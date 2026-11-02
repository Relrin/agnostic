import { defineModule } from "@agnostic/core";
import { Target } from "lucide-react";

import { EvalsPage } from "./evals-page";

export const evalsModule = defineModule({
  id: "evals",
  scope: "instance",
  routes: [{ path: "evals", component: EvalsPage }],
  nav: [{ id: "evals", group: "observe", label: "Evaluations", icon: Target, path: "evals", order: 40 }],
});
