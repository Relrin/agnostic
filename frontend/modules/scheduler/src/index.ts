import { defineModule } from "@agnostic/core";
import { CalendarClock } from "lucide-react";

import { SchedulerPage } from "./scheduler-page";

export const schedulerModule = defineModule({
  id: "scheduler",
  scope: "instance",
  requires: { capabilities: ["scheduler"] },
  routes: [{ path: "scheduler", component: SchedulerPage }],
  nav: [
    {
      id: "scheduler",
      group: "control",
      label: "Scheduler",
      icon: CalendarClock,
      path: "scheduler",
      order: 20,
    },
  ],
});
