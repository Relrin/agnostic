import { GATEWAY, artifactHandlers, operateHandlers, renderPage, sampleOrgHandlers } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
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
    // Images the Markdown embeds by relative path load from the session's own files.
    expect(await within(preview).findByRole("img", { name: "Volume chart" })).toHaveAttribute(
      "src",
      expect.stringMatching(/\/content\/.*filename=volume\.png/),
    );
    expect(within(preview).queryByRole("img", { name: "Missing chart" })).toBeNull();
    expect(within(preview).getByText("Missing chart")).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: /summary\.html/ }));
    const frame = await within(preview).findByTitle("Preview of summary.html");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts allow-popups");
    expect(frame.getAttribute("src")).toContain("disposition=inline");
  });

  it("shows each file's own content when switching between files", async () => {
    const user = userEvent.setup();
    renderPage(ArtifactsPage, { path: "/i/$instance/artifacts", url: "/i/prod-agentos/artifacts" });
    const list = await screen.findByRole("list", { name: "Files" });

    await user.click(within(list).getByRole("button", { name: /report\.md/ }));
    const preview = await screen.findByRole("region", { name: "Preview" });
    expect(
      await within(preview).findByRole("heading", { name: "Report: support volume" }),
    ).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: /data\.csv/ }));
    const csv = await within(preview).findByRole("table", { name: "CSV preview" });
    expect(within(csv).getByRole("columnheader", { name: "quarter" })).toBeInTheDocument();
    expect(within(csv).getByRole("cell", { name: "Q2" })).toBeInTheDocument();
    expect(within(preview).queryByRole("heading", { name: "Report: support volume" })).toBeNull();

    await user.click(within(preview).getByRole("radio", { name: "Source" }));
    expect(await within(preview).findByText(/quarter,volume/)).toBeInTheDocument();

    await user.click(within(list).getByRole("button", { name: /report\.md/ }));
    expect(
      await within(preview).findByRole("heading", { name: "Report: support volume" }),
    ).toBeInTheDocument();
    expect(within(preview).getByRole("radio", { name: "Preview" })).toBeChecked();
  });

  it("says there are no files yet when the instance has stored none", async () => {
    server.use(
      http.get(`${GATEWAY}/agnostic/v1/artifacts/recent`, () =>
        HttpResponse.json({ data: [], scanned_sessions: 0 }),
      ),
    );
    renderPage(ArtifactsPage, { path: "/i/$instance/artifacts", url: "/i/prod-agentos/artifacts" });
    expect(await screen.findByText("No files yet")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows no error when the instance doesn't serve the file listing", async () => {
    server.use(
      http.get(`${GATEWAY}/agnostic/v1/artifacts/recent`, () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );
    renderPage(ArtifactsPage, { path: "/i/$instance/artifacts", url: "/i/prod-agentos/artifacts" });
    expect(await screen.findByText("No files yet")).toBeInTheDocument();
    expect(screen.getByText(/doesn't list files yet/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText("Not Found")).toBeNull();
  });

  it("still reports a listing that failed on the instance", async () => {
    server.use(
      http.get(`${GATEWAY}/agnostic/v1/artifacts/recent`, () =>
        HttpResponse.json({ detail: "The database didn't answer" }, { status: 500 }),
      ),
    );
    renderPage(ArtifactsPage, { path: "/i/$instance/artifacts", url: "/i/prod-agentos/artifacts" });
    expect(await screen.findByRole("alert")).toHaveTextContent("The database didn't answer");
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
