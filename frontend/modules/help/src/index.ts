import { defineModule } from "@agnostic/core";
import { LifeBuoy } from "lucide-react";

import { HelpPage } from "./help-page";

/** The guides bundled with this installation (admin, builder, operator, runbooks), rendered in the app. */
export const helpModule = defineModule({
  id: "help",
  scope: "org",
  routes: [
    { path: "help", component: HelpPage },
    { path: "help/$", component: HelpPage },
  ],
  nav: [{ id: "help", group: "footer", label: "Help", icon: LifeBuoy, path: "help", order: 7 }],
  commands: [
    { id: "help.open", label: "Open the guides", group: "Help", keywords: ["docs", "manual"], path: "help" },
  ],
});

export { HelpPage };
