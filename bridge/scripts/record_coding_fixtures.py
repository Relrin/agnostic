"""Record what Pi and OpenCode print for one turn, into bridge/tests/fixtures/coding/, from the pinned coding image.

    cd runtime && uv run python ../bridge/scripts/record_coding_fixtures.py [--image agnostic-coding:0.1.0]

Each harness runs in a throwaway container from the coding image against a local callback server: the model proxy
backed by the reference runtime's mock coder (``MockModel(persona="coder")``) and the tool server with one tool. The
translators in agnostic_bridge.coding are tested against these recordings, so record again after bumping a CLI in
runtime/sandbox/coding/Dockerfile and check the tests still pass. Needs Docker; the containers reach the server on
host.docker.internal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

import uvicorn  # noqa: E402
from app.models.mock import MockModel  # noqa: E402
from app.tools import lookup_order  # noqa: E402
from starlette.applications import Starlette  # noqa: E402

from agnostic_bridge.coding._callback import LLM_PREFIX, MCP_PATH, CallbackMiddleware  # noqa: E402
from agnostic_bridge.coding._grants import GrantStore  # noqa: E402
from agnostic_bridge.coding._mcp import flatten_tools  # noqa: E402
from agnostic_bridge.coding._opencode import opencode_config  # noqa: E402
from agnostic_bridge.coding._pi import pi_mcp, pi_models  # noqa: E402

OUT = ROOT / "bridge" / "tests" / "fixtures" / "coding"
PORT = 7799
PROMPT = "write a hello file"


def _container_script(harness: str, callback: str) -> str:
    llm, mcp = callback + LLM_PREFIX, callback + MCP_PATH
    if harness == "pi":
        files = {"/runtime/agnostic/pi/models.json": pi_models(llm), "/runtime/agnostic/pi/mcp.json": pi_mcp(mcp)}
        command = (
            "PI_CODING_AGENT_DIR=/runtime/agnostic/pi pi --mode rpc --provider agnostic --model agent-model "
            "--session-dir /workspace/.agnostic/pi-sessions --session-id fixture -ns -np --no-themes -na --offline"
        )
    else:
        config = opencode_config(llm, mcp, workspace="/workspace", has_tools=True)
        files = {"/runtime/agnostic/opencode/opencode.json": config}
        command = (
            "OPENCODE_CONFIG=/runtime/agnostic/opencode/opencode.json OPENCODE_DISABLE_MODELS_FETCH=1 "
            "opencode run --format json --thinking --model agnostic/agent-model"
        )
    writes = [
        f"mkdir -p {shlex.quote(os.path.dirname(path))} && "
        f"printf %s {shlex.quote(json.dumps(body))} > {shlex.quote(path)}"
        for path, body in files.items()
    ]
    return " && ".join([*writes, "mkdir -p /workspace/outputs", "cd /workspace", command])


async def _record(harness: str, image: str, token: str) -> list[str]:
    callback = f"http://host.docker.internal:{PORT}"
    argv = [
        "docker", "run", "--rm", "-i", "--read-only", "--user", "1000:1000",
        "--tmpfs", "/tmp", "--tmpfs", "/workspace:uid=1000,gid=1000", "--tmpfs", "/runtime:uid=1000,gid=1000",
        "-e", "HOME=/runtime", "-e", "AGNOSTIC_RUN_TOKEN", "--add-host", "host.docker.internal:host-gateway",
        image, "sh", "-c", _container_script(harness, callback),
    ]  # fmt: skip
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "AGNOSTIC_RUN_TOKEN": token},
        limit=16 * 1024 * 1024,
    )
    assert process.stdin is not None and process.stdout is not None
    if harness == "pi":
        process.stdin.write((json.dumps({"id": "prompt", "type": "prompt", "message": PROMPT}) + "\n").encode())
        await process.stdin.drain()
    else:
        process.stdin.write(PROMPT.encode())
        process.stdin.close()
    lines: list[str] = []
    while line := await asyncio.wait_for(process.stdout.readline(), 120):
        text = line.decode().rstrip("\r\n")
        if text.startswith("{"):
            lines.append(text)
        if harness == "pi" and '"agent_settled"' in text:
            process.stdin.close()
    await process.wait()
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", default="agnostic-coding:0.1.0")
    parser.add_argument("harnesses", nargs="*", default=["pi", "opencode"])
    args = parser.parse_args()

    grants = GrantStore()
    functions = asyncio.run(flatten_tools([lookup_order]))
    token, _ = grants.mint(
        agent_id="fixture", session_id="fixture", run_id="fixture", model=MockModel(persona="coder"),
        functions=functions, ttl=900,
    )  # fmt: skip
    server = uvicorn.Server(
        uvicorn.Config(CallbackMiddleware(Starlette(), grants=grants), host="0.0.0.0", port=PORT, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(1.5)

    OUT.mkdir(parents=True, exist_ok=True)
    for harness in args.harnesses:
        lines = asyncio.run(_record(harness, args.image, token))
        if not lines or token in "\n".join(lines):
            raise SystemExit(f"{harness}: nothing usable recorded")
        target = OUT / f"{harness}-write-and-bash.jsonl"
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{harness}: {len(lines)} events -> {target.relative_to(ROOT)}")
    server.should_exit = True


if __name__ == "__main__":
    main()
