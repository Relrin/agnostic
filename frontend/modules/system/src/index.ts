import { defineModule } from "@agnostic/core";
import { Activity } from "lucide-react";

import { SystemPage } from "./system-page";

/** The control plane itself: versions, endpoints, job queues and failed jobs, delivery backlogs, instance polling. */
export const systemModule = defineModule({
  id: "system",
  scope: "org",
  routes: [{ path: "org/system", component: SystemPage }],
  nav: [
    {
      id: "system",
      group: "footer",
      label: "System",
      icon: Activity,
      path: "org/system",
      order: 6,
    },
  ],
  requires: { anyScope: ["org:system:read"] },
});

export { SystemPage };
