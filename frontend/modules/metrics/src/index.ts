import { defineModule } from "@agnostic/core";
import { ChartColumn } from "lucide-react";

import { MetricsPage } from "./metrics-page";

export const metricsModule = defineModule({
  id: "metrics",
  scope: "instance",
  routes: [{ path: "metrics", component: MetricsPage }],
  nav: [{ id: "metrics", group: "observe", label: "Metrics", icon: ChartColumn, path: "metrics", order: 30 }],
});
