import { defineModule } from "@agnostic/core";
import { MessagesSquare } from "lucide-react";

import { SessionsPage } from "./sessions-page";

export const sessionsModule = defineModule({
  id: "sessions",
  scope: "instance",
  routes: [
    { path: "sessions", component: SessionsPage },
    { path: "sessions/$sessionId", component: SessionsPage },
  ],
  nav: [
    {
      id: "sessions",
      group: "observe",
      label: "Sessions",
      icon: MessagesSquare,
      path: "sessions",
      order: 10,
    },
  ],
});
