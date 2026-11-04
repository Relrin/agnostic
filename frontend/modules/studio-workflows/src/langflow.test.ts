// Langflow flow JSON: the ticket router exports with Langflow's node, group, note and handle shapes and imports
// back as exactly the same workflow; a flow made in Langflow imports as Steps in the order it runs, with warnings
// for what doesn't carry over.
import { ticketRouter } from "@agnostic/testing";
import { describe, expect, it } from "vitest";

import { decodeHandle, encodeHandle, fromLangflow, nodeId, toLangflow, type LangflowFlow } from "./langflow";
import type { Note } from "./notes";

const NOTE: Note = { id: "note:abc", x: 300, y: 480, width: 240, text: "Keep route names in sync." };

async function exported(): Promise<LangflowFlow> {
  return toLangflow({
    config: ticketRouter(),
    id: "ticket-router",
    name: "ticket-router",
    inputLabel: "input",
    offsets: { "steps[0]": { x: 10, y: -20 } },
    notes: [NOTE],
    viewport: { x: 12, y: 34, zoom: 0.8 },
  });
}

describe("Langflow export", () => {
  it("writes the flow with Langflow's shapes", async () => {
    const flow = await exported();
    expect(flow).toMatchObject({ id: "ticket-router", name: "ticket-router", is_component: false });
    expect(flow.data.viewport).toEqual({ x: 12, y: 34, zoom: 0.8 });
    const types = flow.data.nodes.map((node) => node.data.type);
    expect(types).toEqual([
      "ChatInput",
      "AgnoStep",
      "AgnoRouter",
      "AgnoStep",
      "AgnoParallel",
      "AgnoLoop",
      "AgnoCondition",
      "AgnoStep",
      "AgnoStep",
      "ChatOutput",
      "note",
    ]);
    const router = flow.data.nodes.find((node) => node.data.type === "AgnoRouter");
    expect(router?.type).toBe("genericNode");
    expect(router?.id).toMatch(/^AgnoRouter-[A-Za-z]{5}$/);
    expect(router?.data.node.display_name).toBe("Route by category");
    expect(router?.data.node.outputs).toMatchObject([
      { name: "choice_0", display_name: "Billing", types: ["Message"] },
      { name: "choice_1", display_name: "Investigate" },
      { name: "choice_2", display_name: "Draft & review" },
    ]);
    expect(router?.data.node.template).toMatchObject({
      selector: { type: "str", name: "selector", show: true },
      input_value: { input_types: ["Message"] },
    });
    // A group holds its steps in `node.flow`, positioned inside it.
    const parallel = flow.data.nodes.find((node) => node.data.type === "AgnoParallel");
    const inner = (
      parallel?.data.node.flow as { data: { nodes: { data: { node: { display_name: string } } }[] } }
    ).data.nodes;
    expect(inner.map((node) => node.data.node.display_name)).toEqual(["Search KB", "Check status page"]);
    const note = flow.data.nodes.find((node) => node.type === "noteNode");
    expect(note?.data.node.description).toBe(NOTE.text);
  });

  it("encodes handles the way Langflow does", async () => {
    const flow = await exported();
    const first = flow.data.edges[0];
    expect(first?.sourceHandle).toMatch(/^\{œdataTypeœ:œChatInputœ,œidœ:œChatInput-\w{5}œ,œnameœ:œmessageœ,/);
    expect(first?.id).toBe(
      `reactflow__edge-${first?.source ?? ""}${first?.sourceHandle ?? ""}-${first?.target ?? ""}${first?.targetHandle ?? ""}`,
    );
    expect(decodeHandle(first?.targetHandle ?? "")).toEqual({
      fieldName: "input_value",
      id: first?.target,
      inputTypes: ["Message"],
      type: "str",
    });
    expect(decodeHandle(encodeHandle({ a: 'say "hi"' }))).toEqual({ a: 'say "hi"' });
    const condition = flow.data.edges.filter((edge) => edge.source.startsWith("AgnoCondition-"));
    expect(condition.map((edge) => edge.data?.sourceHandle.name)).toEqual(["true_result", "false_result"]);
    expect(nodeId("AgnoStep", "steps[0]")).toBe(nodeId("AgnoStep", "steps[0]"));
    expect(nodeId("AgnoStep", "steps[0]")).not.toBe(nodeId("AgnoStep", "steps[1]"));
  });
});

describe("Langflow import", () => {
  it("reads an exported flow back as the same workflow, with its notes", async () => {
    const flow = JSON.parse(JSON.stringify(await exported())) as unknown;
    const result = fromLangflow(flow);
    expect(result.source).toBe("agnostic");
    expect(result.warnings).toEqual([]);
    expect(result.steps).toEqual((ticketRouter() as { steps: unknown[] }).steps);
    expect(result.notes).toEqual([NOTE]);
  });

  it("imports a flow made in Langflow as steps in the order it runs", () => {
    const handle = (source: string, type: string, name: string, outputTypes: string[]) =>
      encodeHandle({ dataType: type, id: source, name, output_types: outputTypes });
    const target = (id: string, field: string, inputTypes: string[]) =>
      encodeHandle({ fieldName: field, id, inputTypes, type: "str" });
    const node = (id: string, type: string, display: string, x: number) => ({
      id,
      type: "genericNode",
      position: { x, y: 0 },
      data: { id, type, node: { display_name: display, template: {}, outputs: [] } },
    });
    const edge = (source: string, sourceHandle: string, targetId: string, targetHandle: string) => ({
      id: `reactflow__edge-${source}-${targetId}`,
      source,
      sourceHandle,
      target: targetId,
      targetHandle,
    });
    const flow = {
      name: "Support agent",
      data: {
        nodes: [
          node("ChatInput-aaaaa", "ChatInput", "Chat Input", 0),
          node("Prompt-bbbbb", "Prompt", "Prompt", 300),
          node("Agent-ccccc", "Agent", "Agent", 600),
          node("Calculator-ddddd", "CalculatorComponent", "Calculator", 300),
          node("ChatOutput-eeeee", "ChatOutput", "Chat Output", 900),
          {
            id: "undefined-fffff",
            type: "noteNode",
            position: { x: 50, y: 400 },
            data: { id: "undefined-fffff", type: "note", node: { description: "Read me first" } },
          },
        ],
        edges: [
          edge(
            "ChatInput-aaaaa",
            handle("ChatInput-aaaaa", "ChatInput", "message", ["Message"]),
            "Prompt-bbbbb",
            target("Prompt-bbbbb", "question", ["Message"]),
          ),
          edge(
            "Prompt-bbbbb",
            handle("Prompt-bbbbb", "Prompt", "prompt", ["Message"]),
            "Agent-ccccc",
            target("Agent-ccccc", "input_value", ["Message"]),
          ),
          edge(
            "Calculator-ddddd",
            handle("Calculator-ddddd", "CalculatorComponent", "component_as_tool", ["Tool"]),
            "Agent-ccccc",
            target("Agent-ccccc", "tools", ["Tool"]),
          ),
          edge(
            "Agent-ccccc",
            handle("Agent-ccccc", "Agent", "response", ["Message"]),
            "ChatOutput-eeeee",
            target("ChatOutput-eeeee", "input_value", ["Data", "DataFrame", "Message"]),
          ),
        ],
        viewport: { x: 0, y: 0, zoom: 1 },
      },
    };
    const result = fromLangflow(flow);
    expect(result.source).toBe("langflow");
    expect(result.steps).toEqual([
      { type: "Step", name: "Prompt" },
      { type: "Step", name: "Agent" },
    ]);
    expect(result.notes).toMatchObject([{ x: 50, y: 400, text: "Read me first" }]);
    expect(result.warnings).toEqual([
      "Calculator is wired into Agent as a Tool: give the step's agent that tool or model in the agent editor.",
      "2 steps have no executor yet: pick an agent, team or function for each in the inspector.",
    ]);
  });

  it("refuses a file that isn't a flow", () => {
    expect(() => fromLangflow({ hello: "world" })).toThrow(/isn't a Langflow flow/);
  });
});
