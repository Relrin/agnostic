import {
  API,
  SUPPORT_LEAD_ROLE,
  emptyRolesRecord,
  p01Handlers,
  renderPage,
  rolesHandlers,
  type RolesRecord,
} from "@agnostic/testing";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { RolesPage } from "./roles-page";

let record: RolesRecord = emptyRolesRecord();
// The roles handlers go first: p01 serves a plainer role list.
const handlers = () => [...rolesHandlers(record), ...p01Handlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  record = emptyRolesRecord();
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const PATH = "/access/roles";
const open = (role: string) => renderPage(RolesPage, { path: PATH, url: `${PATH}?role=${role}` });

describe("RolesPage", () => {
  it("lists org roles with member counts and access roles with people counts", async () => {
    renderPage(RolesPage, { path: PATH });
    const nav = await screen.findByRole("navigation", { name: "Roles" });
    expect(await within(nav).findByRole("link", { name: "Operator, 9 people" })).toBeInTheDocument();
    expect(await within(nav).findByRole("link", { name: "Owner, 1 member" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Member, 1 member" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Support lead, 3 people" })).toBeInTheDocument();
    // The first access role is selected without a ?role.
    expect(await screen.findByRole("table", { name: "Instance admin permissions" })).toBeInTheDocument();
  });

  it("shows an org role read-only with who has it", async () => {
    open("owner");
    expect(await screen.findByRole("heading", { name: "Owner" })).toBeInTheDocument();
    const members = screen.getByRole("region", { name: "Members" });
    expect(await within(members).findByText("Daniel Okafor")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Save changes" })).not.toBeInTheDocument();
  });

  it("derives the matrix from the scope catalog with N/A cells and hidden scopes left out", async () => {
    open("rol_operator");
    const table = await screen.findByRole("table", { name: "Operator permissions" });
    for (const group of ["Primitives & Studio", "Runtime data", "Control", "Platform"]) {
      expect(within(table).getByRole("columnheader", { name: group })).toBeInTheDocument();
    }
    expect(within(table).getByRole("checkbox", { name: "Operator: agents run" })).toBeChecked();
    expect(within(table).getByRole("checkbox", { name: "Operator: queue operate" })).toBeChecked();
    expect(within(table).queryByRole("checkbox", { name: "Operator: traces write" })).not.toBeInTheDocument();
    const traces = within(table)
      .getByRole("rowheader", { name: /Traces/ })
      .closest("tr");
    if (!traces) throw new Error("The Traces row is missing");
    expect(within(traces).getAllByText("Not applicable")).toHaveLength(3);
    expect(within(table).queryByText("products")).not.toBeInTheDocument();
    expect(within(table).queryByText("org:roles:write")).not.toBeInTheDocument();
  });

  it("reproduces the Operator edit: +knowledge:write, −approvals:delete, then saves with the version", async () => {
    const user = userEvent.setup();
    open("rol_operator");
    const knowledgeWrite = await screen.findByRole("checkbox", { name: "Operator: knowledge write" });
    const approvalsDelete = screen.getByRole("checkbox", { name: "Operator: approvals delete" });
    expect(knowledgeWrite).not.toBeChecked();
    expect(approvalsDelete).toBeChecked();
    const bar = screen.getByRole("region", { name: "Save changes" });
    expect(within(bar).getByText("All changes saved")).toBeInTheDocument();

    await user.click(knowledgeWrite);
    await user.click(approvalsDelete);
    expect(within(bar).getByText("2 unsaved changes")).toBeInTheDocument();
    expect(knowledgeWrite.closest("td")).toHaveClass("bg-accent/9");

    const aside = screen.getByRole("complementary", { name: "Token scopes" });
    const changes = await within(aside).findByRole("list", { name: "Scope changes" });
    expect(within(changes).getByText("knowledge:write")).toBeInTheDocument();
    expect(within(changes).getByText("approvals:delete")).toBeInTheDocument();
    expect(within(changes).getAllByText("Added")).toHaveLength(1);
    expect(within(changes).getAllByText("Removed")).toHaveLength(1);
    expect(within(aside).getByLabelText("22 scopes")).toHaveTextContent("22");
    expect(
      within(aside).getByText(
        "9 people and 2 groups (Support AI, Billing ops) get the new scopes on their next request.",
        { exact: false },
      ),
    ).toBeInTheDocument();
    expect(within(aside).getByText("No redeploy.")).toBeInTheDocument();
    expect(within(aside).getByText("Recorded in the audit log with this diff.")).toBeInTheDocument();

    await user.click(within(bar).getByRole("button", { name: "Save role" }));
    await waitFor(() => {
      expect(record.updates).toHaveLength(1);
    });
    const sent = record.updates[0];
    expect(sent?.version).toBe(4);
    expect(sent?.permissions.knowledge).toEqual(["read", "write"]);
    expect(sent?.permissions.approvals).toEqual(["read", "write"]);
    expect(sent?.bindable_instance_ids).toBeNull();
    expect(await within(bar).findByText("All changes saved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Version 5" })).toBeInTheDocument();
  });

  it("discards the draft", async () => {
    const user = userEvent.setup();
    open("rol_operator");
    const knowledgeWrite = await screen.findByRole("checkbox", { name: "Operator: knowledge write" });
    await user.click(knowledgeWrite);
    await user.click(screen.getByRole("button", { name: "prod-agentos" }));
    const bar = screen.getByRole("region", { name: "Save changes" });
    expect(within(bar).getByText("2 unsaved changes")).toBeInTheDocument();
    await user.click(within(bar).getByRole("button", { name: "Discard" }));
    expect(within(bar).getByText("All changes saved")).toBeInTheDocument();
    expect(knowledgeWrite).not.toBeChecked();
    expect(screen.getByRole("button", { name: "prod-agentos" })).toHaveAttribute("aria-pressed", "true");
  });

  it("narrows run to selected agents and previews the per-agent scopes", async () => {
    const user = userEvent.setup();
    open("rol_operator");
    await screen.findByRole("table", { name: "Operator permissions" });
    const segment = screen.getByRole("radiogroup", { name: "agents run applies to" });
    await user.click(within(segment).getByRole("radio", { name: "Selected agents" }));
    await user.type(screen.getByRole("textbox", { name: "Add agent id" }), "support-triage{Enter}");
    const bar = screen.getByRole("region", { name: "Save changes" });
    expect(within(bar).getByText("1 unsaved change")).toBeInTheDocument();
    const aside = screen.getByRole("complementary", { name: "Token scopes" });
    const changes = await within(aside).findByRole("list", { name: "Scope changes" });
    // The aside follows a debounced preview; wait for the one that reflects the selected agent.
    expect(await within(changes).findByText("agents:support-triage:run")).toBeInTheDocument();
    expect(within(changes).getByText("agents:run")).toBeInTheDocument();
    expect(record.previews.at(-1)?.run_scope).toEqual({ agents: ["support-triage"] });
  });

  it("explains a version conflict and reloads", async () => {
    const user = userEvent.setup();
    open("rol_operator");
    await user.click(await screen.findByRole("checkbox", { name: "Operator: knowledge write" }));
    server.use(
      http.patch(`${API}/access/roles/:role`, () =>
        HttpResponse.json(
          {
            type: "x",
            title: "Conflict",
            status: 409,
            code: "version_conflict",
            detail: "Operator changed since you opened it (version 5); reload to see the changes.",
          },
          { status: 409 },
        ),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Save role" }));
    const callout = await screen.findByRole("alert");
    expect(callout).toHaveTextContent("Operator changed since you opened it");
    await user.click(within(callout).getByRole("button", { name: "Reload" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Reload" })).not.toBeInTheDocument();
    });
    expect(screen.getByText("All changes saved")).toBeInTheDocument();
  });

  it("shows the bindings that block deleting a custom role", async () => {
    const user = userEvent.setup();
    open(SUPPORT_LEAD_ROLE);
    await screen.findByRole("table", { name: "Support lead permissions" });
    expect(screen.queryByRole("button", { name: "Reset to default" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete Support lead?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete role" }));
    expect(
      await within(dialog).findByRole("heading", { name: "Support lead is still bound" }),
    ).toBeInTheDocument();
    const bindings = within(dialog).getByRole("list", { name: "Bindings" });
    const items = within(bindings).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Marcus Chen");
    expect(items[0]).toHaveTextContent("prod-agentos");
    expect(items[1]).toHaveTextContent("Support AI");
    expect(items[1]).toHaveTextContent("group");
    expect(record.deletes).toEqual([SUPPORT_LEAD_ROLE]);
  });

  it("resets a built-in role to its defaults", async () => {
    const user = userEvent.setup();
    open("rol_viewer");
    const knowledgeWrite = await screen.findByRole("checkbox", { name: "Viewer: knowledge write" });
    expect(knowledgeWrite).toBeChecked();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    const dialog = await screen.findByRole("dialog", { name: "Reset Viewer to default?" });
    await user.click(within(dialog).getByRole("button", { name: "Reset role" }));
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: "Viewer: knowledge write" })).not.toBeChecked();
    });
    expect(record.resets).toEqual(["rol_viewer"]);
    expect(screen.getByRole("button", { name: "Version 4" })).toBeInTheDocument();
  });

  it("lists who holds a role and its versions", async () => {
    const user = userEvent.setup();
    open("rol_operator");
    await user.click(await screen.findByRole("button", { name: "9 people · 2 groups · 1 service account" }));
    const sheet = await screen.findByRole("dialog", { name: "Who holds Operator" });
    const holders = await within(sheet).findByRole("list", { name: "Holders" });
    expect(await within(holders).findByText("Marcus Chen")).toBeInTheDocument();
    expect(within(holders).getByText("Support AI")).toBeInTheDocument();
    expect(within(holders).getByText("Billing ops")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Version 4" }));
    const versions = await screen.findByRole("dialog", { name: "Operator versions" });
    const list = await within(versions).findByRole("list", { name: "Versions" });
    expect(within(list).getAllByText(/^Version \d$/)).toHaveLength(4);
    expect(within(list).getByText("current")).toBeInTheDocument();
  });

  it("creates a blank role and opens it", async () => {
    const user = userEvent.setup();
    renderPage(RolesPage, { path: PATH });
    await user.click(await screen.findByRole("button", { name: "New role" }));
    const dialog = await screen.findByRole("dialog", { name: "New access role" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Night shift");
    await user.click(within(dialog).getByRole("radio", { name: "Purple" }));
    await user.click(within(dialog).getByRole("button", { name: "Create role" }));
    await waitFor(() => {
      expect(record.creates).toHaveLength(1);
    });
    expect(record.creates[0]).toMatchObject({
      name: "Night shift",
      color: "#B79CFF",
      permissions: { agents: ["read"] },
      bindable_instance_ids: null,
    });
    expect(await screen.findByRole("table", { name: "Night shift permissions" })).toBeInTheDocument();
  });
});
