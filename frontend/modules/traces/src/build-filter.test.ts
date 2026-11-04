import type { AgentOS } from "@agnostic/api";
import { describe, expect, it } from "vitest";

import { buildTraceFilter } from "./build-filter";
import { flattenTrace, modelRollup, parseDuration } from "./spans";

const NOW = new Date("2026-11-01T10:00:00Z");

describe("buildTraceFilter", () => {
  it("combines chips, the time range and free text", () => {
    expect(
      buildTraceFilter(
        {
          status: "ERROR",
          component: "workflow:daily-brief",
          user: "sa:scheduler",
          q: "brief",
          range: "24h",
        },
        undefined,
        NOW,
      ),
    ).toEqual({
      op: "AND",
      conditions: [
        { op: "EQ", key: "status", value: "ERROR" },
        { op: "EQ", key: "workflow_id", value: "daily-brief" },
        { op: "EQ", key: "user_id", value: "sa:scheduler" },
        { op: "GTE", key: "start_time", value: "2026-10-31T10:00:00.000Z" },
        {
          op: "OR",
          conditions: ["name", "trace_id", "run_id", "session_id", "user_id"].map((key) => ({
            op: "CONTAINS",
            key,
            value: "brief",
          })),
        },
      ],
    });
  });

  it("keeps the same start for every render within a minute", () => {
    const at = (iso: string) => buildTraceFilter({ range: "24h" }, undefined, new Date(iso));
    expect(at("2026-11-01T10:00:01.250Z")).toEqual(at("2026-11-01T10:00:59.999Z"));
    expect(at("2026-11-01T10:00:59.999Z")).toEqual({
      op: "GTE",
      key: "start_time",
      value: "2026-10-31T10:00:00.000Z",
    });
  });

  it("only uses what the filter schema offers", () => {
    const schema: AgentOS.FilterSchemaResponse = {
      fields: [{ key: "name", label: "Name", type: "string", operators: ["contains"] }],
      logical_operators: ["AND", "OR"],
    };
    expect(buildTraceFilter({ status: "OK", q: "triage", range: "7d" }, schema, NOW)).toEqual({
      op: "CONTAINS",
      key: "name",
      value: "triage",
    });
    expect(buildTraceFilter({ range: "7d" }, schema, NOW)).toBeUndefined();
  });
});

describe("flattenTrace", () => {
  it("orders spans depth first with offsets, kinds and exception attributes", () => {
    const at = (seconds: number) =>
      new Date(Date.parse("2026-11-01T03:00:00Z") + seconds * 1000).toISOString();
    const node = (
      id: string,
      type: string,
      start: number,
      seconds: number,
      extra: Partial<AgentOS.TraceNode> = {},
    ): AgentOS.TraceNode => ({
      id,
      name: id,
      type,
      duration: `${String(seconds)}s`,
      start_time: at(start),
      end_time: at(start + seconds),
      status: "OK",
      ...extra,
    });
    const detail = {
      trace_id: "tr_1",
      start_time: at(0),
      tree: [
        node("daily-brief.run", "WORKFLOW", 0, 64, {
          spans: [
            node("Gather news", "WORKFLOW", 0.1, 63.8, {
              step_type: "Step",
              spans: [
                node("web_search", "TOOL", 1.7, 30, { status: "ERROR", error: "TimeoutError: too slow" }),
                node("chat.completion", "LLM", 0.2, 1.4, {
                  metadata: { model: "claude-haiku-5-5", input_tokens: 100, output_tokens: 10 },
                }),
              ],
            }),
          ],
        }),
      ],
    } as unknown as AgentOS.TraceDetail;
    const spans = flattenTrace(detail);
    expect(spans.map((span) => [span.name, span.kind, span.depth])).toEqual([
      ["daily-brief.run", "workflow", 0],
      ["Gather news", "step", 1],
      ["chat.completion", "model", 2],
      ["web_search", "tool", 2],
    ]);
    const search = spans[3];
    expect(search?.startMs).toBe(1700);
    expect(search?.failed).toBe(true);
    expect(search?.attributes["exception.type"]).toBe("TimeoutError");
    expect(modelRollup(spans)).toEqual([
      { model: "claude-haiku-5-5", calls: 1, prompt: 100, completion: 10 },
    ]);
    expect(parseDuration("1.50s")).toBe(1500);
    expect(parseDuration("350ms")).toBe(350);
  });
});
