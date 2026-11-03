"""A Slack stand-in for development: the Web API methods Agnostic uses, incoming webhooks, and a page listing
everything it received.

Point a Slack channel in Settings › Notifications at it:

* bot token mode: any token starting with ``xoxb-``, and ``api_base`` = ``http://localhost:8030/api``;
* incoming webhook mode: ``http://localhost:8030/hooks/<anything>``.

Then open http://localhost:8030 to see the messages, their buttons and links. ``GET /messages`` returns them as
JSON and ``DELETE /messages`` clears them. Standard library only.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

MESSAGES: list[dict[str, Any]] = []
LOCK = threading.Lock()


def member_id(email: str) -> str:
    return "U" + hashlib.sha1(email.lower().encode()).hexdigest()[:8].upper()  # noqa: S324  (an id, not security)


def render(message: dict[str, Any]) -> str:
    body = message.get("body") or {}
    parts = [
        f"<p class=meta>{html.escape(message['kind'])} · {html.escape(str(message.get('target')))} · "
        f"{time.strftime('%H:%M:%S', time.localtime(message['at']))}</p>"
    ]
    for block in body.get("blocks") or [{"type": "section", "text": {"text": body.get("text", "")}}]:
        if block.get("type") == "section":
            parts.append(f"<pre>{html.escape(str((block.get('text') or {}).get('text', '')))}</pre>")
        elif block.get("type") == "actions":
            links = [
                f"<a class=button href='{html.escape(element.get('url', '#'))}'>"
                f"{html.escape((element.get('text') or {}).get('text', 'Open'))}</a>"
                for element in block.get("elements") or []
            ]
            parts.append("<p>" + " ".join(links) + "</p>")
        elif block.get("type") == "context":
            texts = [html.escape(str(element.get("text", ""))) for element in block.get("elements") or []]
            parts.append(f"<p class=meta>{' · '.join(texts)}</p>")
    return "<article>" + "".join(parts) + "</article>"


PAGE = """<!doctype html><meta charset=utf-8><title>Slack mock</title>
<style>body{{font:14px system-ui;margin:2rem;max-width:760px}}article{{border:1px solid #ccc;border-radius:8px;
padding:.5rem 1rem;margin:.75rem 0}}pre{{white-space:pre-wrap;font:inherit}}.meta{{color:#666;font-size:12px}}
.button{{display:inline-block;border:1px solid #888;border-radius:6px;padding:.2rem .6rem;margin-right:.4rem;
text-decoration:none}}</style><h1>Slack mock</h1><p class=meta>{count} messages, newest first ·
<a href=/messages>JSON</a></p>{items}"""


class Handler(BaseHTTPRequestHandler):
    server_version = "slack-mock/1"

    def _json(self, status: int, payload: Any) -> None:  # noqa: ANN401
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode() if self.command != "GET" else ""
        if self.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw or "{}")
        fields = {key: values[0] for key, values in parse_qs(raw).items()}
        fields.update({key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()})
        return fields

    def _record(self, kind: str, target: str, body: dict[str, Any]) -> str:
        ts = f"{time.time():.6f}"
        with LOCK:
            MESSAGES.append({"kind": kind, "target": target, "body": body, "at": time.time(), "ts": ts})
        return ts

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        with LOCK:
            items = list(reversed(MESSAGES))
        if path == "/messages":
            self._json(200, items)
        elif path == "/healthz":
            self._json(200, {"ok": True})
        elif path == "/":
            page = PAGE.format(count=len(items), items="".join(render(item) for item in items)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        else:
            self._json(404, {"ok": False, "error": "not_found"})

    def do_DELETE(self) -> None:
        if urlsplit(self.path).path == "/messages":
            with LOCK:
                MESSAGES.clear()
            self._json(200, {"ok": True})
        else:
            self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._body()
        if path.startswith("/hooks/"):
            self._record("webhook", path.removeprefix("/hooks/"), body)
            payload = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token.startswith("xoxb-"):
            self._json(200, {"ok": False, "error": "invalid_auth"})
        elif path == "/api/users.lookupByEmail":
            email = str(body.get("email") or "")
            self._json(200, {"ok": True, "user": {"id": member_id(email), "profile": {"email": email}}})
        elif path == "/api/chat.postMessage":
            channel = str(body.get("channel") or "")
            ts = self._record("chat.postMessage", channel, body)
            self._json(200, {"ok": True, "channel": channel, "ts": ts})
        else:
            self._json(200, {"ok": False, "error": "unknown_method"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        print(f"slack-mock {self.command} {self.path} {args[1] if len(args) > 1 else ''}", flush=True)  # noqa: T201


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8030"))
    print(f"slack-mock listening on :{port}", flush=True)  # noqa: T201
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104  (inside the container)
