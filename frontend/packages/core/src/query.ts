// TanStack Query defaults: short staleness for lists, no retries on client errors.
import { QueryClient, skipToken } from "@tanstack/react-query";

export const STALE_TIME = { config: 5 * 60_000, list: 15_000, live: 0 } as const;

/** Errors thrown by the generated client carry the problem body; 4xx are not worth retrying. */
function isClientError(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("status" in error)) return false;
  const status = error.status;
  return typeof status === "number" && status >= 400 && status < 500;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_TIME.list,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => !isClientError(error) && failureCount < 2,
      },
      mutations: { retry: false },
    },
  });
}

/**
 * Generated query options declare `queryFn` optional (exactOptionalPropertyTypes); it is always set. This makes
 * them directly usable with `useQuery`: `useQuery(withQueryFn(meGetMeOptions()))`.
 */
export function withQueryFn<T extends { queryFn?: unknown }>(
  options: T,
): Omit<T, "queryFn"> & { queryFn: NonNullable<T["queryFn"]> | typeof skipToken } {
  return {
    ...options,
    queryFn: options.queryFn ?? skipToken,
  };
}
