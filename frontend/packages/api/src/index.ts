// @agnostic/api: the generated client (do not edit src/generated; run `yarn api:gen`) plus small helpers.
import { client } from "./generated/client.gen";
import type { Problem } from "./generated/types.gen";

export * from "./generated";
export * from "./generated/@tanstack/react-query.gen";
export { client };

/** Point the client at the API. The web app is served same-origin, so the default base URL is "". */
export function configureApi(options: { baseUrl?: string } = {}): void {
  client.setConfig({ baseUrl: options.baseUrl ?? "", throwOnError: true });
}

/** RFC 9457 problem bodies returned by the control plane carry a stable `code`. */
export function isProblem(error: unknown): error is Problem {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    "status" in error &&
    typeof (error as { code: unknown }).code === "string"
  );
}

/** A one-line, human explanation of an API error for error states. */
export function describeError(error: unknown): { reason: string; requestId: string | undefined } {
  if (isProblem(error)) {
    return { reason: error.detail ?? error.title, requestId: error.request_id ?? undefined };
  }
  if (error instanceof Error) return { reason: error.message, requestId: undefined };
  return { reason: "The control plane didn't answer.", requestId: undefined };
}
