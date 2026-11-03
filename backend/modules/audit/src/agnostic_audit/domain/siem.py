"""Streaming audit events to a SIEM.

Payload formats (JSON, OCSF, CEF), webhook signatures, syslog framing and OTLP log requests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from agnostic_audit.domain.events import Actor, AuditEvent, event_document, iso_utc

type SinkKind = Literal["https_webhook", "syslog", "otlp_logs"]
type SinkFormat = Literal["json", "ocsf", "cef"]
type SinkStatus = Literal["ok", "failing", "paused"]

SINK_KINDS: tuple[SinkKind, ...] = ("https_webhook", "syslog", "otlp_logs")
SINK_FORMATS: tuple[SinkFormat, ...] = ("json", "ocsf", "cef")
SIGNATURE_HEADER = "X-Agnostic-Signature"
COUNT_HEADER = "X-Agnostic-Event-Count"
FAILURES_BEFORE_FAILING = 3
"""Consecutive failed deliveries before a sink shows as failing (and admins are told once)."""

VENDOR = "Agnostic"
PRODUCT = "Control Plane"
OCSF_VERSION = "1.3.0"

SECRET_KEYS = frozenset({"secret", "headers"})
"""Config keys whose values are never returned by the API."""


@dataclass(frozen=True, slots=True)
class Sink:
    id: str
    name: str
    kind: SinkKind
    format: SinkFormat
    config: Mapping[str, Any]
    """Decrypted: ``url``/``secret``/``headers`` (webhook), ``host``/``port``/``tls``/``tls_verify``/``ca_pem``
    (syslog), ``endpoint``/``headers`` (OTLP)."""
    enabled: bool
    status: SinkStatus
    failure_count: int
    last_event_at: datetime | None
    last_error: str | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    ok: bool
    status_code: int | None = None
    error: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SinkHealth:
    """What a delivery attempt does to the sink's status; ``announce`` is set once, on the move to failing."""

    status: SinkStatus
    failure_count: int
    last_error: str | None
    announce: bool


def after_delivery(sink: Sink, result: DeliveryResult) -> SinkHealth:
    if result.ok:
        return SinkHealth(
            status="ok" if sink.status != "paused" else "paused", failure_count=0, last_error=None, announce=False
        )
    failures = sink.failure_count + 1
    failing = failures >= FAILURES_BEFORE_FAILING
    status: SinkStatus = "paused" if sink.status == "paused" else ("failing" if failing else sink.status)
    return SinkHealth(
        status=status,
        failure_count=failures,
        last_error=result.error or (f"HTTP {result.status_code}" if result.status_code else "delivery failed"),
        announce=failing and sink.status == "ok",
    )


def public_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Config without secrets: header values are dropped, only their names stay."""
    visible = {key: value for key, value in config.items() if key not in SECRET_KEYS}
    headers = config.get("headers")
    if isinstance(headers, Mapping):
        visible["header_names"] = sorted(str(name) for name in headers)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return visible


# ---------------------------------------------------------------- formats


def _severity(event: AuditEvent) -> int:
    """CEF severity 0-10."""
    return 6 if event.decision == "denied" else 3


def _epoch_ms(moment: datetime) -> int:
    return int(moment.astimezone(UTC).timestamp() * 1000)


_VERBS: Mapping[str, tuple[int, str]] = {
    "create": (1, "Create"),
    "invite": (1, "Create"),
    "read": (2, "Read"),
    "list": (2, "Read"),
    "request": (2, "Read"),
    "update": (3, "Update"),
    "resolve": (3, "Update"),
    "set_current": (3, "Update"),
    "delete": (4, "Delete"),
    "revoke": (4, "Delete"),
    "remove": (4, "Delete"),
}


def to_ocsf(event: AuditEvent, *, product_version: str) -> dict[str, Any]:
    """OCSF: sign-ins as Authentication (3002), everything else as API Activity (6003) with the decision as status."""
    if event.action.startswith("auth.") and event.action.split(".")[-1] in {"login", "logout", "failed", "signin"}:
        class_uid, category_uid, class_name, category_name = 3002, 3, "Authentication", "Identity & Access Management"
        activity_id, activity_name = (2, "Logoff") if event.action.endswith("logout") else (1, "Logon")
    else:
        class_uid, category_uid, class_name, category_name = 6003, 6, "API Activity", "Application Activity"
        activity_id, activity_name = _VERBS.get(event.action.rsplit(".", 1)[-1], (99, "Other"))
    denied = event.decision == "denied"
    document: dict[str, Any] = {
        "class_uid": class_uid,
        "class_name": class_name,
        "category_uid": category_uid,
        "category_name": category_name,
        "activity_id": activity_id,
        "activity_name": activity_name,
        "type_uid": class_uid * 100 + activity_id,
        "time": _epoch_ms(event.occurred_at),
        "severity_id": 3 if denied else 1,
        "severity": "Medium" if denied else "Informational",
        "status_id": 2 if denied else 1,
        "status": "Failure" if denied else "Success",
        "message": event.summary,
        "metadata": {
            "version": OCSF_VERSION,
            "uid": event.id,
            "correlation_uid": event.request_id,
            "original_time": iso_utc(event.occurred_at),
            "product": {"name": PRODUCT, "vendor_name": VENDOR, "version": product_version},
            "log_name": "audit",
        },
        "actor": {
            "user": {"uid": event.actor.id, "name": event.actor.display, "type": event.actor.kind},
        },
        "api": {
            "operation": event.action,
            "request": {"uid": event.request_id} if event.request_id else {},
            "response": {"code": event.response_status} if event.response_status is not None else {},
        },
        "src_endpoint": {"ip": event.ip} if event.ip else {},
        "http_request": {"user_agent": event.client} if event.client else {},
        "unmapped": {
            "decision": event.decision,
            "scope_checked": event.scope_checked,
            "missing_scopes": list(event.missing_scopes),
            "denial_reason": event.denial_reason,
            "instance_id": event.instance_id,
            "via": event.via,
            "source": event.source,
        },
    }
    if event.resource_id or event.resource_display:
        document["resources"] = [
            {"uid": event.resource_id, "name": event.resource_display, "type": event.resource_kind},
        ]
    if denied and event.denial_reason:
        document["status_detail"] = event.denial_reason
    return document


def _cef_header(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _cef_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("=", "\\=").replace("\r", "\\r").replace("\n", "\\n")


def to_cef(event: AuditEvent, *, product_version: str) -> str:
    """``CEF:0|Agnostic|Control Plane|<version>|<action>|<summary>|<severity>|<extension>``."""
    extension: list[tuple[str, str | int | None]] = [
        ("rt", _epoch_ms(event.occurred_at)),
        ("externalId", event.id),
        ("suid", event.actor.id),
        ("suser", event.actor.display),
        ("cs1Label", "actorKind"),
        ("cs1", event.actor.kind),
        ("src", event.ip),
        ("requestClientApplication", event.client),
        ("act", event.action),
        ("outcome", event.decision),
        ("cs2Label", "instance"),
        ("cs2", event.instance_id),
        ("cs3Label", "scope"),
        ("cs3", event.scope_checked or (", ".join(event.missing_scopes) or None)),
        ("cs4Label", "requestId"),
        ("cs4", event.request_id),
        ("cs5Label", "resource"),
        ("cs5", event.resource_display or event.resource_id),
        ("cs6Label", "source"),
        ("cs6", event.source),
        ("cn1Label", "responseStatus"),
        ("cn1", event.response_status),
        ("reason", event.denial_reason),
        ("msg", event.summary),
    ]
    labels_with_values = {key.removesuffix("Label") for key, _ in extension if key.endswith("Label")}
    present = {key for key, value in extension if value is not None and key in labels_with_values}
    parts = [
        f"{key}={_cef_value(str(value))}"
        for key, value in extension
        if value is not None and (not key.endswith("Label") or key.removesuffix("Label") in present)
    ]
    header = "|".join(
        _cef_header(item)
        for item in ("CEF:0", VENDOR, PRODUCT, product_version, event.action, event.summary, str(_severity(event)))
    )
    return f"{header}|{' '.join(parts)}"


def format_event(event: AuditEvent, sink_format: SinkFormat, *, product_version: str) -> dict[str, Any] | str:
    if sink_format == "ocsf":
        return to_ocsf(event, product_version=product_version)
    if sink_format == "cef":
        return to_cef(event, product_version=product_version)
    return event_document(event)


def as_text(formatted: dict[str, Any] | str) -> str:
    return formatted if isinstance(formatted, str) else json.dumps(formatted, separators=(",", ":"), sort_keys=True)


# ---------------------------------------------------------------- transports


def webhook_body(events: Sequence[AuditEvent], sink_format: SinkFormat, *, product_version: str) -> bytes:
    """A JSON array: event documents (json, ocsf) or CEF lines (cef)."""
    items = [format_event(event, sink_format, product_version=product_version) for event in events]
    return json.dumps(items, separators=(",", ":"), sort_keys=True).encode("utf-8")


def webhook_signature(secret: bytes, timestamp: int, body: bytes) -> str:
    """``t=<unix>,v1=<hex HMAC-SHA256(secret, "<unix>.<body>")>``; receivers recompute and compare."""
    digest = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def verify_webhook_signature(secret: bytes, header: str, body: bytes, *, now: int, tolerance: int = 300) -> bool:
    try:
        fields = dict(part.split("=", 1) for part in header.split(","))
        timestamp = int(fields["t"])
    except KeyError, ValueError:
        return False
    if abs(now - timestamp) > tolerance:
        return False
    return hmac.compare_digest(webhook_signature(secret, timestamp, body), header)


SYSLOG_FACILITY = 13
"""``log audit``."""


def syslog_message(
    body: str,
    *,
    timestamp: datetime,
    hostname: str,
    app_name: str = "agnostic",
    msgid: str = "audit",
    severity: int = 6,
) -> bytes:
    """One RFC 5424 message, octet-counted for TCP/TLS transport (RFC 6587): ``<len> <PRI>1 TIMESTAMP ...``."""
    pri = SYSLOG_FACILITY * 8 + severity

    def field(value: str) -> str:
        cleaned = "".join(ch for ch in value if 33 <= ord(ch) <= 126)  # noqa: PLR2004  (PRINTUSASCII)
        return cleaned[:255] or "-"

    line = f"<{pri}>1 {iso_utc(timestamp)} {field(hostname)} {field(app_name)} - {field(msgid)} - {body}"
    encoded = line.encode("utf-8")
    return f"{len(encoded)} ".encode() + encoded


def syslog_severity(event: AuditEvent) -> int:
    return 4 if event.decision == "denied" else 6  # warning / informational


def _attribute(key: str, value: str | int | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def otlp_logs_request(
    events: Sequence[AuditEvent], sink_format: SinkFormat, *, product_version: str, observed_at: datetime
) -> dict[str, Any]:
    """An OTLP/HTTP JSON ``ExportLogsServiceRequest`` with one log record per event."""
    observed = str(int(observed_at.astimezone(UTC).timestamp() * 1_000_000_000))
    records: list[dict[str, Any]] = []
    for event in events:
        denied = event.decision == "denied"
        attributes = [
            item
            for item in (
                _attribute("event.name", event.action),
                _attribute("audit.event_id", event.id),
                _attribute("audit.decision", event.decision),
                _attribute("enduser.id", event.actor.id),
                _attribute("audit.actor_kind", event.actor.kind),
                _attribute("audit.actor_display", event.actor.display),
                _attribute("audit.instance_id", event.instance_id),
                _attribute("audit.scope_checked", event.scope_checked),
                _attribute("audit.resource_id", event.resource_id),
                _attribute("audit.source", event.source),
                _attribute("client.address", event.ip),
                _attribute("http.response.status_code", event.response_status),
            )
            if item is not None
        ]
        timestamp = int(event.occurred_at.astimezone(UTC).timestamp() * 1_000_000) * 1000
        records.append(
            {
                "timeUnixNano": str(timestamp),
                "observedTimeUnixNano": observed,
                "severityNumber": 13 if denied else 9,
                "severityText": "WARN" if denied else "INFO",
                "body": {"stringValue": as_text(format_event(event, sink_format, product_version=product_version))},
                "attributes": attributes,
            }
        )
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "agnostic-control-plane"}},
                        {"key": "service.version", "value": {"stringValue": product_version}},
                    ]
                },
                "scopeLogs": [{"scope": {"name": "agnostic.audit", "version": product_version}, "logRecords": records}],
            }
        ]
    }


class SinkConfigError(ValueError):
    pass


def _headers(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SinkConfigError("headers must be an object of header names to values")
    return {str(name): str(item) for name, item in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def validate_config(kind: SinkKind, config: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a sink's config; raises :class:`SinkConfigError` with a message for the form."""
    if kind == "https_webhook":
        url = str(config.get("url") or "")
        if not url.startswith("https://"):
            raise SinkConfigError("The webhook URL must start with https://")
        secret = config.get("secret")
        return {"url": url, "secret": str(secret) if secret else None, "headers": _headers(config.get("headers"))}
    if kind == "syslog":
        host = str(config.get("host") or "").strip()
        if not host:
            raise SinkConfigError("Set the syslog host")
        tls = bool(config.get("tls", True))
        try:
            port = int(config.get("port") or (6514 if tls else 514))
        except (TypeError, ValueError) as exc:
            raise SinkConfigError("The port must be a number") from exc
        if not 0 < port < 65536:  # noqa: PLR2004
            raise SinkConfigError("The port must be between 1 and 65535")
        ca_pem = config.get("ca_pem")
        return {
            "host": host,
            "port": port,
            "tls": tls,
            "tls_verify": bool(config.get("tls_verify", True)),
            "ca_pem": str(ca_pem) if ca_pem else None,
            "hostname": str(config.get("hostname") or "agnostic"),
        }
    endpoint = str(config.get("endpoint") or "").rstrip("/")
    if not endpoint.startswith(("https://", "http://")):
        raise SinkConfigError("The OTLP endpoint must be an http(s) URL, like https://otel.example.com:4318")
    return {"endpoint": endpoint, "headers": _headers(config.get("headers"))}


def merge_config(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a config update from the form: secrets that aren't sent again are kept."""
    merged = {**current, **changes}
    for key in SECRET_KEYS:
        if key not in changes and key in current:
            merged[key] = current[key]
    return merged


def synthetic_event(at: datetime, actor_id: str, actor_display: str) -> AuditEvent:
    """What "Send test event" delivers: a recognisable event that isn't stored in the log."""
    return AuditEvent(
        id="evt_TEST",
        occurred_at=at,
        request_id=None,
        actor=Actor(kind="user", id=actor_id, display=actor_display),
        via="web",
        ip=None,
        client=None,
        action="audit.sinks.test",
        resource_kind="audit_sink",
        resource_id=None,
        resource_display=None,
        instance_id=None,
        decision="n_a",
        scope_checked=None,
        missing_scopes=(),
        response_status=None,
        summary=f"{actor_display} sent a test event from Agnostic.",
        diff=None,
        links=None,
        source="control_plane",
    )
