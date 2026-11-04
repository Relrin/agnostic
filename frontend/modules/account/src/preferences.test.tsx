import { DensityProvider, useMe } from "@agnostic/core";
import { API, sampleOrgHandlers, renderWithProviders, sampleMe } from "@agnostic/testing";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { Preferences } from "./preferences";

const server = setupServer(...sampleOrgHandlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...sampleOrgHandlers());
  delete document.documentElement.dataset.density;
});
afterAll(() => {
  server.close();
});

function SignedInPreferences() {
  const me = useMe();
  return me.data ? <Preferences me={me.data} /> : null;
}

describe("Preferences", () => {
  it("switches to the compact density and applies it to the page", async () => {
    let sent: unknown;
    server.use(
      http.patch(`${API}/me`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ ...sampleMe, preferences: { density: "compact" } });
      }),
    );
    renderWithProviders(
      <DensityProvider>
        <SignedInPreferences />
      </DensityProvider>,
    );
    const compact = await screen.findByRole("radio", { name: /Compact/ });
    expect(screen.getByRole("radio", { name: /Comfortable/ })).toBeChecked();
    expect(document.documentElement.dataset.density).toBe("comfortable");

    await userEvent.setup().click(compact);

    await waitFor(() => {
      expect(compact).toBeChecked();
    });
    expect(sent).toEqual({ preferences: { density: "compact" } });
    expect(document.documentElement.dataset.density).toBe("compact");
  });
});
