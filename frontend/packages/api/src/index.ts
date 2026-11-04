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

// ---------------------------------------------------------------- direct mode

/** What the instance list says about how browsers reach a runtime. */
export type InstanceRoute = {
  id: string;
  slug: string;
  network_mode?: "gateway" | "direct";
  browser_url?: string;
};

type DirectToken = {
  token: string;
  baseUrl: string;
  expiresAt: number;
};

/** Refresh a direct-mode token this long before it expires. */
const TOKEN_REFRESH_MS = 30_000;
const directBases = new Map<string, string>();
const directTokens = new Map<string, Promise<DirectToken>>();

/** Remember which instances are in direct mode (the shell calls it whenever the instance list loads). */
export function setInstanceRoutes(instances: readonly InstanceRoute[]): void {
  directBases.clear();
  for (const instance of instances) {
    if (instance.network_mode === "direct" && instance.browser_url) {
      const base = instance.browser_url.replace(/\/+$/, "");
      directBases.set(instance.id, base);
      directBases.set(instance.slug, base);
    }
  }
}

async function fetchDirectToken(instance: string): Promise<DirectToken> {
  const response = await fetch(apiUrl(`/api/v1/instances/${encodeURIComponent(instance)}/token`), {
    method: "POST",
    headers: writeHeaders("POST"),
    credentials: "same-origin",
  });
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw isProblem(body) ? body : new AgentOSHttpError("POST", "token", response.status, undefined);
  }
  const token = body as { token: string; expires_at: string; base_url: string };
  return {
    token: token.token,
    baseUrl: token.base_url.replace(/\/+$/, ""),
    expiresAt: Date.parse(token.expires_at),
  };
}

async function directToken(instance: string, fresh = false): Promise<DirectToken> {
  const cached = fresh ? undefined : directTokens.get(instance);
  if (cached) {
    const token = await cached.catch(() => undefined);
    if (token && token.expiresAt - Date.now() > TOKEN_REFRESH_MS) return token;
  }
  const pending = fetchDirectToken(instance);
  directTokens.set(instance, pending);
  pending.catch(() => directTokens.delete(instance));
  return pending;
}

/** Where a call to an AgentOS route goes, and with what credentials. */
export type InstanceRequest = {
  url: string;
  headers: Headers;
  credentials: RequestCredentials;
  /** `true` when the browser calls the runtime itself (direct mode). */
  direct: boolean;
};

/**
 * Resolve an AgentOS route on `instance`: through the gateway (session cookie, CSRF), or straight to the runtime
 * with a short-lived token when the instance is in direct mode.
 */
export async function instanceRequest(
  instance: string,
  path: string,
  method = "GET",
  init?: HeadersInit,
  options: { freshToken?: boolean } = {},
): Promise<InstanceRequest> {
  const relative = path.replace(/^\/+/, "");
  if (!directBases.has(instance)) {
    return {
      url: gatewayUrl(instance, relative),
      headers: writeHeaders(method, init),
      credentials: "same-origin",
      direct: false,
    };
  }
  const token = await directToken(instance, options.freshToken);
  const headers = new Headers(init);
  headers.set("Authorization", `Bearer ${token.token}`);
  return { url: `${token.baseUrl}/${relative}`, headers, credentials: "omit", direct: true };
}

/**
 * Call an AgentOS route on an instance as the signed-in person: through the gateway (scoped JWT, audited), or
 * directly with a short-lived token in direct mode. Throws the problem body (403 `scope_missing` with an
 * explanation, 503 `capability_disabled`, …) or an `AgentOSHttpError` on errors.
 */
export async function gatewayFetch(
  instance: string,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  let target = await instanceRequest(instance, path, method, init.headers);
  let response = await fetch(target.url, {
    ...init,
    method,
    headers: target.headers,
    credentials: target.credentials,
  });
  if (target.direct && response.status === 401) {
    // The token expired or the runtime rotated keys: one retry with a fresh token.
    target = await instanceRequest(instance, path, method, init.headers, { freshToken: true });
    response = await fetch(target.url, {
      ...init,
      method,
      headers: target.headers,
      credentials: target.credentials,
    });
  }
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
