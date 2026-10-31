// Test helpers shared by modules and the app: render with providers, MSW handlers with sample data.
import { configureApi, type GreetingOut } from "@agnostic/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactElement } from "react";

export function renderWithProviders(ui: ReactElement): RenderResult & { queryClient: QueryClient } {
  configureApi({ baseUrl: "http://agnostic.test" });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
  return { ...result, queryClient };
}

export const API = "http://agnostic.test/api/v1";

export const sampleGreetings: GreetingOut[] = [
  {
    id: "hel_01M6A0EEZEQ373S26F20142FZ5",
    message: "Hi from Dana",
    status: "replied",
    reply: "Hello! You said: “Hi from Dana” (3 words).",
    created_at: "2026-10-31T09:12:00Z",
    updated_at: "2026-10-31T09:12:01Z",
  },
  {
    id: "hel_01M6A0EEZEQ373S26F20142FZ4",
    message: "Is the worker up?",
    status: "pending",
    reply: null,
    created_at: "2026-10-31T09:10:00Z",
    updated_at: "2026-10-31T09:10:00Z",
  },
];

/** MSW handlers for the hello endpoints; tests can override any of them with `server.use(...)`. */
export function helloHandlers(greetings: GreetingOut[] = sampleGreetings) {
  const store = [...greetings];
  return [
    http.get(`${API}/hello/greetings`, () => HttpResponse.json({ data: store, next_cursor: null })),
    http.post(`${API}/hello/greetings`, async ({ request }) => {
      const body = (await request.json()) as { message: string };
      const created: GreetingOut = {
        id: `hel_01M6A0EEZEQ373S26F20142F${String(store.length).padStart(2, "0")}`,
        message: body.message,
        status: "pending",
        reply: null,
        created_at: "2026-10-31T10:00:00Z",
        updated_at: "2026-10-31T10:00:00Z",
      };
      store.unshift(created);
      return HttpResponse.json(created, { status: 201 });
    }),
  ];
}
