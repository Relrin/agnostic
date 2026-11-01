import { defineModule } from "@agnostic/core";
import { House } from "lucide-react";

import { HomePage } from "./home-page";

export const homeModule = defineModule({
  id: "home",
  scope: "instance",
  routes: [{ path: "home", component: HomePage }],
  nav: [{ id: "home", group: "main", label: "Home", icon: House, path: "home", order: 10 }],
});
