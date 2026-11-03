import { defineModule } from "@agnostic/core";
import { ScrollText } from "lucide-react";

import { AuditPage } from "./audit-page";

/**
 * Audit log: every action and access decision with saved views, filters in the URL, an event aside (diff, why it
 * was denied, temporary access), CSV/JSONL export and the SIEM streaming status.
 */
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
