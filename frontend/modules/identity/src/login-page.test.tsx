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

  it("asks for the authenticator code after the password", async () => {
    let mfaBody: unknown;
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json({
          mfa_required: true,
          challenge: "mfc_123",
          methods: ["totp", "recovery_code"],
          enroll: false,
        }),
      ),
      http.post(`${API}/auth/login/mfa`, async ({ request }) => {
        mfaBody = await request.json();
        return HttpResponse.json({ user: {}, csrf_token: "t", recovery_codes: [] });
      }),
      http.get(`${API}/me`, () => HttpResponse.json({ id: "usr_1" })),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login", url: "/login?next=/instances" });
    await user.type(await screen.findByLabelText("Email"), "daniel@localhost.company");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Two-step verification" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Authenticator code"), "123 456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Navigated away")).toBeInTheDocument();
    expect(mfaBody).toEqual({ challenge: "mfc_123", code: "123456" });
  });

  it("takes a recovery code and explains a wrong one", async () => {
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json({
          mfa_required: true,
          challenge: "mfc_1",
          methods: ["totp", "recovery_code"],
          enroll: false,
        }),
      ),
      http.post(`${API}/auth/login/mfa`, () =>
        HttpResponse.json(
          { type: "x", title: "Wrong code", status: 401, code: "mfa_invalid" },
          { status: 401 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login" });
    await user.type(await screen.findByLabelText("Email"), "daniel@localhost.company");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await user.click(await screen.findByRole("button", { name: "Use a recovery code" }));
    await user.type(screen.getByLabelText("Recovery code"), "7hq2-k9mx");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText(/That recovery code isn't right/)).toBeInTheDocument();
  });

  it("enrolls an authenticator app at sign-in and shows the recovery codes once", async () => {
    let mfaBody: unknown;
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json({
          mfa_required: true,
          challenge: "mfc_9",
          methods: ["totp", "webauthn"],
          enroll: true,
        }),
      ),
      http.post(`${API}/auth/login/mfa/totp/setup`, () =>
        HttpResponse.json({
          secret: "JBSWY3DPEHPK3PXP",
          otpauth_uri: "otpauth://totp/Agnostic:daniel?secret=JBSWY3DPEHPK3PXP",
        }),
      ),
      http.post(`${API}/auth/login/mfa`, async ({ request }) => {
        mfaBody = await request.json();
        return HttpResponse.json({ user: {}, csrf_token: "t", recovery_codes: ["aaaa-1111", "bbbb-2222"] });
      }),
      http.get(`${API}/me`, () => HttpResponse.json({ id: "usr_1" })),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login" });
    await user.type(await screen.findByLabelText("Email"), "daniel@localhost.company");
    await user.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Set up two-step verification")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set up an authenticator app" }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Code from the app"), "654321");
    await user.click(screen.getByRole("button", { name: "Turn on and sign in" }));
    expect(await screen.findByText(/aaaa-1111/)).toBeInTheDocument();
    expect(mfaBody).toEqual({ challenge: "mfc_9", code: "654321", label: "Authenticator app" });
    await user.click(screen.getByRole("button", { name: "I've saved them, continue" }));
    expect(await screen.findByText("Navigated away")).toBeInTheDocument();
  });

  it("points to SSO when the org requires it", async () => {
    server.use(
      http.post(`${API}/auth/login`, () =>
        HttpResponse.json(
          {
            type: "x",
            title: "SSO required",
            status: 403,
            code: "sso_required",
            detail: "Sign in with SSO.",
          },
          { status: 403 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login" });
    await user.type(await screen.findByLabelText("Email"), "marcus@localhost.company");
    await user.type(screen.getByLabelText("Password"), "a password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Your org signs in with SSO")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue with Okta" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Break-glass sign-in" })).toBeInTheDocument();
  });

  it("folds the password form away while SSO is enforced, and offers SAML providers", async () => {
    server.use(
      http.get(`${API}/auth/providers`, () =>
        HttpResponse.json({
          local_login: true,
          sso_enforced: true,
          providers: [{ id: "okta-saml", display_name: "Okta", preset: "saml" }],
        }),
      ),
    );
    const user = userEvent.setup();
    renderPage(LoginPage, { path: "/login" });
    const okta = await screen.findByRole("link", { name: "Continue with Okta" });
    expect(okta).toHaveAttribute("href", "/api/v1/auth/sso/okta-saml/start?next=%2F");
    expect(okta).toHaveAttribute("data-preset", "saml");
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Break-glass sign-in" }));
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByText(/Only the org's break-glass Owner/)).toBeInTheDocument();
  });

  it("explains SAML errors", async () => {
    renderPage(LoginPage, { path: "/login", url: "/login?error=saml_audience" });
    expect(await screen.findByText(/meant for a different app/)).toBeInTheDocument();
  });
});
