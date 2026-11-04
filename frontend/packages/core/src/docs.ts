// Links to the user guides bundled with the installation (served by the API, rendered at /help, works offline).

/** The in-product help page of a guide, e.g. `docsLink("admin/direct-mode.md")` → `/help/admin/direct-mode.md`. */
export function docsLink(path: string, label?: string): { href: string; label?: string } {
  const href = `/help/${path.replace(/^\/+/, "")}`;
  return label === undefined ? { href } : { href, label };
}

/** Resolve a link inside a guide (`../runbooks/x.md#step`) against the guide's own path. */
export function resolveGuideLink(from: string, href: string): string | undefined {
  if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//") || href.startsWith("#")) return undefined;
  const [target = "", anchor] = href.split("#", 2);
  if (!target.endsWith(".md")) return undefined;
  const parts = from.split("/").slice(0, -1);
  for (const segment of target.split("/")) {
    if (segment === "..") parts.pop();
    else if (segment !== "." && segment !== "") parts.push(segment);
  }
  return `/help/${parts.join("/")}${anchor ? `#${anchor}` : ""}`;
}
