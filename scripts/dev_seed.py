"""Connect the two reference runtimes to a local control plane, hand them its public keys and seed Studio data.

    cd backend && uv run python ../scripts/dev_seed.py [--test]

Needs the API (`just dev` or `just api`), the runtimes (`just runtimes`) and a bootstrapped Owner (`just bootstrap`).
It signs in as the Owner, connects dev-prod and dev-staging unless they're already connected, and writes each one's
active public key to runtime/.jwt/<slug>.pem, where `just runtimes` picks it up as JWT_VERIFICATION_KEY. Restart the
runtimes after a key changes, then test the connection (here with --test, or in the web app).

It also creates the DB component `support-triage-studio` on each runtime through the gateway (AgentOS `/components`):
published versions v1-v3 with v3 current, and a draft v4. Versions that already exist are left alone. On dev-prod it
creates the `daily-brief` schedule (03:00 UTC). With --trigger-daily-brief it runs it now; start the runtimes with
RUNTIME_FAULTS=web_search=timeout first and the run fails like a production one, ready for "Why did daily-brief fail
last night?" in Ask your OS.

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


STUDIO_COMPONENT = "support-triage-studio"


def _tool(name: str, description: str, properties: dict[str, str], **flags: Any) -> dict[str, Any]:
    """A tool as ``Function.to_dict()`` writes it; the runtime's registry reattaches the code by name."""
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {key: {"type": kind} for key, kind in properties.items()},
            "required": list(properties),
            "additionalProperties": False,
        },
        **flags,
    }


LOOKUP_ORDER = _tool("lookup_order", "Look up an order's status.", {"order_id": "string"})
SEARCH_KNOWLEDGE = _tool("search_knowledge", "Search the help center.", {"query": "string"})
REFUND_CUSTOMER = _tool(
    "refund_customer",
    "Refund a customer. Blocks until a human approves.",
    {"customer_id": "string", "amount": "number", "reason": "string"},
    requires_confirmation=True,
    approval_type="required",
)


def _studio_config(tools: list[dict[str, Any]], instructions: str) -> dict[str, Any]:
    return {
        "id": STUDIO_COMPONENT,
        "name": STUDIO_COMPONENT,
        "description": "Support triage, built in Studio.",
        "model": {"id": "agnostic-mock", "provider": "Agnostic", "name": "MockModel"},
        "tools": tools,
        "instructions": instructions,
        "markdown": True,
        "store_events": True,
    }


# (version, stage, notes, config); v3 is the current version.
STUDIO_VERSIONS: tuple[tuple[int, str, str, dict[str, Any]], ...] = (
    (
        1,
        "published",
        "First cut: order lookups and help-center answers",
        _studio_config(
            [LOOKUP_ORDER, SEARCH_KNOWLEDGE], "Triage the ticket and answer from the help center when you can."
        ),
    ),
    (
        2,
        "published",
        "Refunds through refund_customer (needs approval)",
        _studio_config(
            [LOOKUP_ORDER, SEARCH_KNOWLEDGE, REFUND_CUSTOMER],
            "Triage the ticket. Refunds go through refund_customer, which a human approves.",
        ),
    ),
    (
        3,
        "published",
        "Cite the help-center article",
        _studio_config(
            [LOOKUP_ORDER, SEARCH_KNOWLEDGE, REFUND_CUSTOMER],
            "Triage the ticket and cite the help-center article you used. "
            "Refunds go through refund_customer, which a human approves.",
        ),
    ),
    (
        4,
        "draft",
        "Draft: ask for the order id before refunding",
        _studio_config(
            [LOOKUP_ORDER, SEARCH_KNOWLEDGE, REFUND_CUSTOMER],
            "Triage the ticket and cite the help-center article you used. Ask for the order id before any refund; "
            "refunds go through refund_customer, which a human approves.",
        ),
    ),
)
STUDIO_CURRENT = 3


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


def seed_studio_component(client: httpx.Client, prefix: str, label: str) -> None:
    """Create support-triage-studio v1-v4 under ``prefix`` (the gateway's ``/api/v1/instances/<id>/os``)."""
    base = f"{prefix}/components/{STUDIO_COMPONENT}"
    response = client.get(base)
    if response.status_code == 404:
        version, stage, notes, config = STUDIO_VERSIONS[0]
        _check(
            client.post(
                f"{prefix}/components",
                json={
                    "component_id": STUDIO_COMPONENT,
                    "component_type": "agent",
                    "name": STUDIO_COMPONENT,
                    "description": config["description"],
                    "config": config,
                    "stage": stage,
                    "notes": notes,
                    "set_current": True,
                },
            ),
            f"creating {STUDIO_COMPONENT}",
        )
    else:
        _check(response, f"reading {STUDIO_COMPONENT}")
    listed = _check(client.get(f"{base}/configs"), f"listing {STUDIO_COMPONENT} versions")
    items = listed.get("data", listed) if isinstance(listed, dict) else listed
    existing = {int(item["version"]) for item in items}
    created = []
    for version, stage, notes, config in STUDIO_VERSIONS:
        if version in existing:
            continue
        body = {"config": config, "version": version, "stage": stage, "notes": notes, "set_current": False}
        _check(client.post(f"{base}/configs", json=body), f"creating {STUDIO_COMPONENT} v{version}")
        created.append(f"v{version}")
    component = _check(client.get(base), f"reading {STUDIO_COMPONENT}")
    if component.get("current_version") != STUDIO_CURRENT:
        _check(client.post(f"{base}/configs/{STUDIO_CURRENT}/set-current"), f"making v{STUDIO_CURRENT} current")
    summary = f"created {', '.join(created)}" if created else "versions unchanged"
    print(f"  {label}: {STUDIO_COMPONENT} {summary}; v{STUDIO_CURRENT} current, draft v{STUDIO_VERSIONS[-1][0]}")


def seed_components(client: httpx.Client, instance: dict[str, Any]) -> None:
    try:
        seed_studio_component(client, f"/api/v1/instances/{instance['id']}/os", instance["slug"])
    except SeedError as exc:
        # Not fatal: a runtime that still trusts an old key rejects the call until it's restarted.
        print(f"  {instance['slug']}: skipped ({exc}). Restart the runtimes, then run `just seed` again.")


DAILY_BRIEF = {
    "name": "daily-brief",
    "description": "Research the day's agent platform news and write the morning brief.",
    "cron_expr": "0 3 * * *",
    "timezone": "UTC",
    "method": "POST",
    "endpoint": "/workflows/daily-brief/runs",
    "payload": {"message": "Search the web for agent platform news and brief me."},
    "max_retries": 1,
    "retry_delay_seconds": 60,
}


def seed_daily_brief(client: httpx.Client, instance: dict[str, Any], *, trigger: bool) -> None:
    """The daily-brief schedule on ``instance``, created once; ``trigger`` runs it now."""
    base = f"/api/v1/instances/{instance['id']}/schedules"
    try:
        listed = _check(client.get(base, params={"limit": 100}), "listing schedules")
        found = next((item for item in listed.get("data", []) if item.get("name") == DAILY_BRIEF["name"]), None)
        if found is None:
            found = _check(client.post(base, json=DAILY_BRIEF), "creating the daily-brief schedule")
            print(f"  {instance['slug']}: daily-brief schedule created (03:00 UTC)")
        else:
            print(f"  {instance['slug']}: daily-brief schedule exists")
        if trigger:
            run = _check(client.post(f"{base}/{found['id']}/trigger"), "triggering daily-brief")
            print(f"  {instance['slug']}: daily-brief triggered ({run.get('status', 'started')})")
    except SeedError as exc:
        print(f"  {instance['slug']}: schedule skipped ({exc}).")


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
    parser.add_argument(
        "--trigger-daily-brief",
        action="store_true",
        help="run the daily-brief schedule on dev-prod now (with RUNTIME_FAULTS=web_search=timeout it fails)",
    )
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
            print("Components")
            for instance in instances:
                seed_components(client, instance)
            print("Schedules")
            seed_daily_brief(client, instances[0], trigger=args.trigger_daily_brief)
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
