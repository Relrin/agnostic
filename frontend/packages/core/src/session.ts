// Who is signed in, the org, the instances and the signed-in person's access: the server state every page
// and the shell share (query keys namespaced ["org", …] and [instance, …]).
import {
  instancesGetHealthOptions,
  instancesListInstancesOptions,
  meGetMeOptions,
  meMyAccessOptions,
  orgGetOrgOptions,
  setInstanceRoutes,
  systemListFeaturesOptions,
  systemListModulesOptions,
  type HealthOut,
  type InstanceOut,
  type MeOut,
  type MyAccessOut,
  type OrgOut,
} from "@agnostic/api";
import { skipToken, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { STALE_TIME } from "./query";

export function useMe() {
  const options = meGetMeOptions();
  return useQuery({
    ...options,
    queryFn: options.queryFn ?? skipToken,
    staleTime: STALE_TIME.list,
    retry: false,
  });
}

export function useOrg() {
  const options = orgGetOrgOptions();
  return useQuery({ ...options, queryFn: options.queryFn ?? skipToken, staleTime: STALE_TIME.config });
}

export function useInstances() {
  const options = instancesListInstancesOptions();
  const query = useQuery({ ...options, queryFn: options.queryFn ?? skipToken, staleTime: STALE_TIME.list });
  useEffect(() => {
    // Direct-mode instances are called from the browser itself: tell the API client which ones.
    if (query.data) setInstanceRoutes(query.data);
  }, [query.data]);
  return query;
}

/** Effective access on an instance (or org-wide when `instance` is undefined); invalidated on access changes. */
export function useMyAccess(instance?: string) {
  const options = meMyAccessOptions(instance ? { query: { instance } } : {});
  return useQuery({ ...options, queryFn: options.queryFn ?? skipToken, staleTime: STALE_TIME.list });
}

/** Control-plane features switched on right now (`{"assistant": true, …}`); missing means off. */
export function useFeatures() {
  const options = systemListFeaturesOptions();
  return useQuery({
    ...options,
    queryFn: options.queryFn ?? skipToken,
    staleTime: STALE_TIME.list,
    select: (data) => data.features,
  });
}

/** Whether a backend module is installed and enabled (for settings pages that exist even when a feature is off). */
export function useModuleEnabled(name: string): boolean | undefined {
  const options = systemListModulesOptions();
  const modules = useQuery({
    ...options,
    queryFn: options.queryFn ?? skipToken,
    staleTime: STALE_TIME.config,
  });
  return modules.data ? modules.data.enabled.some((module) => module.name === name) : undefined;
}

export function useInstanceHealth(instance: string | undefined) {
  const options = instancesGetHealthOptions({ path: { instance: instance ?? "" } });
  return useQuery({
    ...options,
    queryFn: instance ? (options.queryFn ?? skipToken) : skipToken,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export type { HealthOut, InstanceOut, MeOut, MyAccessOut, OrgOut };

/** "dev-prod" or "ins_01…" → the instance record. */
export function findInstance(
  instances: readonly InstanceOut[] | undefined,
  ref: string | undefined,
): InstanceOut | undefined {
  if (!ref) return undefined;
  return instances?.find((instance) => instance.slug === ref || instance.id === ref);
}

export const ORG_ROLE_LABELS: Record<NonNullable<MeOut["org_role"]>, string> = {
  owner: "Owner",
  administrator: "Administrator",
  member: "Member",
};
