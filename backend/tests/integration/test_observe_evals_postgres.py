"""Observe and evals on PostgreSQL + Redis: JSONB comparison cache and price tables, eval batches on the Procrastinate
queue (a real worker, the per-instance lock) with their comparison and gate."""

import pytest

from tests.api.test_instances_gateway import connect
from tests.api.test_observe_evals import BASE, create_dataset, daily_brief_pair, respond, wait_for
from tests.support.stack import running_stack

pytestmark = pytest.mark.integration


async def test_observe_and_evals_on_postgres(
    fresh_postgres: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(fresh_postgres, redis_url=redis_url, jobs={"mode": "embedded"}) as stack:
        owner = await stack.owner()
        fake = stack.runtime("prod.agentos.test")
        _ = await connect(owner, fake)

        today, _ = daily_brief_pair(fake)
        first = (await owner.get(f"{BASE}/traces/{today['trace_id']}/comparison")).json()
        cached = (await owner.get(f"{BASE}/traces/{today['trace_id']}/comparison")).json()
        assert (first["cached"], cached["cached"]) == (False, True)
        assert cached["rows"] == first["rows"]

        prices = {"prices": [{"model_id": "claude-opus-5-5", "input_per_1m": 5, "output_per_1m": 25}]}
        assert (await owner.put(f"{BASE}/price-table", json=prices)).status_code == 200
        assert (await owner.put("/api/v1/price-table", json=prices)).status_code == 200
        sources = {row["source"] for row in (await owner.get(f"{BASE}/price-table")).json()["prices"]}
        assert sources == {"instance"}

        fake.eval_responder = respond
        dataset = await create_dataset(owner)
        body = {"dataset_id": dataset["id"], "component_kind": "agent", "component_id": "support-triage"}
        one = (await owner.post(f"{BASE}/eval-batches", json=body)).json()
        two = (await owner.post(f"{BASE}/eval-batches", json=body)).json()
        done = [await wait_for(owner, one["id"]), await wait_for(owner, two["id"])]
        assert [detail["batch"]["status"] for detail in done] == ["completed", "completed"]
        assert len(fake.eval_requests) == 10
        compared = (await owner.get(f"{BASE}/eval-batches/{two['id']}/compare", params={"with": one["id"]})).json()
        assert compared["counts"]["regressions"] == 0
