import type { MyAccessOut } from "@agnostic/api";
import { describe, expect, it } from "vitest";

import { defineModule, moduleAvailable } from "./module";
import { decide, isControlPlaneScope, scopeSatisfies } from "./permissions";

const operatorOnProd: MyAccessOut = {
  instance_id: "ins_prod",
  org_role: "member",
  implicit_full_access: false,
  roles: ["Operator"],
  token_scopes: ["agents:run", "sessions:read"],
  runtime_scopes: ["agents:read", "agents:run", "sessions:read", "approvals:write"],
  control_plane_scopes: ["org:read", "os:read"],
  grants: [
    {
      scope: "sessions:read",
      source: "binding",
      role_id: "rol_operator",
      role_name: "Operator",
      binding_id: "bnd_1",
      instance_id: "ins_prod",
      expires_at: null,
    },
  ],
};

describe("scopeSatisfies", () => {
  it("follows AgentOS semantics", () => {
    expect(scopeSatisfies("agents:run", "agents:triage:run")).toBe(true);
    expect(scopeSatisfies("agents:*:run", "agents:run")).toBe(true);
    expect(scopeSatisfies("agents:triage:run", "agents:run")).toBe(false);
    expect(scopeSatisfies("agent_os:admin", "sessions:delete")).toBe(true);
    expect(scopeSatisfies("system:read", "config:read")).toBe(true);
    expect(scopeSatisfies("agent_os:admin", "org:members:write", true)).toBe(false);
  });

  it("classifies control-plane scopes", () => {
    expect(isControlPlaneScope("org:members:write")).toBe(true);
    expect(isControlPlaneScope("os:keys:rotate")).toBe(true);
    expect(isControlPlaneScope("service_accounts:manage")).toBe(true);
    expect(isControlPlaneScope("service_accounts:read")).toBe(false);
    expect(isControlPlaneScope("sessions:delete")).toBe(false);
  });
});

describe("decide", () => {
  it("explains grants and gaps", () => {
    expect(decide(undefined, "sessions:read")).toEqual({ allowed: undefined, reason: undefined });
    expect(decide(operatorOnProd, "sessions:read")).toEqual({
      allowed: true,
      reason: "Granted by Operator → sessions:read",
    });
    expect(decide(operatorOnProd, "sessions:delete").allowed).toBe(false);
    expect(decide(operatorOnProd, "agents:billing:run").allowed).toBe(true);
    expect(decide(operatorOnProd, "org:members:write").allowed).toBe(false);
    expect(decide(operatorOnProd, "os:read").allowed).toBe(true);
  });
});

describe("moduleAvailable", () => {
  const approvals = defineModule({
    id: "approvals",
    scope: "instance",
    routes: [],
    requires: { capabilities: ["approvals"] },
  });

  it("hides modules whose capability is off on the instance", () => {
    expect(moduleAvailable(approvals, undefined)).toBe(true);
    expect(moduleAvailable(approvals, new Map([["approvals", "available"]]))).toBe(true);
    expect(moduleAvailable(approvals, new Map([["approvals", "disabled"]]))).toBe(false);
    expect(moduleAvailable(approvals, new Map())).toBe(true);
  });
});
