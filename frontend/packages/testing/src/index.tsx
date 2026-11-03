// Test helpers shared by modules and the app: render with providers, MSW handlers with the prototype's sample org.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";

import { API, configureTestApi } from "./base";

export { API, configureTestApi };
export * from "./p01";
export * from "./studio-workflows";
export * from "./p02";
export * from "./observe";
export * from "./context";
export * from "./approvals";
export * from "./scheduler";
export * from "./queue";
export * from "./notifications";
export * from "./people-groups";
export * from "./roles";
export * from "./service-accounts";
export * from "./audit-governance";
export * from "./org-settings";
export * from "./studio";

export function renderWithProviders(ui: ReactElement): RenderResult & { queryClient: QueryClient } {
  configureTestApi();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
  return { ...result, queryClient };
}
