import { defineModule } from "@agnostic/core";
import { Boxes } from "lucide-react";

import { TeamEditorPage, TeamsPage } from "./teams-page";

export const studioTeamsModule = defineModule({
  id: "studio-teams",
  scope: "instance",
  requires: { capabilities: ["components"] },
  routes: [
    { path: "studio/teams", component: TeamsPage },
    { path: "studio/teams/$componentId", component: TeamEditorPage },
  ],
  nav: [{ id: "teams", group: "build", label: "Agent teams", icon: Boxes, path: "studio/teams", order: 20 }],
});
