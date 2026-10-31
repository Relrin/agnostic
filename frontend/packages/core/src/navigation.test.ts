import { describe, expect, it } from "vitest";

import { defineModule } from "./module";
import { activeNavId, buildNavigation, collectCommands, scopedPath, type CatalogEntry } from "./navigation";

const Icon = () => null;

const catalog: CatalogEntry[] = [
  { id: "home", group: "main", label: "Home", icon: Icon, path: "home", order: 10, scope: "instance" },
  {
    id: "approvals",
    group: "control",
    label: "Approvals",
    icon: Icon,
    path: "approvals",
    order: 10,
    scope: "instance",
  },
  {
    id: "people",
    group: "access",
    label: "People & groups",
    icon: Icon,
    path: "access/people",
    order: 10,
    scope: "org",
  },
  {
    id: "settings",
    group: "footer",
    label: "Settings",
    icon: Icon,
    path: "settings",
    order: 10,
    scope: "instance",
  },
];

const hello = defineModule({
  id: "hello",
  scope: "instance",
  routes: [],
  nav: [{ id: "hello", group: "build", label: "Hello", icon: Icon, path: "hello", order: 5 }],
  commands: [{ id: "hello.open", label: "Open Hello", path: "hello" }],
});

describe("buildNavigation", () => {
  it("groups catalog and module entries in prototype order", () => {
    const nav = buildNavigation(catalog, [hello]);
    expect(nav.groups.map((g) => g.label)).toEqual([
      undefined,
      "Build",
      "Observe",
      "Context",
      "Control",
      "Access",
    ]);
    expect(nav.groups[1]?.items.map((i) => i.id)).toEqual(["hello"]);
    expect(nav.groups[1]?.items[0]?.moduleId).toBe("hello");
    expect(nav.groups[4]?.items[0]?.moduleId).toBeUndefined();
    expect(nav.footer.map((i) => i.id)).toEqual(["settings"]);
  });

  it("lets a module take over a catalog entry", () => {
    const approvals = defineModule({
      id: "approvals",
      scope: "instance",
      routes: [],
      nav: [{ id: "approvals", group: "control", label: "Approvals", icon: Icon, path: "approvals" }],
    });
    const nav = buildNavigation(catalog, [approvals]);
    const entry = nav.groups.find((g) => g.id === "control")?.items[0];
    expect(entry?.moduleId).toBe("approvals");
    expect(entry?.order).toBe(10);
  });
});

describe("paths", () => {
  it("scopes paths", () => {
    expect(scopedPath("instance", "/hello", "dev prod")).toBe("/i/dev%20prod/hello");
    expect(scopedPath("org", "access/people", "dev-prod")).toBe("/access/people");
  });

  it("finds the active entry by longest prefix", () => {
    const nav = buildNavigation(catalog, [hello]);
    expect(activeNavId(nav, "/i/dev-prod/hello", "dev-prod")).toBe("hello");
    expect(activeNavId(nav, "/i/dev-prod/hello/hel_1", "dev-prod")).toBe("hello");
    expect(activeNavId(nav, "/access/people", "dev-prod")).toBe("people");
    expect(activeNavId(nav, "/elsewhere", "dev-prod")).toBeUndefined();
  });

  it("collects commands with their module scope", () => {
    expect(collectCommands([hello])).toEqual([
      { id: "hello.open", label: "Open Hello", path: "hello", scope: "instance" },
    ]);
  });
});
