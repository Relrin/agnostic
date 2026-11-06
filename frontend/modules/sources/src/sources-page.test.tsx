import {
  sampleConnections,
  sampleOrgHandlers,
  renderPage,
  sourcesCalls,
  sourcesHandlers,
  type SourcesCalls,
} from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { usable } from "./connect-wizard";
import { connectionPatch } from "./connections";
import { SourcesPage as Page } from "./sources-page";

function SourcesPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

let calls: SourcesCalls = sourcesCalls();
const handlers = () => [...sourcesHandlers(calls), ...sampleOrgHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
beforeEach(() => {
  calls = sourcesCalls();
  server.resetHandlers(...handlers());
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

const PATH = "/i/$instance/studio/sources";
const URL = "/i/staging-agentos/studio/sources";

describe("SourcesPage", () => {
  it("shows the sources with their chips, path mapping and sync policy", async () => {
    renderPage(SourcesPage, { path: PATH, url: URL });
    const list = await screen.findByRole("list", { name: "Connected sources" });
    const cards = within(list).getAllByRole("button");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveAttribute("aria-pressed", "true");
    expect(cards[0]).toHaveTextContent("northwind/agent-platform · main");
    expect(cards[0]).toHaveTextContent("↓ 2 incoming");
    expect(cards[0]).toHaveTextContent("↑ 1 outgoing");
    expect(cards[0]).toHaveTextContent("1 conflict");
    expect(cards[1]).toHaveTextContent("up to date");
    expect(cards[1]).toHaveTextContent("read-only");
    expect(cards[2]).toHaveTextContent("in sync · 18 files");

    const mappings = screen.getByRole("list", { name: "Path mappings" });
    expect(mappings).toHaveTextContent("agents/*.py");
    expect(mappings).toHaveTextContent("Agents · 6");
    expect(mappings).toHaveTextContent("Registry · read-only");
    expect(screen.getByRole("radio", { name: "On demand" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Open a pull request" })).toBeChecked();
  });

  it("lists incoming changes with what pulling does, and pulls them as drafts", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const incoming = await screen.findByRole("region", { name: "Incoming" });
    expect(
      await within(incoming).findByText("Becomes draft v9 of ticket-router, next to your draft v8"),
    ).toBeInTheDocument();
    expect(within(incoming).getByText("Becomes draft v9 of kb-researcher")).toBeInTheDocument();
    await user.click(within(incoming).getByRole("checkbox", { name: "Include agents/kb_researcher.py" }));
    await waitFor(() => {
      expect(calls.includes).toEqual([{ change: "sch_2", included: false }]);
    });
    await user.click(within(incoming).getByRole("button", { name: "Pull 2 as drafts" }));
    await waitFor(() => {
      expect(calls.pulls).toEqual([["sch_1", "sch_2"]]);
    });
  });

  it("shows the outgoing change with the commit composer and commits it", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const outgoing = await screen.findByRole("region", { name: "Outgoing" });
    expect(
      await within(outgoing).findByText(
        "Draft v4 by Priya Nair · temperature 0.7 → 0.2, one new instruction",
      ),
    ).toBeInTheDocument();
    expect(
      await within(outgoing).findByText(
        "Branch studio/support-triage-v4 · PR into main · 1 review from Platform required",
      ),
    ).toBeInTheDocument();
    expect(within(outgoing).getByRole("textbox", { name: "Commit message" })).toHaveValue(
      "support-triage: lower temperature, add refund rule",
    );
    await user.click(within(outgoing).getByRole("button", { name: "Commit & open PR" }));
    await waitFor(() => {
      expect(calls.commits).toEqual([
        { change_ids: ["sch_out"], message: "support-triage: lower temperature, add refund rule" },
      ]);
    });
  });

  it("shows a conflict with both sides and resolves it", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const conflict = await screen.findByRole("article", { name: "Conflict on instructions[2]" });
    expect(conflict).toHaveTextContent("Repo · e81f0c4 · Sam Rivera");
    expect(conflict).toHaveTextContent("Refunds over $200 need a manager.");
    expect(conflict).toHaveTextContent("Studio · draft v6 · Maya Chen");
    expect(conflict).toHaveTextContent("Refunds over $150 need a manager.");
    await user.click(within(conflict).getByRole("button", { name: "Keep repo" }));
    await waitFor(() => {
      expect(calls.resolutions).toEqual([{ conflict: "scf_1", resolution: "keep_repo" }]);
    });
  });

  it("saves the sync policy", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    await user.click(await screen.findByRole("radio", { name: "On every push to main, as drafts" }));
    await waitFor(() => {
      expect(calls.updates[0]).toMatchObject({ policy: { pull_mode: "on_push_as_drafts" }, version: 3 });
    });
  });

  it("lists the connections and edits only what changed", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const list = await screen.findByRole("list", { name: "Connections" });
    const gitlab = within(list).getByRole("listitem", { name: "Data GitLab" });
    expect(gitlab).toHaveTextContent("Token · pull only");
    expect(gitlab).toHaveTextContent("GitLab refused the connection's credentials: 401 Unauthorized");
    expect(gitlab).toHaveTextContent("https://gitlab.northwind.test");
    expect(within(list).getByRole("listitem", { name: "Northwind GitHub" })).toHaveTextContent(
      "GitHub App · read & write · northwind",
    );

    await user.click(within(gitlab).getByRole("button", { name: "Edit Data GitLab" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit Data GitLab" });
    const server = within(dialog).getByRole("textbox", { name: "Server URL" });
    await user.clear(server);
    await user.type(server, "https://gitlab.northwind.example/");
    await user.type(within(dialog).getByLabelText("New token"), "glpat-rotated");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(calls.connectionUpdates).toEqual([
        {
          connection: "scn_gitlab",
          body: { version: 4, web_url: "https://gitlab.northwind.example", token: "glpat-rotated" },
        },
      ]);
    });
  });

  it("verifies and removes a connection", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    const list = await screen.findByRole("list", { name: "Connections" });
    await user.click(within(list).getByRole("button", { name: "Verify Data GitLab" }));
    await waitFor(() => {
      expect(calls.verified).toEqual(["scn_gitlab"]);
    });
    await user.click(within(list).getByRole("button", { name: "Remove Northwind Gitea" }));
    const dialog = await screen.findByRole("dialog", { name: "Remove Northwind Gitea?" });
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => {
      expect(calls.deletedConnections).toEqual(["scn_gitea"]);
    });
  });

  it("disconnects the selected source after asking", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    await user.click(await screen.findByRole("button", { name: "Disconnect source" }));
    const dialog = await screen.findByRole("dialog", { name: "Disconnect northwind/agent-platform · main?" });
    expect(dialog).toHaveTextContent("Its components stay in Studio");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => {
      expect(calls.deletedSources).toEqual(["src_github"]);
    });
  });

  it("resumes the wizard at the repository after the GitHub App install, and searches on the server", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: `${URL}?connect=1&connection=scn_github` });
    const dialog = await screen.findByRole("dialog", { name: "Connect source" });
    expect(within(dialog).getByRole("listitem", { current: "step" })).toHaveTextContent("Repository");
    await waitFor(() => {
      expect(calls.repoQueries).toEqual([null]);
    });
    await user.type(within(dialog).getByRole("searchbox", { name: "Search repositories" }), "data");
    await waitFor(() => {
      expect(calls.repoQueries).toContain("data");
    });
  });

  it("asks for GitHub Enterprise's server and API URLs on a new GitHub connection", async () => {
    const user = userEvent.setup();
    renderPage(SourcesPage, { path: PATH, url: URL });
    await user.click(await screen.findByRole("button", { name: "Connect source" }));
    const dialog = await screen.findByRole("dialog", { name: "Connect source" });
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(within(dialog).getByRole("textbox", { name: "Server URL" })).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: "API URL" })).toBeInTheDocument();
  });
});

describe("connections", () => {
  const sample = (id: string) => {
    const found = sampleConnections.find((item) => item.id === id);
    if (!found) throw new Error(`no sample connection ${id}`);
    return found;
  };
  const github = sample("scn_github");
  const gitlab = sample("scn_gitlab");
  const gitea = sample("scn_gitea");

  it("are offered across Gitea and Forgejo both ways, and nowhere else", () => {
    const forgejo = { ...gitea, id: "scn_forgejo", provider: "forgejo" };
    expect(usable(gitea, "forgejo")).toBe(true);
    expect(usable(forgejo, "gitea")).toBe(true);
    expect(usable(forgejo, "forgejo")).toBe(true);
    expect(usable(gitea, "github")).toBe(false);
    expect(usable(github, "gitlab")).toBe(false);
  });

  it("send only the fields that changed, and a secret only when one is typed", () => {
    const form = {
      name: gitlab.name,
      web_url: gitlab.web_url ?? "",
      api_url: "",
      access: gitlab.access,
      secret: "",
    };
    expect(connectionPatch(gitlab, form)).toEqual({ version: 4 });
    expect(connectionPatch(gitlab, { ...form, web_url: "", access: "read_write" })).toEqual({
      version: 4,
      web_url: null,
      access: "read_write",
    });
    expect(
      connectionPatch(github, { ...form, name: "GitHub", web_url: "", access: "read_write", secret: "x" }),
    ).toEqual({
      version: 2,
      name: "GitHub",
    });
  });
});
