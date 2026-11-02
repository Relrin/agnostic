import { defineModule } from "@agnostic/core";
import { ChartGantt } from "lucide-react";

import { TracesPage } from "./traces-page";

export const tracesModule = defineModule({
  id: "traces",
  scope: "instance",
  routes: [
    { path: "traces", component: TracesPage },
    { path: "traces/$traceId", component: TracesPage },
  ],
  nav: [{ id: "traces", group: "observe", label: "Traces", icon: ChartGantt, path: "traces", order: 20 }],
});

export { buildTraceFilter, type FilterExpr, type TraceFilters } from "./build-filter";
