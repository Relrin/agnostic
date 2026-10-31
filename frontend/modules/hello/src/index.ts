import { defineModule } from "@agnostic/core";
import { Hand } from "lucide-react";

import { HelloPage } from "./hello-page";

/** The hello module: one page under the active instance, a nav entry and a palette command. */
export const helloModule = defineModule({
  id: "hello",
  scope: "instance",
  routes: [{ path: "hello", component: HelloPage }],
  nav: [{ id: "hello", group: "main", label: "Hello", icon: Hand, path: "hello", order: 30 }],
  commands: [
    {
      id: "hello.open",
      label: "Open Hello",
      group: "Pages",
      keywords: ["greeting", "sample"],
      path: "hello",
    },
  ],
});

export { HelloPage };
