import { API, sampleOrgHandlers, renderPage, studioHandlers } from "@agnostic/testing";
import { TooltipProvider, toast } from "@agnostic/ui";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { TeamEditorPage as Editor } from "./teams-page";

function TeamEditorPage() {
  return (
    <TooltipProvider>
      <Editor />
    </TooltipProvider>
  );
}

const handlers = () => [...sampleOrgHandlers(), ...studioHandlers()];
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

describe("TeamEditorPage", () => {
  it("switching the mode updates the explainer, the code and the unpublished indicator", async () => {
    const user = userEvent.setup();
    renderPage(TeamEditorPage, {
      path: "/i/$instance/studio/teams/$componentId",
      url: "/i/staging-agentos/studio/teams/research-team",
    });
    const flow = await screen.findByRole("list", { name: "Request flow" });
    expect(within(flow).getByText(/The leader splits the question/)).toBeInTheDocument();
    expect(screen.getByText("v4", { exact: false })).toBeInTheDocument(); // summarizer is pinned at v4
    expect(screen.queryByText(/unpublished/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /Tasks/ }));
    expect(
      within(flow).getByText("The loop ends when the goal is met or after 10 iterations."),
    ).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Max iterations" })).toBeInTheDocument();
    expect(await screen.findByText("↑ 1 unpublished · mode changed")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.body.textContent).toContain("mode=TeamMode.tasks");
    });
  });

  it("a save flushed as the editor closes settles without touching it, even once the page is gone", async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const saves: string[] = [];
    server.use(
      http.patch(`${API}/instances/:instance/studio/components/:id/configs/:version`, async ({ params }) => {
        saves.push(String(params.id));
        await held;
        return HttpResponse.json(
          {
            type: "about:blank",
            title: "Service unavailable",
            status: 503,
            detail: "The instance didn't answer.",
          },
          { status: 503 },
        );
      }),
    );
    const errors = vi.spyOn(toast, "error");
    const user = userEvent.setup();
    const view = renderPage(TeamEditorPage, {
      path: "/i/$instance/studio/teams/$componentId",
      url: "/i/staging-agentos/studio/teams/research-team",
    });
    await screen.findByRole("list", { name: "Request flow" });
    await user.click(screen.getByRole("radio", { name: /Tasks/ }));

    view.unmount(); // flushes the pending autosave
    await waitFor(() => {
      expect(saves).toEqual(["research-team"]);
    });
    // As when the test environment is torn down first: React reads `window` when it schedules a state update.
    const page = globalThis.window;
    Reflect.deleteProperty(globalThis, "window");
    try {
      release();
      await vi.waitFor(() => {
        expect(errors).toHaveBeenCalledWith("The control plane didn't answer.");
      });
    } finally {
      globalThis.window = page;
      errors.mockRestore();
    }
  });
});
