import { defineModule } from "@agnostic/core";
import { Building2 } from "lucide-react";

import { OrgSettingsPage } from "./org-settings-page";

/** Organization settings: sign-in (SSO, SAML, MFA), directory sync (SCIM, Google), audit retention, SIEM. */
export const orgSettingsModule = defineModule({
  id: "org-settings",
  scope: "org",
  routes: [
    { path: "org/settings", component: OrgSettingsPage },
    { path: "org/settings/$section", component: OrgSettingsPage },
  ],
  nav: [
    {
      id: "org-settings",
      group: "footer",
      label: "Organization",
      icon: Building2,
      path: "org/settings",
      order: 5,
    },
  ],
  requires: { anyScope: ["settings:read"] },
});

export { OrgSettingsPage };
