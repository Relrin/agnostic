// The Trusted Types policy the content security policy allows (`require-trusted-types-for 'script'`).
//
// The web app renders through React and has no HTML sinks of its own, so this "default" policy is the gate for
// whatever a dependency might do: inline scripts are refused, HTML only when it is one of the known constant style
// rules below or a string the app has just sanitized for a renderer that can only write HTML (`sanitizedHtml` in
// `@agnostic/core/trusted-html`, used by the notebook viewer), script URLs (workers, lazily loaded chunks) only from
// this origin or a blob created by the page. Import it before anything else.
import { acceptsHtml } from "@agnostic/core/trusted-html";

type ScriptUrlPolicy = {
  /** `type` and `sink` are passed to the default policy only: `"TrustedHTML"` and the sink, `"Element innerHTML"`. */
  createHTML: (input: string, type?: string, sink?: string) => string;
  createScript: (input: string) => string;
  createScriptURL: (input: string) => string;
};
type PolicyFactory = { createPolicy: (name: string, rules: ScriptUrlPolicy) => unknown };

export const TRUSTED_TYPES_POLICY = "default";

/**
 * The only HTML the web app's dependencies write: Radix's scroll-area and select inject these exact style rules
 * (hiding the native scrollbar). Anything else is refused; the CSP end-to-end run catches a new one.
 */
export const ALLOWED_HTML: ReadonlySet<string> = new Set(
  ["scroll-area", "select"].map(
    (part) =>
      `[data-radix-${part}-viewport]{scrollbar-width:none;-ms-overflow-style:none;-webkit-overflow-scrolling:touch;}` +
      `[data-radix-${part}-viewport]::-webkit-scrollbar{display:none}`,
  ),
);

export function allowedHtml(input: string, sink?: string): string {
  if (ALLOWED_HTML.has(input) || acceptsHtml(input, sink)) return input;
  throw new TypeError("HTML strings are refused by the Trusted Types policy; render elements instead.");
}

export function sameOriginScriptUrl(input: string, origin: string = window.location.origin): string {
  const url = new URL(input, origin);
  if (url.origin === origin || url.protocol === "blob:") return url.href;
  throw new TypeError(`Script URL ${url.href} isn't from this origin; refused by the Trusted Types policy.`);
}

export function installTrustedTypes(factory: PolicyFactory | undefined): void {
  if (!factory) return; // Browsers without Trusted Types: the content security policy still applies.
  factory.createPolicy(TRUSTED_TYPES_POLICY, {
    createHTML: (input, _type, sink) => allowedHtml(input, sink),
    createScript: () => {
      throw new TypeError("Inline scripts are refused by the Trusted Types policy.");
    },
    createScriptURL: (input) => sameOriginScriptUrl(input),
  });
}

installTrustedTypes((window as { trustedTypes?: PolicyFactory }).trustedTypes);
