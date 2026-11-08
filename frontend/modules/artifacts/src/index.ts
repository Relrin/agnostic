import { defineModule } from "@agnostic/core";
import { Files } from "lucide-react";

import { ArtifactsPage } from "./artifacts-page";
import { SharePage } from "./share-page";

/** Files agents produced on an instance (artefacts), their previews and share links. */
export const artifactsModule = defineModule({
  id: "artifacts",
  scope: "instance",
  requires: { capabilities: ["artifacts"] },
  routes: [{ path: "artifacts", component: ArtifactsPage }],
  nav: [{ id: "artifacts", group: "main", label: "Files", icon: Files, path: "artifacts", order: 30 }],
});

/** Share links: `/s/:token`, outside the signed-in shell. */
export const shareLinksModule = defineModule({
  id: "share-links",
  scope: "public",
  routes: [{ path: "s/$token", component: SharePage }],
});

export { ArtifactsPage, SharePage };
