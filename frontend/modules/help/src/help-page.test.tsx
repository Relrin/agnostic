import { API, p01Handlers, renderPage } from "@agnostic/testing";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { HelpPage } from "./help-page";

const handlers = () => [
  ...p01Handlers(),
  http.get(`${API}/system/docs`, () =>
    HttpResponse.json({
      available: true,
      guides: [
        { path: "admin/install.md", title: "Install Agnostic" },
        { path: "operator.md", title: "Operator guide" },
      ],
    }),
  ),
  http.get(
    `${API}/system/docs/admin/install.md`,
    () =>
      new HttpResponse(
        "# Install Agnostic\n\nRead [the upgrade guide](upgrades.md) or [agno](https://agno.com).",
        {
          headers: { "Content-Type": "text/markdown; charset=utf-8" },
        },
      ),
  ),
];
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

describe("HelpPage", () => {
  it("lists the bundled guides by section", async () => {
    renderPage(HelpPage, { path: "/help", url: "/help" });
    expect(await screen.findByRole("link", { name: "Install Agnostic" })).toHaveAttribute(
      "href",
      "/help/admin/install.md",
    );
    expect(screen.getByRole("heading", { name: "Administration" })).toBeInTheDocument();
  });

  it("renders a guide with links between guides kept in the app", async () => {
    renderPage(HelpPage, { path: "/help/$", url: "/help/admin/install.md" });
    expect(await screen.findByRole("heading", { name: "Install Agnostic" })).toBeInTheDocument();
    const internal = screen.getByRole("link", { name: "the upgrade guide" });
    expect(internal).toHaveAttribute("href", "/help/admin/upgrades.md");
    expect(internal).not.toHaveAttribute("target");
    expect(screen.getByRole("link", { name: "agno" })).toHaveAttribute("target", "_blank");
  });
});
