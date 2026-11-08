// A narrow way through the Trusted Types policy for HTML the app itself has just sanitized.
//
// The web app's default policy refuses HTML strings. Some renderers (the notebook viewer) can only hand over HTML
// as strings, so they sanitize it first and register the result here; the policy then accepts exactly that string,
// once. While a sanitizer runs, the policy also accepts the parse into an inert document the sanitizer makes of
// its input: nothing parsed there runs or reaches the page. The module has no imports, so the policy can load it
// before anything else.

/** Sanitized strings waiting for the sink they were made for, with how many times each may still be written. */
const pending = new Map<string, number>();

/** Written strings are consumed as they land; an abandoned one is dropped once this many wait. */
const MAX_PENDING = 256;

let sanitizing = 0;

/** The sink a sanitizer parses its input with: `DOMParser.parseFromString`, into a document that runs nothing. */
const INERT_PARSE = /^DOMParser[ .]parseFromString$/;

function remember(html: string): void {
  pending.set(html, (pending.get(html) ?? 0) + 1);
  while (pending.size > MAX_PENDING) {
    const oldest = pending.keys().next();
    if (oldest.done) break;
    pending.delete(oldest.value);
  }
}

/**
 * Run `sanitize` over `input` and let the Trusted Types policy accept its result once. `sanitize` must be
 * synchronous and must strip anything that runs (scripts, event handlers, `javascript:` URLs).
 */
export function sanitizedHtml(input: string, sanitize: (dirty: string) => string): string {
  sanitizing += 1;
  let html: string;
  try {
    html = sanitize(input);
  } finally {
    sanitizing -= 1;
  }
  remember(html);
  return html;
}

/**
 * Whether the policy should accept `input` written to `sink`: a parse a running sanitizer makes, or a string
 * `sanitizedHtml` produced and nothing has written yet (consumed by this call).
 */
export function acceptsHtml(input: string, sink?: string): boolean {
  if (sanitizing > 0 && sink !== undefined && INERT_PARSE.test(sink)) return true;
  const left = pending.get(input);
  if (left === undefined) return false;
  if (left > 1) pending.set(input, left - 1);
  else pending.delete(input);
  return true;
}

/** Forget every waiting string (tests). */
export function clearSanitizedHtml(): void {
  pending.clear();
}
