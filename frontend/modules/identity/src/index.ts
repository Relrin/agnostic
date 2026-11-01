import { defineModule } from "@agnostic/core";

import { InvitePage } from "./invite-page";
import { LoginPage } from "./login-page";
import { OnboardingPage } from "./onboarding-page";
import { ResetPasswordPage } from "./reset-password-page";

/** Public pages outside the signed-in shell: sign-in, first run, invitations, password reset. */
export const identityModule = defineModule({
  id: "identity",
  scope: "public",
  routes: [
    { path: "login", component: LoginPage },
    { path: "onboarding", component: OnboardingPage },
    { path: "invite/$token", component: InvitePage },
    { path: "reset-password", component: ResetPasswordPage },
  ],
});

export { InvitePage, LoginPage, OnboardingPage, ResetPasswordPage };
