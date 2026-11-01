import { defineModule } from "@agnostic/core";
import { MessageSquare } from "lucide-react";

import { ChatPage } from "./chat-page";

export { chatPath } from "./chat-page";

export const chatModule = defineModule({
  id: "chat",
  scope: "instance",
  routes: [
    { path: "chat", component: ChatPage },
    { path: "chat/$kind", component: ChatPage },
    { path: "chat/$kind/$componentId", component: ChatPage },
    { path: "chat/$kind/$componentId/$sessionId", component: ChatPage },
  ],
  nav: [{ id: "chat", group: "main", label: "Chat", icon: MessageSquare, path: "chat", order: 20 }],
  commands: [
    {
      id: "chat.new",
      label: "New chat session",
      group: "Actions",
      keywords: ["chat", "run", "agent", "new session"],
      path: "chat",
    },
  ],
});
