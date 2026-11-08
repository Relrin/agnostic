// The coding-agent section: fields from the schema's marker description, edits written into
// metadata.agnostic.coding_agent (the rest of the metadata kept), the published-version note, and nothing at all for
// an agent without the marker.
import { renderWithProviders, sampleCodingAgentSchema, studioHandlers } from "@agnostic/testing";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { useState } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { CodingAgentSection, withCodingSetting } from "./coding-agent-section";
import type { Config } from "./config";
import { codingFields } from "./document";
import { ConfigForm, type FormContext } from "./form";

const server = setupServer(...studioHandlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...studioHandlers());
});
afterAll(() => {
  server.close();
});

const registry = { byType: () => [], find: () => undefined };

function Harness({ initial, seen }: { initial: Config; seen: { config: Config } }) {
  const [config, setConfig] = useState(initial);
  const ctx: FormContext = {
    config,
    onChange: (update) => {
      setConfig((current) => {
        const next = update(current);
        seen.config = next;
        return next;
      });
    },
    spans: {},
    focusedPath: undefined,
    onFocusPath: () => undefined,
    registry,
  };
  return <CodingAgentSection ctx={ctx} />;
}

const coder: Config = {
  name: "Repo coder",
  metadata: { owner: "platform", agnostic: { coding_agent: { harness: "pi" } } },
};

describe("codingFields", () => {
  it("flattens the marker's settings, the sandbox's after the harness's", () => {
    const fields = codingFields(sampleCodingAgentSchema);
    expect(fields.map((field) => field.path.join("."))).toEqual([
      "harness",
      "outputs_root",
      "thinking",
      "sandbox.provider",
      "sandbox.image",
      "sandbox.template",
      "sandbox.cpus",
      "sandbox.memory_mb",
      "sandbox.workspace_mb",
      "sandbox.pids_limit",
      "sandbox.network",
      "sandbox.turn_timeout_s",
      "sandbox.idle_pause_s",
      "sandbox.ttl_s",
    ]);
    expect(fields[0]).toMatchObject({
      required: true,
      info: { widget: "select", options: ["pi", "opencode"] },
    });
    expect(fields.find((field) => field.path.join(".") === "sandbox.memory_mb")).toMatchObject({
      type: "integer",
      info: { default: 2048, label: "Memory (MB)" },
    });
    expect(codingFields(undefined)).toEqual([]);
  });
});

describe("withCodingSetting", () => {
  it("writes nested settings and drops emptied ones, keeping the marker", () => {
    const set = withCodingSetting(coder, ["sandbox", "cpus"], 4);
    expect(set.metadata).toEqual({
      owner: "platform",
      agnostic: { coding_agent: { harness: "pi", sandbox: { cpus: 4 } } },
    });
    const cleared = withCodingSetting(set, ["sandbox", "cpus"], undefined);
    expect(cleared.metadata).toEqual({ owner: "platform", agnostic: { coding_agent: { harness: "pi" } } });
  });
});

describe("CodingAgentSection", () => {
  it("edits the sandbox inside the agent's metadata", async () => {
    const user = userEvent.setup();
    const seen = { config: coder };
    renderWithProviders(<Harness initial={coder} seen={seen} />);
    expect(await screen.findByLabelText("CPUs")).toHaveAttribute("placeholder", "2");
    expect(screen.getByText("Test runs use the published version")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coding agent: Pi on Docker" })).toBeInTheDocument();
    // Docker by default: the image shows, the E2B template doesn't.
    expect(screen.getByLabelText("Image")).toHaveAttribute("placeholder", "agnostic-coding:0.1.0");
    expect(screen.queryByLabelText("E2B template")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("CPUs"), "4");
    await user.type(screen.getByLabelText("Outputs folder"), "out");
    expect(seen.config.metadata).toEqual({
      owner: "platform",
      agnostic: { coding_agent: { harness: "pi", outputs_root: "out", sandbox: { cpus: 4 } } },
    });
    expect(seen.config.name).toBe("Repo coder");
  });

  it("shows the E2B template for an E2B sandbox", async () => {
    const e2b: Config = {
      metadata: { agnostic: { coding_agent: { harness: "opencode", sandbox: { provider: "e2b" } } } },
    };
    renderWithProviders(<Harness initial={e2b} seen={{ config: e2b }} />);
    expect(await screen.findByLabelText("E2B template")).toBeInTheDocument();
    expect(screen.queryByLabelText("Image")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Coding agent: OpenCode on E2B" })).toBeInTheDocument();
  });

  it("renders nothing for an ordinary agent, and the form leaves its section out", () => {
    const plain: Config = { name: "Support triage" };
    const { container } = renderWithProviders(<Harness initial={plain} seen={{ config: plain }} />);
    expect(container).toBeEmptyDOMElement();
    renderWithProviders(
      <ConfigForm
        sections={[
          { id: "identity", label: "Identity", fields: [] },
          { id: "coding_agent", label: "Coding agent", fields: [] },
        ]}
        fields={{}}
        ctx={{
          config: plain,
          onChange: () => undefined,
          spans: {},
          focusedPath: undefined,
          onFocusPath: () => undefined,
          registry,
        }}
        ariaLabel="Agent configuration"
      />,
    );
    expect(screen.getByText("Identity")).toBeInTheDocument();
    expect(screen.queryByText("Coding agent")).not.toBeInTheDocument();
  });
});
