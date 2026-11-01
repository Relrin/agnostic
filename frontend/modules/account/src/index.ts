import { defineModule } from "@agnostic/core";
import { UserRound } from "lucide-react";

import { AccountPage } from "./account-page";

/** Account: reached from the sidebar's account button and the palette. */
export const accountModule = defineModule({
  id: "account",
  scope: "org",
  routes: [{ path: "account", component: AccountPage }],
  commands: [
    {
      id: "account.open",
      label: "Your account",
      group: "Pages",
      keywords: ["profile", "sign out"],
      icon: UserRound,
      path: "account",
    },
  ],
});

export { AccountPage };
