"""Pi (pi.dev) as a coding agent: ``pi --mode rpc``, its prompt on stdin and its JSONL session events on stdout.

Pi's agent directory in the sandbox holds a ``models.json`` with one provider, ``agnostic``, pointing at this
runtime's model proxy, and an ``mcp.json`` with the agent's tools when it has any. Both read the run token from the
environment (``${AGNOSTIC_RUN_TOKEN}``), so neither file holds a secret. Pi's own session for an Agno session is kept
in the workspace under the Agno session id, so the next turn in the same sandbox resumes it.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from agno.agents._config import agent_dataclass
from agno.agents.base import ExternalRunWarningEvent
from agno.run.agent import RunOutputEvent
from agno.tools.function import Function

from agnostic_bridge.coding._agent import TOKEN_ENV, CodingAgent, EventTranslator, result_text
from agnostic_bridge.coding._llm import MODEL_ALIAS
from agnostic_bridge.coding._providers import ProcessStream, SandboxLease, SandboxProvider, write_file

PROVIDER = "agnostic"
_SESSION_ID = re.compile(r"[^A-Za-z0-9_-]")


def pi_models(callback_llm_url: str) -> dict[str, Any]:
    return {
        "providers": {
            PROVIDER: {
                "name": "Agnostic",
                "baseUrl": callback_llm_url,
                "api": "openai-completions",
                "apiKey": "${" + TOKEN_ENV + "}",
                "authHeader": True,
                "compat": {
                    "supportsStore": False,
                    "supportsDeveloperRole": False,
                    "supportsReasoningEffort": False,
                    "supportsUsageInStreaming": True,
                    "maxTokensField": "max_tokens",
                },
                "models": [
                    {
                        "id": MODEL_ALIAS,
                        "name": "Agent model",
                        "reasoning": False,
                        "input": ["text", "image"],
                        "contextWindow": 128000,
                        "maxTokens": 16384,
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    }
                ],
            }
        }
    }


def pi_mcp(callback_mcp_url: str) -> dict[str, Any]:
    return {
        "mcpServers": {
            PROVIDER: {
                "type": "http",
                "url": callback_mcp_url,
                "headers": {"Authorization": "Bearer ${" + TOKEN_ENV + "}"},
                "description": "Tools of the Agnostic agent this sandbox runs for",
                "exposure": "direct",
                "timeout": 120,
            }
        }
    }


def pi_session_id(agno_session_id: str) -> str:
    return _SESSION_ID.sub("-", agno_session_id)[:96] or "session"


class PiTranslator(EventTranslator):
    """Pi session events (shared by its JSON and RPC modes) as Agno run events."""

    native_session: str | None = None

    def translate(self, event: dict[str, Any]) -> list[RunOutputEvent]:
        kind = event.get("type")
        if kind == "response":
            if event.get("command") == "prompt":
                if event.get("success") is False:
                    self.error = str(event.get("error") or "Pi refused the prompt")
                    self.finished = True
                elif (event.get("data") or {}).get("disposition") == "handled":
                    self.finished = True  # handled without a run: no agent_settled follows
            return []
        if kind == "session" and isinstance(event.get("id"), str):
            self.session_id = event["id"]
            return []
        if kind == "message_update":
            update = event.get("assistantMessageEvent") or {}
            delta = update.get("delta")
            if update.get("type") == "text_delta" and isinstance(delta, str) and delta:
                return [self.content(delta)]
            if update.get("type") == "thinking_delta" and isinstance(delta, str) and delta:
                return [self.reasoning(delta)]
            return []
        if kind == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant" and message.get("stopReason") == "error":
                self.error = str(message.get("errorMessage") or "The model call failed")
            return []
        if kind == "tool_execution_start":
            call_id = str(event.get("toolCallId") or "")
            return [self.tool_started(call_id, str(event.get("toolName") or "tool"), event.get("args"))]
        if kind == "tool_execution_end":
            call_id = str(event.get("toolCallId") or "")
            result = event.get("result")
            text = result_text(result)
            code = None
            if isinstance(result, dict):
                for key in ("structuredContent", "details"):
                    block = result.get(key)
                    if isinstance(block, dict):
                        found = block.get("exit_code", block.get("exitCode"))
                        code = found if isinstance(found, int) else code
            if isinstance(code, int) and code != 0 and f"exit code {code}" not in text:
                text = f"{text.rstrip()}\n[exit code {code}]"
            return self.tool_completed(
                call_id, str(event.get("toolName") or "tool"), event.get("args"), text, bool(event.get("isError"))
            )
        if kind in ("auto_retry_start", "extension_error") or (kind == "compaction_end" and event.get("errorMessage")):
            warning = {
                "type": kind,
                "message": str(event.get("errorMessage") or event.get("error") or kind),
            }
            return [ExternalRunWarningEvent(run_id=self.run_id, agent_id=self.agent.get_id(), warning=warning)]
        if kind == "auto_retry_end" and event.get("success") is False:
            self.error = str(event.get("finalError") or "The model call failed after retries")
            return []
        if kind == "agent_settled":
            self.finished = True
            self.session_id = self.native_session
            if event.get("aborted"):
                self.error = self.error or "Pi aborted the turn"
        return []


@agent_dataclass
class PiAgent(CodingAgent):
    """Pi in a sandbox, thinking with an Agno model. See :class:`CodingAgent` for the arguments."""

    _sdk_name: ClassVar[str] = "pi"
    _harness: ClassVar[str] = "pi"

    def _agent_dir(self, lease: SandboxLease) -> str:
        return f"{lease.home}/agnostic/pi"

    def _session_dir(self, lease: SandboxLease) -> str:
        return f"{lease.workspace}/.agnostic/pi-sessions"

    async def _prepare(
        self, provider: SandboxProvider, lease: SandboxLease, callback: str, functions: dict[str, Function]
    ) -> None:
        agent_dir = self._agent_dir(lease)
        await write_file(
            provider,
            lease,
            f"{agent_dir}/models.json",
            json.dumps(pi_models(self.llm_url(callback)), indent=2).encode(),
        )
        settings = {"quietStartup": True, "defaultProvider": PROVIDER, "defaultModel": MODEL_ALIAS}
        await write_file(provider, lease, f"{agent_dir}/settings.json", json.dumps(settings, indent=2).encode())
        mcp = pi_mcp(self.mcp_url(callback)) if functions else {"mcpServers": {}}
        await write_file(provider, lease, f"{agent_dir}/mcp.json", json.dumps(mcp, indent=2).encode())

    def _env(self, lease: SandboxLease) -> dict[str, str]:
        return {
            "PI_CODING_AGENT_DIR": self._agent_dir(lease),
            "PI_OFFLINE": "1",
            "PI_TELEMETRY": "0",
            "PI_SKIP_VERSION_CHECK": "1",
        }

    def _command(self, prompt: str, state: dict[str, Any], lease: SandboxLease, has_tools: bool) -> list[str]:
        session_id = state.get("native_session") or pi_session_id(lease.session_id)
        state["native_session"] = session_id
        argv = [
            "pi",
            "--mode",
            "rpc",
            "--provider",
            PROVIDER,
            "--model",
            MODEL_ALIAS,
            "--session-dir",
            self._session_dir(lease),
            "--session-id",
            session_id,
            # Not --no-extensions: MCP support is one of Pi's built-in extensions.
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-approve",
            "--offline",
        ]
        if not has_tools:
            argv.append("--no-mcp")
        if self.spec.thinking:
            argv.extend(["--thinking", self.spec.thinking])
        instructions = self.instructions_text()
        if instructions:
            argv.extend(["--append-system-prompt", instructions])
        return argv

    def _stdin(self, prompt: str) -> bytes:
        return (json.dumps({"id": "prompt", "type": "prompt", "message": prompt}) + "\n").encode()

    def _translator(self, run_id: str, state: dict[str, Any]) -> EventTranslator:
        translator = PiTranslator(self, run_id)
        # Pi keeps the session under the id it was given; once a turn ran in this sandbox the next one resumes it.
        translator.native_session = state.get("native_session")
        return translator

    async def _ainterrupt_run(self, handle: Any) -> None:
        if isinstance(handle, ProcessStream):
            await handle.write(b'{"type":"abort"}\n')
            await handle.terminate(grace=3.0)
