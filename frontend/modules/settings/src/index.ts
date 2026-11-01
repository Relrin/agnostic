import { defineModule } from "@agnostic/core";
import { Settings } from "lucide-react";

import { SettingsPage } from "./settings-page";

/** Instance settings: takes over the prototype's "Settings" footer entry. */
export const settingsModule = defineModule({
  id: "settings",
  scope: "instance",
  routes: [
    { path: "settings", component: SettingsPage },
    { path: "settings/$section", component: SettingsPage },
  ],
  nav: [{ id: "settings", group: "footer", label: "Settings", icon: Settings, path: "settings", order: 10 }],
  commands: [
    {
      id: "settings.keys",
      label: "Rotate the instance key pair",
      group: "Actions",
      keywords: ["jwt", "rotate"],
      path: "settings/authorization",
    },
    {
      id: "settings.test",
      label: "Test the instance connection",
      group: "Actions",
      keywords: ["health"],
      path: "settings/connection",
    },
  ],
});

export { SettingsPage };
