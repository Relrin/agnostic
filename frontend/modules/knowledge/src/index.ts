import { defineModule } from "@agnostic/core";
import { BookOpen } from "lucide-react";

import { KnowledgePage } from "./knowledge-page";

export const knowledgeModule = defineModule({
  id: "knowledge",
  scope: "instance",
  requires: { capabilities: ["knowledge"] },
  routes: [{ path: "knowledge", component: KnowledgePage }],
  nav: [
    { id: "knowledge", group: "context", label: "Knowledge", icon: BookOpen, path: "knowledge", order: 20 },
  ],
});
