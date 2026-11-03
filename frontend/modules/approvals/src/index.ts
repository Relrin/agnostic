import { defineModule } from "@agnostic/core";
import { BadgeCheck } from "lucide-react";

import { ApprovalsPage } from "./approvals-page";

export const approvalsModule = defineModule({
  id: "approvals",
  scope: "instance",
  requires: { capabilities: ["approvals"] },
  routes: [{ path: "approvals", component: ApprovalsPage }],
  nav: [
    { id: "approvals", group: "control", label: "Approvals", icon: BadgeCheck, path: "approvals", order: 10 },
  ],
});
