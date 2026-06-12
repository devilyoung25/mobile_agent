import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "./api"
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
  // The GitHub-backed /repos endpoint was removed in the Azure DevOps migration.
  // Return an empty set so repo pickers render cleanly without 404-ing on load;
  // Azure DevOps repositories will be wired through the MCP toolset later.
  return useQuery({
    queryKey: ["repos"],
    queryFn: () => ({ installations: [], repositories: [] }),
    staleTime: Infinity,
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
