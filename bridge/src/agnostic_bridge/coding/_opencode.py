"""OpenCode (opencode.ai) as a coding agent: ``opencode run --format json``, one process per turn, the
prompt on stdin.

The sandbox gets an ``opencode.json`` with one provider, ``agnostic`` (the OpenAI-compatible SDK provider pointed at
this runtime's model proxy), and the agent's tools as a remote MCP server. Both read the run token from the
environment (``{env:AGNOSTIC_RUN_TOKEN}``). OpenCode's own session id is kept on the Agno session and passed back with
``--session`` while the sandbox lives.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from agno.agents._config import agent_dataclass
from agno.run.agent import RunOutputEvent
from agno.tools.function import Function

from agnostic_bridge.coding._agent import TOKEN_ENV, CodingAgent, EventTranslator, result_text
from agnostic_bridge.coding._llm import MODEL_ALIAS
from agnostic_bridge.coding._providers import SandboxLease, SandboxProvider, write_file

PROVIDER = "agnostic"
PROVIDER_CACHE = "/opt/agnostic/opencode-cache"


def opencode_config(
    llm_url: str, mcp_url: str, *, workspace: str, has_tools: bool, instructions: str | None = None
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{PROVIDER}/{MODEL_ALIAS}",
        "autoupdate": False,
        "share": "disabled",
        "provider": {
            PROVIDER: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Agnostic",
                "options": {"baseURL": llm_url, "apiKey": "{env:" + TOKEN_ENV + "}"},
                "models": {MODEL_ALIAS: {"name": "Agent model", "tool_call": True}},
            }
        },
        # Nobody can answer a permission prompt inside a sandboxed turn; the sandbox is the boundary instead.
        "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny", "external_directory": "deny"},
        "mcp": {},
    }
    if has_tools:
        config["mcp"][PROVIDER] = {
            "type": "remote",
            "url": mcp_url,
            "enabled": True,
            "headers": {"Authorization": "Bearer {env:" + TOKEN_ENV + "}"},
        }
    if instructions:
        config["instructions"] = [f"{workspace}/.agnostic/instructions.md"]
    return config


class OpenCodeTranslator(EventTranslator):
    """``opencode run --format json`` events (one JSON object per line) as Agno run events."""

    def translate(self, event: dict[str, Any]) -> list[RunOutputEvent]:
        session = event.get("sessionID")
        if isinstance(session, str) and session:
            self.session_id = session
        kind = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if kind == "text":
            text = part.get("text")
            return [self.content(text)] if isinstance(text, str) and text else []
        if kind == "reasoning":
            text = part.get("text")
            return [self.reasoning(text)] if isinstance(text, str) and text else []
        if kind == "tool_use":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            call_id = str(part.get("callID") or part.get("id") or "")
            name = str(part.get("tool") or "tool")
            args = state.get("input")
            status = state.get("status")
            if status in ("completed", "error"):
                failed = status == "error"
                output = state.get("error") if failed else state.get("output")
                text = result_text(output)
                metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
                code = metadata.get("exit")
                if isinstance(code, int) and code != 0 and f"exit code {code}" not in text:
                    text = f"{text.rstrip()}\n[exit code {code}]"
                return self.tool_completed(call_id, name, args, text, failed)
            if call_id and call_id not in self.started:
                return [self.tool_started(call_id, name, args)]
            return []
        if kind == "error":
            error = event.get("error")
            message = error.get("data", {}).get("message") if isinstance(error, dict) else None
            self.error = str(message or (error.get("name") if isinstance(error, dict) else error) or "OpenCode failed")
            return []
        return []


@agent_dataclass
class OpenCodeAgent(CodingAgent):
    """OpenCode in a sandbox, thinking with an Agno model. See :class:`CodingAgent` for the arguments."""

    _sdk_name: ClassVar[str] = "opencode"
    _harness: ClassVar[str] = "opencode"
    _exit_ends_turn: ClassVar[bool] = True
    _stdin_is_prompt: ClassVar[bool] = True

    def _config_path(self, lease: SandboxLease) -> str:
        return f"{lease.home}/agnostic/opencode/opencode.json"

    async def _prepare(
        self, provider: SandboxProvider, lease: SandboxLease, callback: str, functions: dict[str, Function]
    ) -> None:
        instructions = self.instructions_text()
        config = opencode_config(
            self.llm_url(callback),
            self.mcp_url(callback),
            workspace=lease.workspace,
            has_tools=bool(functions),
            instructions=instructions,
        )
        await write_file(provider, lease, self._config_path(lease), json.dumps(config, indent=2).encode())
        if instructions:
            await write_file(provider, lease, f"{lease.workspace}/.agnostic/instructions.md", instructions.encode())
        if lease.fresh:
            # The provider package is installed in the image; the root filesystem is read-only at run time.
            script = 'mkdir -p "$1/.cache/opencode" && cp -a "$0/." "$1/.cache/opencode/" 2>/dev/null; true'
            await provider.exec(lease, ["sh", "-c", script, PROVIDER_CACHE, lease.home], timeout=60)

    def _env(self, lease: SandboxLease) -> dict[str, str]:
        return {
            "OPENCODE_CONFIG": self._config_path(lease),
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_SHARE": "1",
            # The only model is the agent's, so the models.dev catalog is not fetched (a fresh HOME would otherwise
            # download it on the first turn, and that turn ends without running).
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "1",
            "OPENCODE_DISABLE_CLAUDE_CODE": "1",
            "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        }

    def _command(
        self, prompt: str, state: dict[str, Any], lease: SandboxLease, has_tools: bool, reasoning: str | None = None
    ) -> list[str]:
        # OpenCode has no effort flag: the run's level is applied to the model behind the proxy.
        argv = ["opencode", "run", "--format", "json", "--thinking", "--model", f"{PROVIDER}/{MODEL_ALIAS}"]
        if state.get("harness_session_id"):
            argv.extend(["--session", str(state["harness_session_id"])])
        return argv

    def _stdin(self, prompt: str) -> bytes:
        # OpenCode reads the message from stdin when none is given, so a long replayed history never meets the
        # command-line length limit.
        return prompt.encode()

    def _translator(self, run_id: str, state: dict[str, Any]) -> EventTranslator:
        return OpenCodeTranslator(self, run_id)

    async def _after_finish(self, process: Any) -> None:
        return None
