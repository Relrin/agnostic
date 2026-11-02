import { defineModule } from "@agnostic/core";
import { Brain } from "lucide-react";

import { MemoryPage } from "./memory-page";

export const memoryModule = defineModule({
  id: "memory",
  scope: "instance",
  requires: { capabilities: ["memory"] },
  routes: [{ path: "memory", component: MemoryPage }],
  nav: [{ id: "memory", group: "context", label: "Memory", icon: Brain, path: "memory", order: 10 }],
});
