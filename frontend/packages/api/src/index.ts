// @agnostic/api: the generated client (do not edit src/generated; run `yarn api:gen`) plus small helpers.
import { client } from "./generated/client.gen";
import type { Problem } from "./generated/types.gen";

export * from "./generated";
export * from "./generated/@tanstack/react-query.gen";
export { client };
/** AgentOS response and request types (generated from the pinned AgentOS OpenAPI; called through the gateway). */
export type * as AgentOS from "./agentos";

const CSRF_COOKIE = "agnostic_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** The double-submit CSRF token the API sets next to the session cookie (readable by design). */
export function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  for (const part of document.cookie.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(value.join("="));
  }
  return undefined;
}

let configuredBaseUrl = "";
let interceptorInstalled = false;

/** Point the client at the API. The web app is served same-origin, so the default base URL is "". */
export function configureApi(options: { baseUrl?: string } = {}): void {
  configuredBaseUrl = options.baseUrl ?? "";
  client.setConfig({ baseUrl: configuredBaseUrl, throwOnError: true, credentials: "same-origin" });
  if (!interceptorInstalled) {
    interceptorInstalled = true;
    client.interceptors.request.use((request) => {
      const token = csrfToken();
      if (token && !SAFE_METHODS.has(request.method.toUpperCase())) request.headers.set(CSRF_HEADER, token);
      return request;
    });
  }
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

/** Problems carry extra fields per code, e.g. `explanation` and `missing_scopes` on `scope_missing`. */
export type ProblemDetails = Problem & {
  explanation?: string;
  required_scopes?: string[];
  missing_scopes?: string[];
  steps?: { id: string; label: string; status: string; detail: string; hint: string | null }[];
  field?: string;
};

/** A one-line, human explanation of an API error for error states. */
export function describeError(error: unknown): { reason: string; requestId: string | undefined } {
  if (isProblem(error)) {
    const details = error as ProblemDetails;
    return {
      reason: details.explanation ?? error.detail ?? error.title,
      requestId: error.request_id ?? undefined,
    };
  }
  if (error instanceof Error) return { reason: error.message, requestId: undefined };
  return { reason: "The control plane didn't answer.", requestId: undefined };
}

export function problemCode(error: unknown): string | undefined {
  return isProblem(error) ? error.code : undefined;
}

/** An AgentOS error passed through the gateway as it is (`{detail}` bodies, e.g. 404 under user isolation). */
export class AgentOSHttpError extends Error {
  readonly status: number;
  readonly detail: string | undefined;

  constructor(method: string, path: string, status: number, detail: string | undefined) {
    super(detail ?? `${method} ${path}: HTTP ${String(status)}`);
    this.name = "AgentOSHttpError";
    this.status = status;
    this.detail = detail;
  }
}

/** Absolute API URL for paths the generated client doesn't cover (SSE streams). */
export function apiUrl(path: string): string {
  return `${configuredBaseUrl}${path}`;
}

/** The gateway URL of an AgentOS route on `instance`. */
export function gatewayUrl(instance: string, path: string): string {
  return apiUrl(`/api/v1/instances/${encodeURIComponent(instance)}/os/${path.replace(/^\/+/, "")}`);
}

/** Headers for a non-generated call: the CSRF token on writes. */
export function writeHeaders(method: string, init?: HeadersInit): Headers {
  const headers = new Headers(init);
  const token = csrfToken();
  if (token && !SAFE_METHODS.has(method.toUpperCase())) headers.set(CSRF_HEADER, token);
  return headers;
}

/**
 * Call an AgentOS route on an instance through the gateway, as the signed-in person (scoped JWT, audited).
 * Throws the problem body (403 `scope_missing` with an explanation, 503 `capability_disabled`, …) on errors.
 */
export async function gatewayFetch(
  instance: string,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = writeHeaders(method, init.headers);
  const response = await fetch(gatewayUrl(instance, path), {
    ...init,
    method,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    let body: unknown = undefined;
    try {
      body = await response.json();
    } catch {
      // Not JSON (AgentOS passthrough errors are returned as they are).
    }
    if (isProblem(body)) {
      // Problems are thrown as plain bodies, like the generated client does, so `describeError` handles both.
      // eslint-disable-next-line @typescript-eslint/only-throw-error
      throw body;
    }
    const detail =
      typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : undefined;
    throw new AgentOSHttpError(method, path, response.status, detail);
  }
  return response;
}

/** `gatewayFetch` + JSON (or `undefined` for 204). */
export async function gatewayJson<T>(instance: string, path: string, init: RequestInit = {}): Promise<T> {
  const response = await gatewayFetch(instance, path, init);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A JSON body for `gatewayFetch` writes. */
export function jsonBody(value: unknown): RequestInit {
  return { body: JSON.stringify(value), headers: { "Content-Type": "application/json" } };
}
