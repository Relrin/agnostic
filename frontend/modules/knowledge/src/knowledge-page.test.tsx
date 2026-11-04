import { API, contextHandlers, sampleOrgHandlers, operateHandlers, renderPage } from "@agnostic/testing";
import { TooltipProvider } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { KnowledgePage as Page } from "./knowledge-page";

/** Tooltips need the provider the shell mounts. */
function KnowledgePage() {
  return (
    <TooltipProvider>
      <Page />
    </TooltipProvider>
  );
}

const handlers = () => [...contextHandlers(), ...sampleOrgHandlers(), ...operateHandlers()];
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

describe("KnowledgePage", () => {
  it("shows the knowledge base, its readers, counters and content statuses", async () => {
    renderPage(KnowledgePage, { path: "/i/$instance/knowledge", url: "/i/prod-agentos/knowledge" });
    expect(await screen.findByRole("heading", { name: "help_center" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /support-triage/ })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Content" });
    expect(within(table).getByText("Reader error: file is password-protected")).toBeInTheDocument();
    expect(within(table).getByText("Embedding, 62%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 failed" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 processing" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Add to help_center" })).toBeDisabled();
  });

  it("runs a test retrieval and shows scored chunks", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    server.use(
      http.post(`${API}/instances/:instance/os/knowledge/search`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          data: [
            {
              content: "Refunds take 5 to 10 business days.",
              name: "refund-policy-2026.pdf",
              reranking_score: 0.86,
            },
          ],
          meta: { page: 1, limit: 5, total_count: 1, total_pages: 1, search_time_ms: 142 },
        });
      }),
    );
    renderPage(KnowledgePage, { path: "/i/$instance/knowledge", url: "/i/prod-agentos/knowledge" });
    await user.type(await screen.findByRole("textbox", { name: "Query" }), "customer charged twice");
    await user.click(screen.getByRole("button", { name: "Search" }));
    const results = await screen.findByRole("list", { name: "Top chunks" });
    expect(within(results).getByText("0.86")).toBeInTheDocument();
    expect(screen.getByText(/1 results in 142 ms · hybrid search · reranking on/)).toBeInTheDocument();
    expect(sent).toMatchObject({
      query: "customer charged twice",
      knowledge_id: "kb_help_center",
      max_results: 5,
    });
  });

  it("adds pasted text to the selected knowledge base", async () => {
    const user = userEvent.setup();
    let form: FormData | undefined;
    server.use(
      http.post(`${API}/instances/:instance/os/knowledge/content`, async ({ request }) => {
        form = await request.formData();
        return HttpResponse.json({ id: "c9", status: "processing" }, { status: 202 });
      }),
    );
    renderPage(KnowledgePage, { path: "/i/$instance/knowledge", url: "/i/prod-agentos/knowledge" });
    const aside = await screen.findByRole("complementary", { name: "Add content" });
    await user.click(within(aside).getByRole("radio", { name: "Text" }));
    await user.type(await within(aside).findByRole("textbox", { name: "Text" }), "Status page FAQ");
    await user.click(within(aside).getByRole("button", { name: "Add to help_center" }));
    await waitFor(() => {
      expect(form?.get("text_content")).toBe("Status page FAQ");
    });
  });
});
