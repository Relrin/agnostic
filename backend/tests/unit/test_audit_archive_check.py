"""Verifying an archived month against its manifest: digests, counts, month bounds and the hash chain."""

import hashlib
import json
from compression import zstd
from dataclasses import replace
from datetime import UTC, datetime

from agnostic_audit.domain.archive import Manifest, check_archive
from agnostic_audit.domain.events import AuditEvent, event_document
from tests.unit.test_audit_domain_governance import chained, event

MONTH = "2026-10"


def archive(events: list[AuditEvent], **manifest_changes: object) -> tuple[bytes, Manifest]:
    lines = b"".join(
        (json.dumps(event_document(item), sort_keys=True, separators=(",", ":")) + "\n").encode() for item in events
    )
    data = zstd.compress(lines)
    head = next((item.hash for item in reversed(events) if item.hash), None)
    manifest = Manifest(
        month=MONTH,
        event_count=len(events),
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        chain_head=head,
        created_at=datetime(2027, 11, 1, tzinfo=UTC),
    )
    return data, replace(manifest, **manifest_changes)  # pyright: ignore[reportArgumentType]


def test_intact_archive() -> None:
    events = chained([event(n) for n in range(5)])
    data, manifest = archive(events)
    check = check_archive(MONTH, data, manifest, recorded_sha256=manifest.sha256, size=len(data))
    assert check.ok, check.problems
    assert (check.event_count, check.chained) == (5, 5)


def test_unchained_archive_is_intact_without_a_chain_head() -> None:
    data, manifest = archive([event(n) for n in range(3)])
    check = check_archive(MONTH, data, manifest, recorded_sha256=None)
    assert check.ok
    assert check.chained == 0


def test_tampered_object_and_manifest() -> None:
    events = chained([event(n) for n in range(4)])
    data, manifest = archive(events)
    check = check_archive(MONTH, data + b"x", manifest, recorded_sha256=manifest.sha256, size=len(data))
    assert not check.ok
    assert any("differs from the manifest" in problem for problem in check.problems)
    assert any("recorded when it was archived" in problem for problem in check.problems)
    assert any("can't be read" in problem for problem in check.problems)

    wrong_count = check_archive(MONTH, data, replace(manifest, event_count=9), recorded_sha256=None)
    assert "4 events, the manifest says 9" in wrong_count.problems


def test_edited_event_breaks_the_chain() -> None:
    events = chained([event(n) for n in range(4)])
    events[2] = replace(events[2], summary="someone rewrote history")
    data, manifest = archive(events, chain_head=chained([event(n) for n in range(4)])[-1].hash)
    check = check_archive(MONTH, data, manifest, recorded_sha256=None)
    assert check.problems == (f"the hash chain breaks at event {events[2].id}",)


def test_removed_tail_no_longer_reaches_the_chain_head() -> None:
    events = chained([event(n) for n in range(4)])
    data, manifest = archive(events[:3], chain_head=events[3].hash)
    check = check_archive(MONTH, data, manifest, recorded_sha256=None)
    assert check.problems == ("the last chained event doesn't match the manifest's chain head",)


def test_events_outside_the_month() -> None:
    data, manifest = archive([event(0), event(1, occurred_at=datetime(2026, 11, 2, tzinfo=UTC))])
    check = check_archive(MONTH, data, manifest, recorded_sha256=None)
    assert check.problems == ("1 event(s) fall outside 2026-10",)
