import { defineModule } from "@agnostic/core";
import { KeySquare } from "lucide-react";

import { ServiceAccountsPage } from "./service-accounts-page";

/** Service accounts: machine identities (`sa:<name>`) with native tokens per instance and gateway tokens. */
export const serviceAccountsModule = defineModule({
  id: "service-accounts",
  scope: "org",
  routes: [{ path: "access/service-accounts", component: ServiceAccountsPage }],
  nav: [
    {
      id: "tokens",
      group: "access",
      label: "Service accounts",
      icon: KeySquare,
      path: "access/service-accounts",
      order: 30,
    },
  ],
  requires: { anyScope: ["org:read"] },
});

export { ServiceAccountsPage };
