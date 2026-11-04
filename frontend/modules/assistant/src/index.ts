import { defineModule } from "@agnostic/core";
import { SquareTerminal } from "lucide-react";

import { AskPage } from "./ask-page";

export const assistantModule = defineModule({
  id: "assistant",
  scope: "instance",
  requires: { features: ["assistant"], anyScope: ["assistant:use"] },
  routes: [{ path: "ask", component: AskPage }],
  nav: [{ id: "ask", group: "footer", label: "Ask your OS", icon: SquareTerminal, path: "ask", order: 20 }],
  commands: [
    {
      id: "assistant.ask",
      label: "Ask your OS",
      group: "Actions",
      keywords: ["ask", "assistant", "why", "question", "ai"],
      icon: SquareTerminal,
      path: "ask",
      withQuery: true,
    },
  ],
});
