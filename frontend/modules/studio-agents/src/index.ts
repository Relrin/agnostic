import { defineModule } from "@agnostic/core";
import { Bot } from "lucide-react";

import { AgentEditorPage, AgentsPage } from "./agents-page";

export const studioAgentsModule = defineModule({
  id: "studio-agents",
  scope: "instance",
  requires: { capabilities: ["components"] },
  routes: [
    { path: "studio/agents", component: AgentsPage },
    { path: "studio/agents/$componentId", component: AgentEditorPage },
  ],
  nav: [{ id: "agents", group: "build", label: "Agents", icon: Bot, path: "studio/agents", order: 10 }],
  commands: [
    {
      id: "studio.agents",
      label: "Open Studio agents",
      group: "Go to",
      keywords: ["studio", "agent", "editor", "publish"],
      path: "studio/agents",
    },
  ],
});
