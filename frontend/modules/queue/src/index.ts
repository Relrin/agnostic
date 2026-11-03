import { defineModule } from "@agnostic/core";
import { ListOrdered } from "lucide-react";

import { QueuePage } from "./queue-page";

export const queueModule = defineModule({
  id: "queue",
  scope: "instance",
  requires: { capabilities: ["durable_queue"] },
  routes: [{ path: "queue", component: QueuePage }],
  nav: [{ id: "queue", group: "control", label: "Queue", icon: ListOrdered, path: "queue", order: 30 }],
});
