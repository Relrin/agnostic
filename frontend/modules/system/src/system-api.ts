// Hooks of the System page over the generated client.
import {
  systemDiscardJobMutation,
  systemListFailedJobsOptions,
  systemListFailedJobsQueryKey,
  systemRetryJobMutation,
  systemRunChecksMutation,
  systemSystemStatusOptions,
  systemSystemStatusQueryKey,
} from "@agnostic/api";
import { withQueryFn } from "@agnostic/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const REFRESH_MS = 15_000;

export function useSystemStatus() {
  return useQuery({ ...withQueryFn(systemSystemStatusOptions()), refetchInterval: REFRESH_MS });
}

export function useFailedJobs() {
  return useQuery({ ...withQueryFn(systemListFailedJobsOptions()), refetchInterval: REFRESH_MS });
}

export function useChecks() {
  return useMutation(systemRunChecksMutation());
}

function useRefresh() {
  const client = useQueryClient();
  return async () => {
    await client.invalidateQueries({ queryKey: systemListFailedJobsQueryKey() });
    await client.invalidateQueries({ queryKey: systemSystemStatusQueryKey() });
  };
}

export function useRetryJob() {
  const refresh = useRefresh();
  return useMutation({ ...systemRetryJobMutation(), onSuccess: refresh });
}

export function useDiscardJob() {
  const refresh = useRefresh();
  return useMutation({ ...systemDiscardJobMutation(), onSuccess: refresh });
}
