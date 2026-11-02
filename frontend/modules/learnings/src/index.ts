import { defineModule } from "@agnostic/core";
import { Lightbulb } from "lucide-react";

import { LearningsPage } from "./learnings-page";

export const learningsModule = defineModule({
  id: "learnings",
  scope: "instance",
  requires: { capabilities: ["learnings"] },
  routes: [{ path: "learnings", component: LearningsPage }],
  nav: [
    { id: "learnings", group: "context", label: "Learnings", icon: Lightbulb, path: "learnings", order: 30 },
  ],
});
