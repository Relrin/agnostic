// useCan / PermissionGate / WhyVisible: decisions come from /me/access; the server enforces them anyway,
// the UI only avoids offering what will be refused, and says why.
import type { MyAccessOut } from "@agnostic/api";
import { Tooltip } from "@agnostic/ui";
import { Info } from "lucide-react";
import type { ReactNode } from "react";

import { RequestAccessButton } from "./request-access";
import { useMyAccess } from "./session";

const ADMIN = "agent_os:admin";
const PER_COMPONENT = new Set(["agents", "teams", "workflows"]);
const ALIASES: Record<string, string> = { system: "config" };

function split(scope: string): [string, string | undefined, string] {
  const parts = scope.split(":");
  if (parts.length === 3) return [ALIASES[parts[0] ?? ""] ?? parts[0] ?? "", parts[1], parts[2] ?? ""];
  return [ALIASES[parts[0] ?? ""] ?? parts[0] ?? "", undefined, parts[1] ?? ""];
}

/** Same rules as the backend (agno scopes.py): admin passes AgentOS checks, global covers per-component. */
export function scopeSatisfies(held: string, required: string, controlPlane = false): boolean {
  if (held === required) return true;
  if (!controlPlane && held === ADMIN) return true;
  const [hResource, hId, hAction] = split(held);
  const [rResource, rId, rAction] = split(required);
  if (hResource !== rResource || hAction !== rAction) return false;
  if (controlPlane || !PER_COMPONENT.has(rResource)) return hId === rId;
  if (rId === undefined || rId === "*") return hId === undefined || hId === "*";
  return hId === undefined || hId === "*" || hId === rId;
}

export type Can = {
  /** `undefined` while access is loading. */
  allowed: boolean | undefined;
  /** "Granted by Operator", "Owner", or why not. */
  reason: string | undefined;
};

export function decide(access: MyAccessOut | undefined, scope: string): Can {
  if (!access) return { allowed: undefined, reason: undefined };
  const controlPlane = isControlPlaneScope(scope);
  const pool = controlPlane ? access.control_plane_scopes : access.runtime_scopes;
  const held = pool.find((candidate) => scopeSatisfies(candidate, scope, controlPlane));
  if (held === undefined) {
    return { allowed: false, reason: `Needs ${scope}.` };
  }
  const grant = access.grants.find((item) => item.scope === held);
  return { allowed: true, reason: grant ? `Granted by ${grant.role_name} → ${held}` : `You have ${held}` };
}

const CONTROL_PLANE_FAMILIES = new Set(["org", "os", "audit", "settings", "studio", "assistant", "queue"]);

export function isControlPlaneScope(scope: string): boolean {
  const [family, middle, action] = split(scope);
  if (CONTROL_PLANE_FAMILIES.has(family)) return true;
  return (family === "service_accounts" && action === "manage") || (family === "evals" && middle === "gates");
}

/** Can the signed-in person do `scope` (on `instance`, for AgentOS scopes)? */
export function useCan(scope: string, instance?: string): Can {
  const access = useMyAccess(isControlPlaneScope(scope) ? undefined : instance);
  return decide(access.data, scope);
}

/** Renders `children` only when allowed; `fallback` (e.g. a disabled button with a reason) otherwise. */
export function PermissionGate({
  scope,
  instance,
  children,
  fallback = null,
}: {
  scope: string;
  instance?: string;
  children: ReactNode;
  fallback?: ReactNode | ((reason: string | undefined) => ReactNode);
}) {
  const can = useCan(scope, instance);
  if (can.allowed === undefined) return null;
  if (can.allowed) return <>{children}</>;
  return <>{typeof fallback === "function" ? fallback(can.reason) : fallback}</>;
}

/**
 * A small (i) that says which grant makes something visible or available ("Granted by Operator → …"). When an
 * instance scope is denied it also offers "Request access" (temporary access, decided by approvers).
 */
export function WhyVisible({ scope, instance }: { scope: string; instance?: string }) {
  const can = useCan(scope, instance);
  if (!can.reason) return null;
  const info = (
    <Tooltip content={can.reason}>
      <button
        type="button"
        aria-label={`Why: ${can.reason}`}
        className="inline-grid size-5 cursor-help place-items-center rounded-full text-fg-muted hover:text-fg"
      >
        <Info className="size-3.5" aria-hidden />
      </button>
    </Tooltip>
  );
  if (can.allowed !== false || isControlPlaneScope(scope)) return info;
  return (
    <span className="inline-flex items-center gap-1">
      {info}
      <RequestAccessButton instance={instance} scopes={[scope]} />
    </span>
  );
}
