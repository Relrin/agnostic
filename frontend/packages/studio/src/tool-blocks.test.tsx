// The tool picker: catalog tools by level, the runtime's own tools, every Agno toolkit with an "already offered" hint,
// and a raw toolkit set up as a custom entry whose credentials are environment variable names.
import type { EntryIn, RegistryEntryOut } from "@agnostic/api";
import { catalogRegistryTools, renderWithProviders, toolCatalogHandlers } from "@agnostic/testing";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ToolCard, ToolPicker } from "./tool-blocks";

const store: { created: EntryIn[] } = { created: [] };
const server = setupServer(...toolCatalogHandlers(store));

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...toolCatalogHandlers(store));
  store.created = [];
});
afterAll(() => {
  server.close();
});

function firstTool(): RegistryEntryOut {
  const [first] = catalogRegistryTools;
  if (!first) throw new Error("the fixtures have catalog tools");
  return first;
}

const codeTool: RegistryEntryOut = {
  ...firstTool(),
  name: "kb_lookup",
  description: "Search the help center.",
  catalog: null,
};

function picker(onPick = vi.fn()) {
  renderWithProviders(
    <ToolPicker
      open
      onOpenChange={vi.fn()}
      instance="staging-agentos"
      available={[...catalogRegistryTools, codeTool]}
      offered={catalogRegistryTools}
      onPick={onPick}
    />,
  );
  return onPick;
}

describe("ToolPicker", () => {
  it("groups tools by where they come from", async () => {
    picker();
    const dialog = await screen.findByRole("dialog", { name: "Add a tool" });
    const org = within(dialog).getByRole("region", { name: "Organization" });
    expect(within(org).getByText("Linear")).toBeInTheDocument();
    expect(within(org).getByText("Web search")).toBeInTheDocument();
    const team = within(dialog).getByRole("region", { name: "Team · Data" });
    expect(within(team).getByText("Data search")).toBeInTheDocument();
    expect(within(team).getByText("missing credential")).toBeInTheDocument();
    expect(within(dialog).getByRole("region", { name: "Custom" })).toHaveTextContent(
      "not on this instance yet",
    );
    expect(within(dialog).getByRole("region", { name: "Runtime registry" })).toHaveTextContent("kb_lookup");
  });

  it("marks toolkits the organization or a team already offers", async () => {
    picker();
    const toolkits = await screen.findByRole("region", { name: "Agno toolkits" });
    const duck = (await within(toolkits).findByText("DuckDuckGo")).closest("button");
    expect(duck).toHaveTextContent("Organization version available");
    expect(within(toolkits).getByText("GitHub").closest("button")).toHaveTextContent("not installed");
    expect(within(toolkits).getByText("Shell").closest("button")).toHaveTextContent("runs commands");
  });

  it("shows each tool with the logo of the service it talks to", async () => {
    picker();
    const dialog = await screen.findByRole("dialog", { name: "Add a tool" });
    const logo = (text: string) =>
      within(dialog).getByText(text).closest("button")?.querySelector("[data-brand]");
    // An MCP server by its name, a catalog toolkit and a raw toolkit by their service, a code tool generic.
    expect(logo("Linear")).toHaveAttribute("data-brand", "linear");
    expect(logo("Web search")).toHaveAttribute("data-brand", "duckduckgo");
    const toolkits = within(dialog).getByRole("region", { name: "Agno toolkits" });
    expect(
      (await within(toolkits).findByText("GitHub")).closest("button")?.querySelector("[data-brand]"),
    ).toHaveAttribute("data-brand", "github");
    expect(logo("kb_lookup")).toBeNull();
  });

  it("adds a catalog tool", async () => {
    const user = userEvent.setup();
    const onPick = picker();
    await user.click(await screen.findByRole("button", { name: /Linear/ }));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ name: "org-linear" }));
  });

  it("sets a raw toolkit up for this instance with its credential as an environment variable", async () => {
    const user = userEvent.setup();
    picker();
    const toolkits = await screen.findByRole("region", { name: "Agno toolkits" });
    await user.click(await within(toolkits).findByText("Tavily"));
    await user.type(screen.getByRole("textbox", { name: "api_key" }), "tavily_key");
    await user.click(screen.getByRole("button", { name: "Set up for this instance" }));

    expect(await screen.findByText(/is set up/)).toBeInTheDocument();
    expect(store.created).toEqual([
      expect.objectContaining({
        level: "custom",
        kind: "toolkit",
        toolkit_key: "tavily",
        instance_ids: ["staging-agentos"],
        config: { params: { api_key: { env: "TAVILY_KEY" } } },
      }),
    ]);
  });
});

describe("ToolCard", () => {
  it("shows the level, kind, tool count and runtime state", () => {
    const warehouse = catalogRegistryTools.find((entry) => entry.name === "team-data-warehouse");
    renderWithProviders(
      <ul>
        <ToolCard name="team-data-warehouse" entry={warehouse} functions={0} approval={false} />
        <ToolCard name="gone" entry={undefined} functions={0} approval />
      </ul>,
    );
    const [first, second] = screen.getAllByRole("listitem");
    expect(first).toHaveTextContent("Warehouse");
    expect(first).toHaveTextContent("Team · Data");
    expect(first).toHaveTextContent("MCP server · sse");
    expect(first).toHaveTextContent("missing credential");
    expect(second).toHaveTextContent("not registered");
    expect(second).toHaveTextContent("needs approval");
  });
});
