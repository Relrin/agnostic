import { API, renderPage } from "@agnostic/testing";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { LoginPage } from "./login-page";

const handlers = [
  http.get(`${API}/auth/providers`, () =>
    HttpResponse.json({
      local_login: true,
      providers: [
        { id: "okta", display_name: "Okta", preset: "okta" },
        { id: "github", display_name: "GitHub", preset: "github" },
      ],
    }),
  ),
  http.get(`${API}/onboarding/status`, () =>
    HttpResponse.json({ org_exists: true, owner_exists: true, org_name: "Localhost Company" }),
  ),
];
const server = setupServer(...handlers);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers);
});
afterAll(() => {
  server.close();
});

describe("LoginPage", () => {
  it("offers SSO providers that come back to the requested page", async () => {
    renderPage(LoginPage, { path: "/login", url: "/login?next=/access/people" });
    const okta = await screen.findByRole("link", { name: "Continue with Okta" });
    expect(okta).toHaveAttribute("href", "/api/v1/auth/sso/okta/start?next=%2Faccess%2Fpeople");
    expect(screen.getByRole("link", { name: "Continue with GitHub" })).toBeInTheDocument();
  });

  it("explains SSO errors", async () => {
    renderPage(LoginPage, { path: "/login", url: "/login?error=not_invited" });
    expect(await screen.findByText(/You need an invitation to join this org/)).toBeInTheDocument();
  });

  it("signs in with a password and goes on", async () => {
    let body: unknown;
    server.use(
      http.post(`${API}/auth/login`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ user: {}, csrf_token: "t" });
      }),
      http.get(`${API}/me`, () => HttpResponse.json({ id: "usr_1" })),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login", url: "/login?next=/instances" });
    await user.type(await screen.findByLabelText("Email"), "daniel@localhost.company");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Navigated away")).toBeInTheDocument();
    expect(body).toEqual({ email: "daniel@localhost.company", password: "correct horse battery staple" });
  });

  it("shows why sign-in failed", async () => {
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json(
          {
            type: "urn:agnostic:problem:invalid_credentials",
            title: "Email or password is wrong",
            status: 401,
            code: "invalid_credentials",
            detail: "Check your email and password and try again.",
          },
          { status: 401 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login" });
    await user.type(await screen.findByLabelText("Email"), "daniel@localhost.company");
    await user.type(screen.getByLabelText("Password"), "wrong password!!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Check your email and password");
    });
  });
});
