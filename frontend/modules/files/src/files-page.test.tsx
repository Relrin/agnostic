import { contextHandlers, p01Handlers, p02Handlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, within } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { parseCsv } from "./files-api";
import { FilesPage as Page } from "./files-page";

/** Tooltips need the provider the shell mounts. */
function FilesPage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...contextHandlers(), ...p01Handlers(), ...p02Handlers()];
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

describe("FilesPage", () => {
  it("browses folders, previews a brief and says where it came from", async () => {
    renderPage(FilesPage, {
      path: "/i/$instance/files",
      url: "/i/prod-agentos/files?dir=reports%2Fdaily-brief&file=reports%2Fdaily-brief%2F2026-10-30.md",
    });
    expect(await screen.findByText("2.1 GB of 20.0 GB")).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Files" });
    expect(within(table).getByText("2026-10-31.md")).toBeInTheDocument();
    expect(screen.getByText(/daily-brief writes here; kb-researcher can only read/)).toBeInTheDocument();
    const preview = await screen.findByRole("complementary", { name: "File preview" });
    expect(
      await within(preview).findByRole("heading", { name: "Daily brief: Thu 30 Oct 2026" }),
    ).toBeInTheDocument();
    const origin = within(preview).getByRole("region", { name: "Where this came from" });
    expect(await within(origin).findByText("Compile brief")).toBeInTheDocument();
    expect(within(origin).getByText("kb-researcher, 2 times")).toBeInTheDocument();
    expect(within(origin).getByRole("link", { name: "Open trace" })).toHaveAttribute(
      "href",
      "/i/prod-agentos/traces/tr_2f81c0",
    );
  });

  it("renders CSV files as a grid", async () => {
    renderPage(FilesPage, {
      path: "/i/$instance/files",
      url: "/i/prod-agentos/files?dir=reports%2Fdaily-brief&file=reports%2Fdaily-brief%2Fsources-2026-10-30.csv",
    });
    const grid = await screen.findByRole("table", { name: "CSV preview" });
    expect(within(grid).getByRole("columnheader", { name: "source" })).toBeInTheDocument();
    expect(within(grid).getByText("Android 4.12 sync")).toBeInTheDocument();
  });

  it("parses quoted CSV fields", () => {
    expect(parseCsv('a,b\n"x, y","say ""hi"""\r\n')).toEqual([
      ["a", "b"],
      ["x, y", 'say "hi"'],
    ]);
  });
});
