import { defineModule } from "@agnostic/core";
import { ScrollText } from "lucide-react";

import { AuditPage } from "./audit-page";

/** Audit log (basic, P01): table and detail aside. Saved views and SIEM streaming arrive in P06. */
export const auditModule = defineModule({
  id: "audit",
  scope: "org",
  routes: [{ path: "access/audit", component: AuditPage }],
  nav: [
    { id: "audit", group: "access", label: "Audit log", icon: ScrollText, path: "access/audit", order: 40 },
  ],
  requires: { anyScope: ["audit:read"] },
});

export { AuditPage };
