import { defineModule } from "@agnostic/core";
import { GitBranch } from "lucide-react";

import { SourcesPage } from "./sources-page";

export const sourcesModule = defineModule({
  id: "sources",
  scope: "instance",
  requires: { capabilities: ["components"] },
  routes: [{ path: "studio/sources", component: SourcesPage }],
  nav: [
    {
      id: "sources",
      group: "build",
      label: "Code sources",
      icon: GitBranch,
      path: "studio/sources",
      order: 50,
    },
  ],
  commands: [
    {
      id: "studio.sources",
      label: "Open code sources",
      group: "Go to",
      keywords: ["git", "repository", "github", "gitlab", "gitea", "pull request", "sync"],
      path: "studio/sources",
    },
  ],
});
