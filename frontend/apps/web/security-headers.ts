// The headers the API sends with the web app in production (agnostic_kernel.security_headers), used by
// `vite preview` so the CSP end-to-end run (`yarn e2e:csp`) exercises the real policy. A backend test keeps the
// two in sync.

export const CONTENT_SECURITY_POLICY =
  "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; manifest-src 'self'; require-trusted-types-for 'script'; trusted-types default";

export const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy": CONTENT_SECURITY_POLICY,
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
};
