"""Audit governance, pure parts: the hash chain, SIEM formats and signatures, archive manifests, AgentOS trail rows."""

import asyncio
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from agnostic_audit.domain.archive import (
    InvalidMonthError,
    Manifest,
    month_bounds,
    object_keys,
    parse_month,
)
from agnostic_audit.domain.chain import ChainVerifier, canonical_json, chain_hash
from agnostic_audit.domain.events import (
    Actor,
    AuditEvent,
    can_request_access,
    event_document,
    event_from_document,
)
from agnostic_audit.domain.siem import (
    DeliveryResult,
    Sink,
    SinkConfigError,
    after_delivery,
    merge_config,
    otlp_logs_request,
    public_config,
    syslog_message,
    to_cef,
    to_ocsf,
    validate_config,
    verify_webhook_signature,
    webhook_body,
    webhook_signature,
)
from agnostic_audit.infrastructure.http import AuditHttp
from agnostic_audit.infrastructure.sinks import SinkTransports
from agnostic_gateway.application.ingest import actor_of, entries, parse_rows, via_of
from agnostic_instances.facade import AuthMode, EnvTag, Instance, InstanceStatus, SubClaimMode
from tests.support.fake_s3 import FakeReceiver

AT = datetime(2026, 10, 31, 17, 4, 12, 381000, tzinfo=UTC)


def event(number: int = 0, **changes: Any) -> AuditEvent:
    base = AuditEvent(
        id=f"evt_{number:026d}",
        occurred_at=AT + timedelta(seconds=number),
        request_id="req_01JBX9T3K2W7",
        actor=Actor(kind="user", id="usr_maya", display="Maya Chen"),
        via="web",
        ip="203.0.113.24",
        client="Mozilla/5.0",
        action="components.set_current",
        resource_kind="component",
        resource_id="agents/support-triage",
        resource_display="agents/support-triage → v4",
        instance_id="ins_prod",
        decision="denied",
        scope_checked="components:write",
        missing_scopes=("components:write",),
        response_status=403,
        summary="Maya Chen tried to make draft v4 current | with = signs",
        diff={"title": "Current version", "lines": [{"op": "+", "text": "v4"}]},
        links=None,
        source="control_plane",
        denial_reason="POST /components/*/set-current needs components:write on prod-agentos.",
    )
    return replace(base, **changes)


def chained(events: list[AuditEvent]) -> list[AuditEvent]:
    previous: str | None = None
    result: list[AuditEvent] = []
    for item in events:
        linked = replace(item, prev_hash=previous)
        linked = replace(linked, hash=chain_hash(previous, linked))
        previous = linked.hash
        result.append(linked)
    return result


# ---------------------------------------------------------------- hash chain


def test_canonical_json_is_stable_and_excludes_the_chain_fields() -> None:
    one = event()
    text = canonical_json(one)
    assert text == canonical_json(replace(one, prev_hash="aa", hash="bb"))
    assert json.loads(text)["occurred_at"] == "2026-10-31T17:04:12.381000Z"
    assert list(json.loads(text)) == sorted(json.loads(text))
    assert '", "' not in text  # no whitespace between tokens
    assert '": "' not in text
    assert chain_hash(None, one) == hashlib.sha256(text.encode()).hexdigest()
    assert chain_hash("abc", one) == hashlib.sha256(("abc" + text).encode()).hexdigest()


def test_document_round_trip_keeps_every_field() -> None:
    original = chained([event(1), event(2, source="agentos", source_event_id="decisions:x:0")])[1]
    restored = event_from_document(json.loads(json.dumps(event_document(original))))
    assert restored == original
    assert canonical_json(restored) == canonical_json(original)


def test_verifier_accepts_an_intact_chain_and_skips_unchained_events() -> None:
    events = chained([event(n) for n in range(5)])
    verifier = ChainVerifier()
    for item in [event(99, hash=None), *events]:
        assert verifier.feed(item)
    assert verifier.result().ok
    assert verifier.result().checked == 5


@pytest.mark.parametrize("tamper", ["changed", "removed", "inserted"])
def test_verifier_finds_the_first_broken_event(tamper: str) -> None:
    events = chained([event(n) for n in range(5)])
    if tamper == "changed":
        events[2] = replace(events[2], summary="edited")
    elif tamper == "removed":
        del events[2]
    else:
        events.insert(2, chained([event(42)])[0])
    verifier = ChainVerifier()
    for item in events:
        if not verifier.feed(item):
            break
    result = verifier.result()
    assert not result.ok
    assert result.first_broken_event_id == events[2].id  # whatever now sits where the chain was touched
    assert result.checked == 3


def test_verifier_with_an_anchor_checks_the_first_link_too() -> None:
    events = chained([event(n) for n in range(3)])
    assert not ChainVerifier(anchor="0" * 64).feed(events[1])
    assert ChainVerifier(anchor=events[0].hash).feed(events[1])


# ---------------------------------------------------------------- SIEM formats


def test_cef_header_and_extension_are_escaped() -> None:
    line = to_cef(event(), product_version="1.2.3")
    assert line.startswith("CEF:0|Agnostic|Control Plane|1.2.3|components.set_current|")
    assert "draft v4 current \\| with = signs|6|" in line  # pipes escaped in the header, "=" is fine there
    extension = line.split("|6|", 1)[1]
    assert "suser=Maya Chen" in extension
    assert "outcome=denied" in extension
    assert "cs2Label=instance cs2=ins_prod" in extension
    assert "msg=Maya Chen tried to make draft v4 current | with \\= signs" in extension
    assert "reason=POST /components/*/set-current needs components:write on prod-agentos." in extension
    allowed = to_cef(event(decision="allowed", denial_reason=None, instance_id=None), product_version="1")
    assert "|3|" in allowed
    assert "cs2Label" not in allowed  # labels only with values


def test_ocsf_maps_to_api_activity_with_status() -> None:
    document = to_ocsf(event(), product_version="1.2.3")
    assert (document["class_uid"], document["category_uid"]) == (6003, 6)
    assert document["activity_id"] == 3  # set_current → Update
    assert document["type_uid"] == 600303
    assert (document["status_id"], document["status"]) == (2, "Failure")
    assert document["time"] == int(AT.timestamp() * 1000)
    assert document["actor"]["user"] == {"uid": "usr_maya", "name": "Maya Chen", "type": "user"}
    assert document["metadata"]["product"] == {"name": "Control Plane", "vendor_name": "Agnostic", "version": "1.2.3"}
    assert document["status_detail"].startswith("POST /components")
    sign_in = to_ocsf(event(action="auth.login", decision="allowed"), product_version="1")
    assert (sign_in["class_uid"], sign_in["activity_id"], sign_in["status"]) == (3002, 1, "Success")


def test_webhook_body_and_hmac_signature() -> None:
    body = webhook_body([event(1), event(2)], "json", product_version="1")
    parsed = json.loads(body)
    assert [item["id"] for item in parsed] == [event(1).id, event(2).id]
    assert parsed[0]["actor"]["display"] == "Maya Chen"
    secret = ("whsec-" + "unit").encode()
    header = webhook_signature(secret, 1_700_000_000, body)
    timestamp, digest = header.split(",")
    assert timestamp == "t=1700000000"
    expected = hmac.new(secret, b"1700000000." + body, hashlib.sha256).hexdigest()
    assert digest == f"v1={expected}"
    assert verify_webhook_signature(secret, header, body, now=1_700_000_100)
    assert not verify_webhook_signature(secret, header, body + b" ", now=1_700_000_100)
    assert not verify_webhook_signature(secret, header, body, now=1_700_001_000)  # too old
    cef = json.loads(webhook_body([event()], "cef", product_version="1"))
    assert cef[0].startswith("CEF:0|")


def test_syslog_frame_is_octet_counted_rfc5424() -> None:
    frame = syslog_message("CEF:0|x", timestamp=AT, hostname="cp 1", severity=4)
    length, message = frame.split(b" ", 1)
    assert int(length) == len(message)
    assert message.decode() == "<108>1 2026-10-31T17:04:12.381000Z cp1 agnostic - audit - CEF:0|x"


def test_otlp_logs_request_shape() -> None:
    request = otlp_logs_request([event()], "json", product_version="1.2.3", observed_at=AT)
    scope_logs = request["resourceLogs"][0]["scopeLogs"][0]
    record = scope_logs["logRecords"][0]
    assert scope_logs["scope"]["name"] == "agnostic.audit"
    assert record["timeUnixNano"] == str(int(AT.timestamp() * 1_000_000) * 1000)
    assert (record["severityNumber"], record["severityText"]) == (13, "WARN")
    assert json.loads(record["body"]["stringValue"])["id"] == event().id
    attributes = {item["key"]: item["value"] for item in record["attributes"]}
    assert attributes["event.name"] == {"stringValue": "components.set_current"}
    assert attributes["http.response.status_code"] == {"intValue": "403"}


def test_sink_config_validation_and_secrets() -> None:
    secret = "s3" + "cr3t"
    config = validate_config("https_webhook", {"url": "https://hooks.example/x", "secret": secret, "headers": {"A": 1}})
    assert config == {"url": "https://hooks.example/x", "secret": secret, "headers": {"A": "1"}}
    assert public_config(config) == {"url": "https://hooks.example/x", "header_names": ["A"]}
    assert merge_config(config, {"url": "https://hooks.example/y"})["secret"] == secret
    with pytest.raises(SinkConfigError, match="https"):
        _ = validate_config("https_webhook", {"url": "http://hooks.example/x"})
    assert validate_config("syslog", {"host": "siem", "tls": False})["port"] == 514
    assert validate_config("syslog", {"host": "siem"})["port"] == 6514
    assert validate_config("otlp_logs", {"endpoint": "https://otel:4318/"})["endpoint"] == "https://otel:4318"


def test_failing_status_is_announced_once() -> None:
    sink = Sink(
        id="sink_1",
        name="SIEM",
        kind="https_webhook",
        format="json",
        config={},
        enabled=True,
        status="ok",
        failure_count=0,
        last_event_at=None,
        last_error=None,
        created_by="usr_1",
        created_at=AT,
    )
    failed = DeliveryResult(ok=False, status_code=503)
    first = after_delivery(sink, failed)
    assert (first.status, first.failure_count, first.announce) == ("ok", 1, False)
    third = after_delivery(replace(sink, failure_count=2), failed)
    assert (third.status, third.announce, third.last_error) == ("failing", True, "HTTP 503")
    fourth = after_delivery(replace(sink, status="failing", failure_count=3), failed)
    assert (fourth.status, fourth.announce) == ("failing", False)
    recovered = after_delivery(replace(sink, status="failing", failure_count=4), DeliveryResult(ok=True))
    assert (recovered.status, recovered.failure_count, recovered.last_error) == ("ok", 0, None)


# ---------------------------------------------------------------- archives


def test_months_and_object_keys() -> None:
    assert parse_month("2025-08") == datetime(2025, 8, 1, tzinfo=UTC)
    assert month_bounds("2025-12") == (datetime(2025, 12, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(InvalidMonthError):
        _ = parse_month("2025-13")
    assert object_keys("/audit/prod/", "2025-08") == (
        "audit/prod/audit-events-2025-08.jsonl.zst",
        "audit/prod/audit-events-2025-08.manifest.json",
    )
    assert object_keys("", "2025-08")[0] == "audit-events-2025-08.jsonl.zst"


def test_manifest_round_trip() -> None:
    manifest = Manifest(month="2025-08", event_count=3, sha256="ab" * 32, bytes=120, chain_head=None, created_at=AT)
    assert Manifest.parse(manifest.to_json()) == manifest
    with pytest.raises(ValueError, match="format"):
        _ = Manifest.parse(json.dumps({"format": "csv"}).encode())


def test_can_request_access_only_for_people_denied_on_an_instance() -> None:
    assert can_request_access(event())
    assert not can_request_access(event(decision="allowed"))
    assert not can_request_access(event(instance_id=None))
    assert not can_request_access(event(actor=Actor(kind="service_account", id="sa:bot", display="sa:bot")))


# ---------------------------------------------------------------- AgentOS trail rows

INSTANCE = Instance(
    id="ins_prod",
    slug="prod-agentos",
    display_name="prod-agentos",
    env_tag=EnvTag.PRODUCTION,
    endpoint_url="http://prod.agentos.test",
    os_id="fake-prod",
    agno_version="3.1.12",
    os_version="3.1.12",
    auth_mode=AuthMode.JWT,
    user_isolation=True,
    status=InstanceStatus.CONNECTED,
    last_seen_at=None,
    latency_ms=None,
    sub_claim_mode=SubClaimMode.USER_ID,
    tls_verify=True,
    ca_bundle_pem=None,
    has_security_key=False,
    previous_agno_version=None,
    version_changed_at=None,
    created_at=AT,
    updated_at=AT,
    version=1,
)


def test_decision_rows_become_audit_entries() -> None:
    body = {
        "data": [
            {
                "created_at": 1_761_930_000,
                "actor": "usr_maya",
                "action": "access.denied",
                "target": "POST /components/x/configs/4/set-current",
                "metadata": {"required": ["components:write"], "token": "a1b2", "scopes": ["agents:read"]},
            },
            {
                "created_at": 1_761_930_000,
                "actor": "sa:zendesk-bridge",
                "action": "access.allowed",
                "target": "POST /agents/support-triage/runs",
                "metadata": {"required": ["agents:run"], "token": "c3d4", "scopes": ["agents:run"]},
            },
        ],
        "meta": {"page": 1, "limit": 500, "total_pages": 1, "total_count": 2},
    }
    rows, pages = parse_rows(body)
    assert pages == 1
    denied, allowed = entries("decisions", rows, INSTANCE)
    assert denied.decision == "denied"
    assert denied.missing_scopes == ("components:write",)
    assert denied.denial_reason is not None
    assert "components:write" in denied.denial_reason
    assert (denied.actor.kind, denied.via, denied.instance_id) == ("user", "jwt", "ins_prod")
    assert (allowed.actor.kind, allowed.via, allowed.decision) == ("service_account", "native-pat", "allowed")
    assert denied.source_event_id != allowed.source_event_id
    assert denied.occurred_at == datetime.fromtimestamp(1_761_930_000, UTC)


def test_identical_rows_in_one_second_stay_distinct_and_stable() -> None:
    row = {"created_at": 1_761_930_000, "actor": "usr_a", "action": "access.allowed", "target": "GET /agents"}
    rows, _ = parse_rows([row, dict(row)])
    first = [entry.source_event_id for entry in entries("decisions", rows, INSTANCE)]
    again = [entry.source_event_id for entry in entries("decisions", parse_rows([row, dict(row)])[0], INSTANCE)]
    assert len(set(first)) == 2
    assert first == again


def test_change_rows_and_subjects() -> None:
    rows, _ = parse_rows(
        [
            {
                "created_at": "2026-10-31T10:00:00Z",
                "actor": None,
                "action": "user.assigned",
                "target": "usr_b",
                "before": [],
                "after": ["operator"],
            }
        ]
    )
    (change,) = entries("audit", rows, INSTANCE)
    assert change.action == "agentos.user.assigned"
    assert change.actor.kind == "anonymous"
    assert change.diff is not None
    assert change.diff["lines"] == [{"op": "+", "text": "operator"}]
    assert actor_of("agnostic-system").kind == "system"
    assert actor_of("maya@northwind.dev").kind == "user"
    assert via_of("usr_a", {"token": "agno_pat_x"}) == "native-pat"


# ---------------------------------------------------------------- transports (local sockets, in-process HTTP)


def sink_of(kind: str, sink_format: str, config: dict[str, Any]) -> Sink:
    return Sink(
        id="sink_1",
        name="SIEM",
        kind=kind,  # pyright: ignore[reportArgumentType]
        format=sink_format,  # pyright: ignore[reportArgumentType]
        config=config,
        enabled=True,
        status="ok",
        failure_count=0,
        last_event_at=None,
        last_error=None,
        created_by="usr_1",
        created_at=AT,
    )


async def test_syslog_over_tcp_sends_octet_counted_cef() -> None:
    received: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.read())
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transports = SinkTransports(AuditHttp())
    try:
        result = await transports.send(
            sink_of("syslog", "cef", {"host": "127.0.0.1", "port": port, "tls": False}), [event(1), event(2)]
        )
        await asyncio.sleep(0.05)
    finally:
        server.close()
        await server.wait_closed()
    assert result.ok, result.error
    data = b"".join(received)
    length, rest = data.split(b" ", 1)
    first, second = rest[: int(length)], rest[int(length) :]
    assert first.startswith(b"<108>1 2026-10-31T17:04:13.381000Z agnostic agnostic - audit - CEF:0|Agnostic|")
    assert second.split(b" ", 1)[1].startswith(b"<108>1 ")
    refused = await transports.send(
        sink_of("syslog", "json", {"host": "127.0.0.1", "port": 1, "tls": False}), [event()]
    )
    assert refused.ok is False
    assert refused.error


async def test_otlp_posts_to_v1_logs() -> None:
    receiver = FakeReceiver()
    http = AuditHttp(httpx.ASGITransport(app=receiver.app))
    transports = SinkTransports(http)
    sink = sink_of("otlp_logs", "ocsf", {"endpoint": "https://otel.test:4318", "headers": {"x-api-key": "k"}})
    result = await transports.send(sink, [event()])
    await http.aclose()
    assert (result.ok, result.status_code) == (True, 204)
    (request,) = receiver.received
    assert request["path"] == "v1/logs"
    assert request["headers"]["x-api-key"] == "k"
    body = json.loads(request["body"])
    record = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert json.loads(record["body"]["stringValue"])["class_uid"] == 6003
