import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { ApiError, api } from "./api"
import { useSession } from "./session"
import type { Profile, ProfileUpdate } from "./api"

export function useProfile() {
  const session = useSession()
  return useQuery({
    queryKey: ["profile"],
    queryFn: api.profile,
    enabled: !!session.data,
  })
}

export function useOptions() {
  const session = useSession()
  return useQuery({
    queryKey: ["options"],
    queryFn: api.options,
    enabled: !!session.data,
  })
}

export function useRepos() {
  // Live Azure DevOps repositories for the signed-in user. When they haven't
  // consented to Azure DevOps yet, the API answers 403 — degrade to an empty
  // picker instead of surfacing an error.
  const session = useSession()
  return useQuery({
    queryKey: ["repos"],
    queryFn: async () => {
      try {
        return await api.repos()
      } catch (e) {
        if (e instanceof ApiError && (e.status === 403 || e.status === 401))
          return { repositories: [] }
        throw e
      }
    },
    enabled: !!session.data,
    staleTime: 5 * 60 * 1000,
  })
}

export function useWorkspaces() {
  const session = useSession()
  return useQuery({
    queryKey: ["workspaces"],
    queryFn: api.workspaces,
    enabled: !!session.data,
  })
}

export function usePickWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.pickWorkspace,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workspaces"] })
    },
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfileUpdate) => api.saveProfile(body),
    onSuccess: (saved) => {
      qc.setQueryData(["profile"], saved)
    },
  })
}

/**
 * Build a ProfileUpdate body from the current cached profile plus a patch,
 * so individual pages can mutate one field without losing values managed by
 * other pages.
 */
export function buildProfileUpdate(
  current: Profile | undefined,
  patch: Partial<ProfileUpdate>,
  fallbackModel: string,
  fallbackEffort: string
): ProfileUpdate {
  return {
    default_model: current?.default_model ?? fallbackModel,
    reasoning_effort: current?.reasoning_effort ?? fallbackEffort,
    default_subagent_model:
      current?.default_subagent_model ?? current?.default_model ?? fallbackModel,
    subagent_reasoning_effort:
      current?.subagent_reasoning_effort ?? current?.reasoning_effort ?? fallbackEffort,
    default_repo: current?.default_repo ?? null,
    base_branch: current?.base_branch ?? null,
    branch_prefix: current?.branch_prefix ?? null,
    auto_fix_ci: current?.auto_fix_ci ?? true,
    create_prs: current?.create_prs ?? false,
    review_draft_prs: current?.review_draft_prs ?? null,
    ...patch,
  }
}
