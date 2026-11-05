"""Query plans of the hot list queries at realistic volumes: no sequential scan over a large table.

The tables are filled with COPY (hundreds of thousands of audit events over six monthly partitions, thousands of
people, a busy inbox, approval trails), ANALYZEd, and then the real endpoints and repositories run while every SQL
statement they send is recorded. Each recorded SELECT is EXPLAINed (ANALYZE, BUFFERS) with its own parameters.

A table is large when PostgreSQL estimates 10,000 rows or more. A sequential scan of one fails the test unless it is
bounded: it has no filter and a LIMIT sits above it with nothing blocking in between (the capped count reads at most
the cap). Set ``AGNOSTIC_QUERY_PLANS_REPORT`` to a file path to keep every plan for review.

The palette search is judged by whether an index plan exists at all (EXPLAINed again with ``enable_seqscan = off``):
over a few tens of thousands of documents a full read and the three-way bitmap OR cost about the same, and the
planner rightly picks either. What must not happen is a query no index can serve, which then grows with the table.
"""

import asyncio
import json
import os
import random
import uuid
from collections.abc import AsyncGenerator, Callable, Generator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from agnostic_approvals.infrastructure.repository import SqlApprovalStore
from agnostic_audit.application.ports import PartitionMaintenance
from agnostic_audit.domain.archive import month_key
from agnostic_notifications.infrastructure.repository import SqlDeliveryRepository
from agnostic_scheduler.infrastructure.repository import SqlNoteStore
from tests.support.stack import Stack, running_stack

pytestmark = pytest.mark.integration

NEVER = "0 0 1 1 *"
LARGE_ROWS = 10_000
BLOCKING = frozenset({"Sort", "Incremental Sort", "Aggregate", "Hash", "Hash Join", "Materialize", "WindowAgg"})

AUDIT_EVENTS = 360_000
AUDIT_MONTHS = 6
PEOPLE = 5_000
COMPONENT_DOCUMENTS = 15_000
INSTANCES = 50
INBOX_ITEMS = 150_000
OWNER_INBOX = 3_000
DELIVERIES = 60_000
APPROVAL_EVENTS = 120_000
APPROVAL_VIEWS = 60_000
SCHEDULE_NOTES = 20_000

ACTIONS = (
    "agentos.access",
    "gateway.call",
    "gateway.denied",
    "instance.connected",
    "instance.updated",
    "access.binding_created",
    "approval.resolved",
    "auth.login",
    "studio.published",
    "audit.export",
)
DECISIONS = ("allowed", "allowed", "allowed", "denied", "n_a")
FIRST_NAMES = ("Maya", "Marcus", "Daniel", "Priya", "Lena", "Tomás", "Aiko", "Noah", "Zara", "Ibrahim", "Mara")
SYLLABLES = ("ka", "lo", "mi", "ren", "to", "sa", "vik", "dor", "bel", "ni", "ras", "quin", "fe", "lu", "gor", "zan")


def person_name(n: int) -> str:
    """Thousands of distinct surnames, so a typed fragment matches a handful of people, as in a real org."""
    surname = "".join(SYLLABLES[(n >> shift) % len(SYLLABLES)] for shift in (0, 4, 8)).capitalize()
    return f"{FIRST_NAMES[n % len(FIRST_NAMES)]} {surname}"


@dataclass
class Recorded:
    case: str
    statement: str
    parameters: Sequence[Any]


@dataclass
class Recorder:
    """Every statement the app's engine sends while a case is open."""

    statements: list[Recorded] = field(default_factory=list[Recorded])
    current: str | None = None

    def listen(self, engine: AsyncEngine) -> Callable[[], None]:
        def before(_conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, many: bool) -> None:
            if self.current is not None and not many:
                self.statements.append(Recorded(self.current, statement, tuple(parameters or ())))

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        return lambda: event.remove(engine.sync_engine, "before_cursor_execute", before)

    @contextmanager
    def case(self, name: str) -> Generator[None]:
        self.current = name
        try:
            yield
        finally:
            self.current = None

    def selects(self) -> list[Recorded]:
        seen: set[tuple[str, str]] = set()
        found: list[Recorded] = []
        for item in self.statements:
            head = item.statement.lstrip().split(None, 1)[0].upper()
            if head not in {"SELECT", "WITH"} or (item.case, item.statement) in seen:
                continue
            seen.add((item.case, item.statement))
            found.append(item)
        return found


@dataclass(frozen=True)
class Scan:
    relation: str
    node: str
    filtered: bool
    bounded: bool
    rows: float


def scans(plan: dict[str, Any], *, limited: bool = False) -> Iterator[Scan]:
    node = str(plan["Node Type"])
    limited = (limited or node == "Limit") and node not in BLOCKING
    if "Relation Name" in plan:
        yield Scan(
            relation=str(plan["Relation Name"]),
            node=node,
            filtered="Filter" in plan,
            bounded=limited,
            rows=float(plan.get("Actual Rows", plan.get("Plan Rows", 0))),
        )
    for child in plan.get("Plans", ()):
        yield from scans(child, limited=limited)


def admin_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


async def seed(dsn: str, owner_id: str) -> dict[str, list[str]]:
    rng = random.Random(20261104)
    now = datetime.now(UTC)
    instance_ids = [f"ins_{n:04d}" for n in range(INSTANCES)]
    people = [f"usr_perf{n:05d}" for n in range(PEOPLE)]
    connection = await asyncpg.connect(dsn)
    try:
        _ = await connection.copy_records_to_table(
            "identity_users",
            schema_name="agnostic",
            columns=["id", "email", "display_name", "avatar_seed", "status", "created_via", "last_active_at"],
            records=(
                (
                    user_id,
                    f"person{n:05d}@perf.test",
                    person_name(n),
                    user_id,
                    "active",
                    "invite",
                    now - timedelta(minutes=n),
                )
                for n, user_id in enumerate(people)
            ),
        )
        _ = await connection.copy_records_to_table(
            "org_members",
            schema_name="agnostic",
            columns=["user_id", "org_role", "status", "joined_via"],
            records=((user_id, "member", "active", "invitation") for user_id in people),
        )
        _ = await connection.copy_records_to_table(
            "search_documents",
            schema_name="agnostic",
            columns=["id", "provider", "kind", "ref", "instance_id", "title", "body", "url_path", "required_scope"],
            records=[
                *(
                    (
                        f"org:member:-:{user_id}",
                        "org",
                        "member",
                        user_id,
                        None,
                        person_name(n),
                        f"person{n:05d}@perf.test member",
                        f"/access/people?member={user_id}",
                        "org:members:read",
                    )
                    for n, user_id in enumerate(people)
                ),
                *(
                    (
                        f"instances:agent:{instance_ids[n % INSTANCES]}:agent-{n}",
                        "instances",
                        "agent",
                        f"agent-{n}",
                        instance_ids[n % INSTANCES],
                        f"Agent {n} {SYLLABLES[n % len(SYLLABLES)]} helper",
                        "support triage billing",
                        f"/agents/agent-{n}",
                        None,
                    )
                    for n in range(COMPONENT_DOCUMENTS)
                ),
            ],
        )

        def audit_rows() -> Iterator[tuple[Any, ...]]:
            span = timedelta(days=30 * AUDIT_MONTHS).total_seconds()
            for n in range(AUDIT_EVENTS):
                at = now - timedelta(seconds=span * (AUDIT_EVENTS - n) / AUDIT_EVENTS)
                actor = people[rng.randrange(200)] if n % 10 else "system"
                instance = instance_ids[rng.randrange(INSTANCES)] if n % 4 else None
                action = ACTIONS[rng.randrange(len(ACTIONS))]
                yield (
                    f"aud_{n:012d}",
                    at,
                    f"req_{n:012d}",
                    "user" if actor != "system" else "system",
                    actor,
                    f"Person {actor}",
                    "gateway" if action.startswith(("gateway", "agentos")) else "web",
                    f"10.0.{n % 250}.{n % 200}",
                    action,
                    "session",
                    f"ses_{n % 40_000:06d}",
                    f"Session {n % 40_000}",
                    instance,
                    DECISIONS[n % len(DECISIONS)],
                    "agentos" if action == "agentos.access" else "control_plane",
                    f"{action} by {actor}",
                )

        _ = await connection.copy_records_to_table(
            "audit_events",
            schema_name="agnostic",
            columns=[
                "id",
                "occurred_at",
                "request_id",
                "actor_kind",
                "actor_id",
                "actor_display",
                "via",
                "ip",
                "action",
                "resource_kind",
                "resource_id",
                "resource_display",
                "instance_id",
                "decision",
                "source",
                "summary",
            ],
            records=audit_rows(),
        )

        inbox_users = [owner_id] * OWNER_INBOX + [people[n % PEOPLE] for n in range(INBOX_ITEMS - OWNER_INBOX)]
        _ = await connection.copy_records_to_table(
            "ntf_inbox",
            schema_name="agnostic",
            columns=["id", "user_id", "kind", "title", "body", "instance_id", "payload", "created_at", "read_at"],
            records=(
                (
                    f"ntf_{n:010d}",
                    user_id,
                    "approval.requested",
                    f"Approval {n} waits for you",
                    "",
                    instance_ids[n % INSTANCES],
                    "{}",
                    now - timedelta(minutes=INBOX_ITEMS - n),
                    None if n % 3 else now,
                )
                for n, user_id in enumerate(inbox_users)
            ),
        )
        channels = [f"chn_{n:03d}" for n in range(20)]
        _ = await connection.copy_records_to_table(
            "ntf_deliveries",
            schema_name="agnostic",
            columns=[
                "id",
                "event_type",
                "channel",
                "channel_id",
                "user_id",
                "target",
                "message",
                "status",
                "created_at",
            ],
            records=(
                (
                    f"dlv_{n:010d}",
                    "approval.requested",
                    "slack",
                    channels[n % len(channels)],
                    None,
                    "#approvals",
                    "{}",
                    "sent",
                    now - timedelta(seconds=DELIVERIES - n),
                )
                for n in range(DELIVERIES)
            ),
        )
        approval_ids = [f"apr_{n:07d}" for n in range(APPROVAL_EVENTS // 3)]
        _ = await connection.copy_records_to_table(
            "apr_events",
            schema_name="agnostic",
            columns=["id", "instance_id", "approval_id", "kind", "detail", "actor", "at"],
            records=(
                (
                    f"aev_{n:010d}",
                    instance_ids[(n // 3) % INSTANCES],
                    approval_ids[n // 3],
                    ("routed", "notified", "resolved")[n % 3],
                    "{}",
                    None,
                    now - timedelta(seconds=APPROVAL_EVENTS - n),
                )
                for n in range(APPROVAL_EVENTS)
            ),
        )
        _ = await connection.copy_records_to_table(
            "apr_views",
            schema_name="agnostic",
            columns=["instance_id", "approval_id", "user_id", "viewed_at"],
            records=(
                (
                    instance_ids[(n % len(approval_ids)) % INSTANCES],
                    approval_ids[n % len(approval_ids)],
                    people[n // len(approval_ids)],
                    now,
                )
                for n in range(APPROVAL_VIEWS)
            ),
        )
        _ = await connection.copy_records_to_table(
            "sch_notes",
            schema_name="agnostic",
            columns=["instance_id", "schedule_id", "reason", "disabled_by", "disabled_by_name"],
            records=(
                (instance_ids[n % INSTANCES], f"sch_{n:06d}", "Paused for the migration", owner_id, "Daniel Okafor")
                for n in range(SCHEDULE_NOTES)
            ),
        )
        _ = await connection.execute("ANALYZE")
    finally:
        await connection.close()
    return {"instances": instance_ids, "people": people, "approvals": approval_ids, "channels": channels}


SEARCH_EMPTINESS = "SELECT agnostic.search_documents.id FROM agnostic.search_documents LIMIT"
# A surname fragment, an email and an exact id. Two or three letters match a large share of the index, where
# reading the whole table is the cheaper plan; these must not.
SEARCH_TERMS = (person_name(1234).split()[1][:6].lower(), "person01234@perf.test", "usr_perf04321")


def relabel(case: str, statement: str) -> str:
    """The palette's emptiness check runs inside every search request; it gets its own verdict."""
    if " ".join(statement.split()).startswith(SEARCH_EMPTINESS):
        return "search: emptiness check on every request"
    return case


def audit_cases(person: str, instance: str, week_ago: str) -> dict[str, dict[str, str]]:
    return {
        "audit: newest": {},
        "audit: by actor": {"actor": person},
        "audit: by actor kind": {"actor_kind": "system"},
        "audit: by action": {"action": "instance.updated"},
        "audit: by action prefix": {"action": "gateway.*"},
        "audit: by instance": {"instance": instance},
        "audit: by resource": {"resource": "ses_001234"},
        "audit: by decision": {"decision": "denied"},
        "audit: by source": {"source": "agentos"},
        "audit: last week": {"since": week_ago},
        "audit: text search": {"q": "ses_00123"},
        "audit: instance and action, last week": {"instance": instance, "action": "gateway.*", "since": week_ago},
    }


@dataclass
class Verdicts:
    covered: set[str]
    problems: dict[str, list[str]]


async def explain(
    dsn: str, recorded: Sequence[Recorded], *, indexable_only: Callable[[Recorded], bool]
) -> list[tuple[Recorded, dict[str, Any]]]:
    connection = await asyncpg.connect(dsn)
    try:
        plans: list[tuple[Recorded, dict[str, Any]]] = []
        for item in recorded:
            async with connection.transaction():
                if indexable_only(item):
                    await connection.execute("SET LOCAL enable_seqscan = off")
                raw = await connection.fetchval(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + item.statement, *item.parameters
                )
            document = json.loads(raw) if isinstance(raw, str) else raw
            plans.append((item, document[0]))
        return plans
    finally:
        await connection.close()


def palette_search(item: Recorded) -> bool:
    return relabel(item.case, item.statement).startswith("people search: ")


async def large_tables(dsn: str) -> set[str]:
    connection = await asyncpg.connect(dsn)
    try:
        rows = await connection.fetch(
            "SELECT relname FROM pg_class WHERE relnamespace = 'agnostic'::regnamespace "
            "AND relkind IN ('r', 'p') AND reltuples >= $1",
            LARGE_ROWS,
        )
    finally:
        await connection.close()
    return {str(row["relname"]) for row in rows}


async def pages(client: httpx.AsyncClient, path: str, params: dict[str, str], count: int) -> None:
    cursor: str | None = None
    for _ in range(count):
        response = await client.get(path, params={**params, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        cursor = response.json().get("next_cursor")
        if cursor is None:
            return


@asynccontextmanager
async def scratch_database(postgres_url: str) -> AsyncGenerator[str]:
    """Like ``fresh_postgres``, for one module: the seeded volumes are shared by every case."""
    name = f"agnostic_plans_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_dsn(postgres_url))
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    try:
        yield make_url(postgres_url).set(database=name).render_as_string(hide_password=False)
    finally:
        admin = await asyncpg.connect(admin_dsn(postgres_url))
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


async def record_hot_queries(stack: Stack, dsn: str, recorder: Recorder) -> None:
    owner = await stack.owner()
    connection = await asyncpg.connect(dsn)
    try:
        owner_id = str(await connection.fetchval("SELECT id FROM agnostic.identity_users ORDER BY created_at LIMIT 1"))
    finally:
        await connection.close()

    now = datetime.now(UTC)
    async with stack.container() as request:
        maintenance = await request.get(PartitionMaintenance)
        for back in range(AUDIT_MONTHS + 1):
            await maintenance.ensure_month(month_key(now - timedelta(days=30 * back)))
    seeded = await seed(dsn, owner_id)
    instance = seeded["instances"][7]
    week_ago = (now - timedelta(days=7)).isoformat()

    stop = recorder.listen(await stack.container.get(AsyncEngine))
    try:
        for name, params in audit_cases(seeded["people"][42], instance, week_ago).items():
            with recorder.case(name):
                await pages(owner, "/api/v1/audit/events", {"limit": "50", **params}, 3)
        with recorder.case("audit: actors"):
            assert (await owner.get("/api/v1/audit/actors")).status_code == 200

        with recorder.case("notifications: inbox"):
            await pages(owner, "/api/v1/notifications", {"limit": "30"}, 3)
        with recorder.case("notifications: unread"):
            await pages(owner, "/api/v1/notifications", {"limit": "30", "unread": "true"}, 3)
        with recorder.case("notifications: unread count"):
            assert (await owner.get("/api/v1/notifications/unread-count")).status_code == 200

        for term in SEARCH_TERMS:
            with recorder.case(f"people search: {term}"):
                found = await owner.get("/api/v1/search", params={"q": term})
                assert found.status_code == 200, found.text

        async with stack.container() as scope:
            session = await scope.get(AsyncSession)
            approvals = SqlApprovalStore(session)
            approvals_instance = seeded["instances"][700 % INSTANCES]
            page = seeded["approvals"][700:750]
            with recorder.case("approvals: event kinds of a page"):
                _ = await approvals.event_kinds(approvals_instance, page)
            with recorder.case("approvals: trail and views of one"):
                _ = await approvals.events(approvals_instance, page[0])
                _ = await approvals.views(approvals_instance, page[0])
            with recorder.case("scheduler: notes of a page"):
                _ = await SqlNoteStore(session).notes(instance, [f"sch_{n:06d}" for n in range(7, 2007, 50)])
            with recorder.case("notifications: channel deliveries"):
                _ = await SqlDeliveryRepository(session).recent(channel_id=seeded["channels"][3], limit=20)
    finally:
        stop()


@pytest.fixture(scope="module")
async def verdicts(postgres_url: str, redis_url: str) -> Verdicts:
    recorder = Recorder()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
        patch.setenv("AGNOSTIC_AUDIT__DELIVER_ON_RECORD", "false")
        patch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
        async with (
            scratch_database(postgres_url) as database_url,
            running_stack(database_url, redis_url=redis_url, jobs={"mode": "embedded"}) as stack,
        ):
            dsn = admin_dsn(database_url)
            await record_hot_queries(stack, dsn, recorder)
            large = await large_tables(dsn)
            plans = await explain(dsn, recorder.selects(), indexable_only=palette_search)

    if report_path := os.environ.get("AGNOSTIC_QUERY_PLANS_REPORT"):
        report = [{"case": item.case, "statement": item.statement, "plan": plan} for item, plan in plans]
        text = json.dumps(report, indent=2, default=str)
        _ = await asyncio.to_thread(Path(report_path).write_text, text, encoding="utf-8")
    problems: dict[str, list[str]] = {}
    covered: set[str] = set()
    for item, plan in plans:
        case = relabel(item.case, item.statement)
        covered.add(case)
        for scan in scans(plan["Plan"]):
            if scan.node == "Seq Scan" and scan.relation in large and (scan.filtered or not scan.bounded):
                problems.setdefault(case, []).append(
                    f"{scan.node} on {scan.relation} ({scan.rows:.0f} rows, "
                    f"{'filtered' if scan.filtered else 'unfiltered'}, {plan['Plan']['Actual Total Time']} ms): "
                    + " ".join(item.statement.split())[:300]
                )
    return Verdicts(covered=covered, problems=problems)


def known_gap(case: str, finding: str) -> Any:
    reason = f"Known limitation: {finding}"
    return pytest.param(case, marks=pytest.mark.xfail(strict=True, reason=reason))


CASES = [
    *audit_cases("", "", ""),
    known_gap("audit: actors", "the actors summary aggregates 90 days of audit events on every call"),
    "notifications: inbox",
    "notifications: unread",
    "notifications: unread count",
    "notifications: channel deliveries",
    *(f"people search: {term}" for term in SEARCH_TERMS),
    "search: emptiness check on every request",
    "approvals: event kinds of a page",
    "approvals: trail and views of one",
    "scheduler: notes of a page",
]


@pytest.mark.parametrize("case", CASES)
async def test_no_sequential_scan_over_large_tables(verdicts: Verdicts, case: str) -> None:
    assert case in verdicts.covered, f"{case} sent no SELECT"
    assert not verdicts.problems.get(case), "\n".join(verdicts.problems[case])
