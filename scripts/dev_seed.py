"""Connect the two reference runtimes to a local control plane and hand them its public keys (`just seed`).

    cd backend && uv run python ../scripts/dev_seed.py [--test]

Needs the API (`just dev` or `just api`), the runtimes (`just runtimes`) and a bootstrapped Owner (`just bootstrap`).
It signs in as the Owner, connects dev-prod and dev-staging unless they're already connected, and writes each one's
active public key to runtime/.jwt/<slug>.pem, where `just runtimes` picks it up as JWT_VERIFICATION_KEY. Restart the
runtimes after a key changes, then test the connection (here with --test, or in the web app).

Environment: AGNOSTIC_DEV_API_URL (default http://127.0.0.1:8000), AGNOSTIC_DEV_OWNER_EMAIL and
AGNOSTIC_DEV_OWNER_PASSWORD (the `just bootstrap` defaults).
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
KEY_DIR = ROOT / "runtime" / ".jwt"


@dataclass(frozen=True)
class Runtime:
    slug: str
    endpoint_url: str
    env_tag: str
    display_name: str


RUNTIMES = (
    Runtime("dev-prod", "http://127.0.0.1:7777", "production", "dev-prod"),
    Runtime("dev-staging", "http://127.0.0.1:7778", "staging", "dev-staging"),
)


class SeedError(Exception):
    pass


def _problem(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"
    if isinstance(body, dict):
        parts = [str(body.get(key)) for key in ("title", "detail") if body.get(key)]
        return f"HTTP {response.status_code}: " + " — ".join(parts or [str(body)])
    return f"HTTP {response.status_code}: {body}"


def _check(response: httpx.Response, action: str) -> Any:
    if response.is_error:
        raise SeedError(f"{action} failed ({_problem(response)})")
    return response.json()


def sign_in(client: httpx.Client, email: str, password: str) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if response.status_code in {401, 403, 404}:
        raise SeedError(f"can't sign in as {email} ({_problem(response)}). Create the Owner first: just bootstrap")
    body = _check(response, "sign-in")
    session = response.cookies.get("agnostic_session")
    if not session:
        raise SeedError("sign-in returned no agnostic_session cookie")
    # Keep the session even if the cookie is marked Secure (public URL on https) while we talk plain http.
    client.cookies.clear()
    client.cookies.set("agnostic_session", session)
    client.headers["X-CSRF-Token"] = body["csrf_token"]


def ensure_connected(client: httpx.Client, runtime: Runtime, existing: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint = runtime.endpoint_url.rstrip("/")
    for instance in existing:
        if instance["slug"] == runtime.slug or str(instance["endpoint_url"]).rstrip("/") == endpoint:
            print(f"  {runtime.slug}: already connected as {instance['slug']} ({instance['id']})")
            return instance
    response = client.post(
        "/api/v1/instances",
        json={
            "endpoint_url": runtime.endpoint_url,
            "display_name": runtime.display_name,
            "slug": runtime.slug,
            "env_tag": runtime.env_tag,
        },
    )
    if response.is_error:
        raise SeedError(
            f"connecting {runtime.slug} at {runtime.endpoint_url} failed ({_problem(response)}). "
            "Is it running? Start both with: just runtimes"
        )
    body = response.json()
    instance = body["instance"]
    print(f"  {runtime.slug}: connected ({instance['id']}, {runtime.env_tag})")
    for step in body.get("steps", []):
        if step.get("status") in {"failed", "warning"}:
            print(f"    {step['status']}: {step['label']}: {step['detail']}")
    return instance


def write_key(client: httpx.Client, instance: dict[str, Any]) -> bool:
    """Write the active public key to runtime/.jwt/<slug>.pem; True when the file changed."""
    keys = _check(client.get(f"/api/v1/instances/{instance['id']}/keys/public"), "reading public keys")
    active = next((key for key in keys["keys"] if key["status"] == "active"), None)
    if active is None:
        raise SeedError(f"{instance['slug']} has no active key")
    pem = active["public_pem"].strip() + "\n"
    target = KEY_DIR / f"{instance['slug']}.pem"
    if target.exists() and target.read_text(encoding="utf-8") == pem:
        print(f"  {instance['slug']}: key {active['kid']} unchanged ({target.relative_to(ROOT)})")
        return False
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(pem, encoding="utf-8", newline="\n")
    print(f"  {instance['slug']}: wrote key {active['kid']} to {target.relative_to(ROOT)} (aud={keys['audience']})")
    return True


def test_connection(client: httpx.Client, instance: dict[str, Any]) -> bool:
    report = _check(client.post(f"/api/v1/instances/{instance['id']}/test"), f"testing {instance['slug']}")
    print(f"  {instance['slug']}: {'ok' if report['ok'] else 'FAILED'}")
    for step in report["steps"]:
        line = f"    [{step['status']}] {step['label']}: {step['detail']}"
        if step.get("hint") and step["status"] != "ok":
            line += f" ({step['hint']})"
        print(line)
    capabilities = {item["name"]: item["status"] for item in report.get("capabilities", [])}
    available = sorted(name for name, status in capabilities.items() if status == "available")
    print(f"    capabilities available: {', '.join(available) or 'none'}")
    return bool(report["ok"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=os.environ.get("AGNOSTIC_DEV_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--test", action="store_true", help="also run Test connection for each runtime")
    args = parser.parse_args()
    email = os.environ.get("AGNOSTIC_DEV_OWNER_EMAIL", "daniel@localhost.company")
    password = os.environ.get("AGNOSTIC_DEV_OWNER_PASSWORD", "localhost-dev-password")

    try:
        with httpx.Client(base_url=args.api_url, timeout=30.0) as client:
            print(f"Signing in to {args.api_url} as {email}")
            sign_in(client, email, password)
            existing = _check(client.get("/api/v1/instances"), "listing instances")
            print("Instances")
            instances = [ensure_connected(client, runtime, existing) for runtime in RUNTIMES]
            print("Keys")
            changed = [instance["slug"] for instance in instances if write_key(client, instance)]
            if args.test:
                print("Test connection")
                results = [test_connection(client, instance) for instance in instances]
                if not all(results):
                    return 1
            elif changed:
                print(f"\nNext: restart `just runtimes` so {', '.join(changed)} load the new key, then test the")
                print("connection (Settings > Connection in the web app, or: just seed --test).")
            else:
                print("\nKeys are current. Test the connection with: just seed --test")
    except httpx.TransportError as exc:
        print(f"error: can't reach the API at {args.api_url} ({exc}). Start it with: just dev", file=sys.stderr)
        return 1
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
