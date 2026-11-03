import { configureApi } from "@agnostic/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { useState } from "react";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ReauthProvider, useReauth } from "./reauth";

const API = "http://agnostic.test/api/v1";
const reauthRequired = {
  type: "urn:agnostic:problem:reauth_required",
  title: "Confirm it's you",
  status: 403,
  code: "reauth_required",
  detail: "This change needs a recent sign-in.",
  reauth_window_seconds: 600,
};
const stepUp = {
  authenticated_at: "2026-11-01T09:00:00Z",
  recent: false,
  expires_at: null,
  methods: ["password", "totp"],
  sso_providers: [],
};

const server = setupServer(
  http.get(`${API}/auth/step-up`, () => HttpResponse.json(stepUp)),
  http.get(`${API}/auth/providers`, () => HttpResponse.json({ local_login: true, providers: [] })),
);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers();
});
afterAll(() => {
  server.close();
});

function Harness({ action }: { action: () => Promise<string> }) {
  const reauth = useReauth();
  const [result, setResult] = useState("idle");
  return (
    <>
      <button
        type="button"
        onClick={() => {
          reauth.run(action).then(setResult, (error: unknown) => {
            setResult(`failed: ${(error as { code?: string }).code ?? "?"}`);
          });
        }}
      >
        Save
      </button>
      <p>Result: {result}</p>
    </>
  );
}

function renderHarness(action: () => Promise<string>, provider = true) {
  configureApi({ baseUrl: "http://agnostic.test" });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {provider ? (
        <ReauthProvider>
          <Harness action={action} />
        </ReauthProvider>
      ) : (
        <Harness action={action} />
      )}
    </QueryClientProvider>,
  );
}

describe("useReauth", () => {
  it("asks for the password on reauth_required and retries once", async () => {
    let calls = 0;
    let stepUpBody: unknown;
    server.use(
      http.post(`${API}/auth/step-up`, async ({ request }) => {
        stepUpBody = await request.json();
        return HttpResponse.json({ ...stepUp, recent: true });
      }),
    );
    const action = () => {
      calls += 1;
      // The generated client throws problem bodies as they are.
      // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
      return calls === 1 ? Promise.reject(reauthRequired) : Promise.resolve("saved");
    };
    const user = userEvent.setup();
    renderHarness(action);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("dialog", { name: "Confirm it's you" })).toBeInTheDocument();
    expect(screen.getByText(/Confirming lasts 10 minutes/)).toBeInTheDocument();
    await user.type(await screen.findByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Result: saved")).toBeInTheDocument();
    expect(calls).toBe(2);
    expect(stepUpBody).toEqual({ password: "correct horse" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("says when the password is wrong and keeps the dialog open", async () => {
    server.use(
      http.post(`${API}/auth/step-up`, () =>
        HttpResponse.json(
          { type: "x", title: "Not confirmed", status: 422, code: "step_up_failed" },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
    renderHarness(() => Promise.reject(reauthRequired));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.type(await screen.findByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("That password isn't right.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Result: failed: reauth_required")).toBeInTheDocument();
  });

  it("passes other errors and missing providers through", async () => {
    const user = userEvent.setup();
    // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors
    renderHarness(() => Promise.reject(reauthRequired), false);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Result: failed: reauth_required")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
