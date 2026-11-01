import { defineModule } from "@agnostic/core";
import { Plus, Server } from "lucide-react";

import { ConnectWizard } from "./connect-wizard";
import { InstancesPage } from "./instances-page";

/** Instances: the list and the Connect wizard (org-wide pages). */
export const instancesModule = defineModule({
  id: "instances",
  scope: "org",
  routes: [
    { path: "instances", component: InstancesPage },
    { path: "instances/connect", component: ConnectWizard },
  ],
  commands: [
    {
      id: "instances.open",
      label: "Instances",
      group: "Pages",
      keywords: ["agentos", "runtime"],
      icon: Server,
      path: "instances",
    },
    {
      id: "instances.connect",
      label: "Connect an instance",
      group: "Actions",
      icon: Plus,
      path: "instances/connect",
    },
  ],
});

export { ConnectWizard, InstancesPage };
