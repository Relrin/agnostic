import { API, renderWithProviders, sampleMyMfa, sampleRecoveryCodes } from "@agnostic/testing";
import type { MfaOut } from "@agnostic/api";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { TwoStepVerification } from "./two-step";

let mfa: MfaOut = {
  ...sampleMyMfa,
  factors: [],
  required: true,
  policy: "required_local",
  recovery_codes_left: 0,
};
const handlers = [
  http.get(`${API}/me/mfa`, () => HttpResponse.json(mfa)),
  http.post(`${API}/me/mfa/totp/setup`, () =>
    HttpResponse.json({
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_uri:
        "otpauth://totp/Agnostic:daniel%40localhost.company?secret=JBSWY3DPEHPK3PXP&issuer=Agnostic",
    }),
  ),
];
const server = setupServer(...handlers);

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...handlers);
  mfa = { ...sampleMyMfa, factors: [], required: true, policy: "required_local", recovery_codes_left: 0 };
});
afterAll(() => {
  server.close();
});

describe("TwoStepVerification", () => {
  it("enrolls an authenticator app and shows the recovery codes once", async () => {
    let confirmBody: unknown;
    server.use(
      http.post(`${API}/me/mfa/totp/confirm`, async ({ request }) => {
        confirmBody = await request.json();
        mfa = { ...sampleMyMfa, required: true, policy: "required_local" };
        return HttpResponse.json({ factor: sampleMyMfa.factors[0], recovery_codes: sampleRecoveryCodes });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<TwoStepVerification />);
    expect(await screen.findByText("Your org requires two-step verification")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add authenticator app" }));
    const form = await screen.findByRole("form", { name: "Add an authenticator app" });
    expect(within(form).getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    expect(within(form).getByText(/^otpauth:\/\/totp\/Agnostic/)).toBeInTheDocument();
    await user.type(within(form).getByLabelText("Code from the app"), "123 456");
    await user.type(within(form).getByLabelText("Name (optional)"), "1Password");
    await user.click(within(form).getByRole("button", { name: "Turn on" }));

    const dialog = await screen.findByRole("dialog", { name: "Save your recovery codes" });
    expect(within(dialog).getByText(/7hq2-k9mx/)).toBeInTheDocument();
    expect(confirmBody).toEqual({ code: "123456", label: "1Password" });
    await user.click(within(dialog).getByRole("button", { name: "I've saved them" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(await screen.findByText("1Password")).toBeInTheDocument();
    // Required by the org and the only factor: it can't be removed.
    expect(screen.getByRole("button", { name: "Remove 1Password" })).toBeDisabled();
  });

  it("says why a wrong code didn't work", async () => {
    server.use(
      http.post(`${API}/me/mfa/totp/confirm`, () =>
        HttpResponse.json(
          {
            type: "x",
            title: "Wrong code",
            status: 422,
            code: "mfa_invalid",
            detail: "That code isn't right.",
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TwoStepVerification />);
    await user.click(await screen.findByRole("button", { name: "Add authenticator app" }));
    const form = await screen.findByRole("form", { name: "Add an authenticator app" });
    await user.type(within(form).getByLabelText("Code from the app"), "000000");
    await user.click(within(form).getByRole("button", { name: "Turn on" }));
    expect(await within(form).findByText("That code isn't right.")).toBeInTheDocument();
  });

  it("makes new recovery codes", async () => {
    mfa = sampleMyMfa;
    server.use(
      http.post(`${API}/me/mfa/recovery-codes`, () =>
        HttpResponse.json({ recovery_codes: sampleRecoveryCodes }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<TwoStepVerification />);
    expect(await screen.findByText("8 left")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Make new codes" }));
    expect(await screen.findByRole("dialog", { name: "Save your recovery codes" })).toBeInTheDocument();
  });
});
