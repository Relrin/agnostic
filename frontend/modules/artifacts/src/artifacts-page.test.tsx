import { artifactHandlers, operateHandlers, renderPage, sampleOrgHandlers } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ArtifactsPage as Page } from "./artifacts-page";
import { SharePage } from "./share-page";

function ArtifactsPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...artifactHandlers(), ...sampleOrgHandlers(), ...operateHandlers()];
const server = setupServer(...handlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers());
});
afterAll(() => {
  server.close();
});

describe("ArtifactsPage", () => {
  it("lists the files, filters them and previews Markdown and HTML", async () => {
    const user = userEvent.setup();
    renderPage(ArtifactsPage, { path: "/i/$instance/artifacts", url: "/i/prod-agentos/artifacts" });
    const list = await screen.findByRole("list", { name: "Files" });
    expect(within(list).getAllByRole("button")).toHaveLength(4);
    expect(screen.getByText(/from the 12 most recent sessions/)).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Filter files" }), "csv");
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    await user.clear(screen.getByRole("textbox", { name: "Filter files" }));

    await user.click(within(list).getByRole("button", { name: /report\.md/ }));
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(
      await within(preview).findByRole("heading", { name: "Report: support volume" }),
    ).toBeInTheDocument();
    expect(within(preview).getByRole("table")).toBeInTheDocument();
    expect(within(preview).getByRole("button", { name: "Download" })).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: /summary\.html/ }));
    const frame = await within(preview).findByTitle("Preview of summary.html");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts allow-popups");
    expect(frame.getAttribute("src")).toContain("disposition=inline");
  });

  it("shows share links with their state", async () => {
    renderPage(ArtifactsPage, {
      path: "/i/$instance/artifacts",
      url: "/i/prod-agentos/artifacts?view=links",
    });
    const table = await screen.findByRole("table", { name: "Share links" });
    expect(within(table).getByText("report.md")).toBeInTheDocument();
    expect(within(table).getByText("Daniel Okafor")).toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  });
});

describe("SharePage", () => {
  it("opens a shared file read-only", async () => {
    renderPage(SharePage, { path: "/s/$token", url: "/s/ash_sample-token-0000000000000000" });
    expect(await screen.findByRole("heading", { name: "report.md" })).toBeInTheDocument();
    expect(screen.getByText(/Shared by Daniel Okafor/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Report: support volume" })).toBeInTheDocument();
  });
});
