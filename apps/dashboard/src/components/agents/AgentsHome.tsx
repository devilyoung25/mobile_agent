import { useEffect, useRef, useState } from "react"
import { useStreamContext as useAgentThreadStream } from "@langchain/react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import type { AgentThread, ImageChunk } from "@/lib/agents/types"
import type { CreateAgentThreadVariables } from "@/lib/agents/queries"
import type { ModelSelection } from "@/lib/agents/provider/useModelOptions"
import { AgentsApiError } from "@/lib/agents/api"
import { AgentPromptBar } from "@/components/agents/AgentPromptBar"
import { ModelCatalogPicker } from "@/components/agents/ModelCatalogPicker"
import {
  SELECTED_WORKSPACE_STORAGE_KEY,
  WORKSPACE_SELECTION_EVENT,
} from "@/components/agents/AgentsSidebar"
import { Logo } from "@/components/agents/ported/Logo"
import { agentThreadKeys, optimisticThread } from "@/lib/agents/queries"
import { useModelOptions } from "@/lib/agents/provider/useModelOptions"
import { useProfile, useRepos, useWorkspaces } from "@/lib/profile"
import { useSession } from "@/lib/session"

const WORKSPACE_NOT_AZURE_MESSAGE =
  "Solo puedes seleccionar repositorios de Azure DevOps como workspace. Este repositorio no apunta a Azure DevOps."

// Mirror of the backend Azure-host check (workspaces.py `_is_azure_devops_remote`).
function isAzureRemote(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    const host = new URL(url.includes("://") ? url : `ssh://${url}`).hostname.toLowerCase()
    return (
      host === "dev.azure.com" ||
      host === "ssh.dev.azure.com" ||
      host.endsWith(".visualstudio.com")
    )
  } catch {
    return /(?:^|@|\/\/)(?:ssh\.)?dev\.azure\.com|\.visualstudio\.com/i.test(url)
  }
}

// Friendly Spanish copy for the workspace prep errors the run-start can raise.
function workspaceRunErrorMessage(detail: string): string {
  const labels: Record<string, string> = {
    workspace_path_not_azure_repo: WORKSPACE_NOT_AZURE_MESSAGE,
    workspace_path_wrong_azure_org:
      "El repositorio pertenece a otra organización de Azure DevOps.",
    workspace_source_dirty:
      "Tu repositorio tiene cambios sin commitear. Haz commit o stash antes de iniciar.",
    workspace_integration_branch_missing:
      "No existe la rama de integración (develop) en origin. Verifica el remoto.",
    workspace_base_branch_required:
      "Tu repositorio está en HEAD desacoplado. Cambia a una rama nombrada.",
    workspace_integration_merge_conflict:
      "Tu rama tiene conflictos con develop. Resuélvelos antes de usar el workspace.",
  }
  return labels[detail] ?? "No se pudo preparar el workspace para esta corrida."
}

function promptContent(text: string, images: Array<ImageChunk>) {
  const trimmed = text.trim()
  const imageBlocks = images.map((image) => ({
    type: "image",
    base64: image.base64,
    mime_type: image.mimeType,
    ...(image.fileName ? { file_name: image.fileName } : {}),
  }))
  return [...imageBlocks, ...(trimmed ? [{ type: "text", text: trimmed }] : [])]
}

export function AgentsHome() {
  // Submit straight through the layout's persistent stream. The SDK mints the
  // thread id (no client-minted id, no `getState` 404), fires the first
  // `run.start` — which lazily creates + stamps + owns the thread server-side
  // — and keeps streaming after we navigate to the minted thread below.
  const stream = useAgentThreadStream()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { models, defaultSelection } = useModelOptions()
  const [selection, setSelection] = useState<ModelSelection | null>(null)
  const activeSelection = selection ?? defaultSelection
  const [submitting, setSubmitting] = useState(false)

  const reposQuery = useRepos()
  const profileQuery = useProfile()
  const workspacesQuery = useWorkspaces()
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    () =>
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(SELECTED_WORKSPACE_STORAGE_KEY)
  )
  const selectedWorkspace = workspacesQuery.data?.workspaces.find(
    (workspace) => workspace.id === selectedWorkspaceId
  )
  // undefined = untouched (fall back to the profile default); null = explicitly "no repo".
  const [repoOverride, setRepoOverride] = useState<string | null | undefined>(
    undefined
  )
  // How the agent's isolated worktree is based. "integration": fresh branch from
  // origin/develop. "local_branch": the dev's branch with develop merged in.
  const [baseMode, setBaseMode] = useState<"integration" | "local_branch">(
    "integration"
  )
  const session = useSession()
  const allowNonAzure = session.data?.allow_nonazure_workspace ?? false
  const [composeError, setComposeError] = useState<string | null>(null)
  // Azure DevOps-first: a non-Azure workspace can't start a run unless the gate
  // is relaxed server-side. Surfaced proactively so the user isn't left hanging.
  const workspaceNotAzure =
    !!selectedWorkspace &&
    !allowNonAzure &&
    !isAzureRemote(selectedWorkspace.remote_url)
  const repo =
    selectedWorkspace
      ? null
      : repoOverride === undefined
      ? (profileQuery.data?.default_repo ?? null)
      : repoOverride

  // Holds the just-submitted prompt until the SDK mints the thread id; the
  // effect then seeds the optimistic summary and navigates exactly once.
  const draftRef = useRef<CreateAgentThreadVariables | null>(null)

  useEffect(() => {
    const syncSelectedWorkspace = () => {
      setSelectedWorkspaceId(
        window.localStorage.getItem(SELECTED_WORKSPACE_STORAGE_KEY)
      )
    }
    window.addEventListener(WORKSPACE_SELECTION_EVENT, syncSelectedWorkspace)
    window.addEventListener("storage", syncSelectedWorkspace)
    return () => {
      window.removeEventListener(WORKSPACE_SELECTION_EVENT, syncSelectedWorkspace)
      window.removeEventListener("storage", syncSelectedWorkspace)
    }
  }, [])

  useEffect(() => {
    const id = stream.threadId
    const draft = draftRef.current
    if (!id || !draft) return
    draftRef.current = null
    const thread = optimisticThread(id, draft)
    queryClient.setQueryData(agentThreadKeys.detail(id), thread)
    // Surface the thread in the sidebar immediately; the list's running
    // refetch reconciles to server truth once the run.start stamps it.
    queryClient.setQueryData<Array<AgentThread>>(agentThreadKeys.all, (prev) => [
      thread,
      ...(prev?.filter((existing) => existing.id !== id) ?? []),
    ])
    void navigate({ to: "/agents/$threadId", params: { threadId: id } })
  }, [stream.threadId, queryClient, navigate])

  const handleSubmit = (prompt: string, images: Array<ImageChunk>) => {
    if (workspaceNotAzure) {
      setComposeError(WORKSPACE_NOT_AZURE_MESSAGE)
      return
    }
    setComposeError(null)
    draftRef.current = {
      prompt,
      images,
      repo,
      repo_explicitly_none: selectedWorkspace ? true : repoOverride === null,
      workspace_id: selectedWorkspace?.id ?? null,
      workspace_label: selectedWorkspace?.label ?? null,
      model_id: activeSelection?.modelId ?? null,
      effort: activeSelection?.effort ?? null,
    }
    setSubmitting(true)

    const configurable: Record<string, unknown> = {}
    if (activeSelection?.modelId && activeSelection.effort) {
      configurable.agent_model_id = activeSelection.modelId
      configurable.agent_effort = activeSelection.effort
    }
    if (!selectedWorkspace && repo) configurable.repo = repo
    if (selectedWorkspace || repoOverride === null) {
      configurable.repo_explicitly_none = true
    }
    if (selectedWorkspace?.id) {
      configurable.workspace_id = selectedWorkspace.id
      configurable.base_mode = baseMode
    }

    stream
      .submit(
        { messages: [{ type: "human", content: promptContent(prompt, images) }] },
        { config: { configurable } }
      )
      .catch((err: unknown) => {
        // Run-start failed (e.g. workspace prep 422/409). Surface it instead of
        // leaving the thread hanging on a loading state.
        const detail = err instanceof AgentsApiError ? err.message : ""
        const message = detail.startsWith("workspace")
          ? workspaceRunErrorMessage(detail)
          : "No se pudo iniciar la corrida. Intenta de nuevo."
        const id = stream.threadId
        if (id) {
          queryClient.setQueryData<AgentThread>(agentThreadKeys.detail(id), (prev) =>
            prev ? { ...prev, status: "error", errorMessage: message } : prev
          )
        }
        setComposeError(message)
        draftRef.current = null
        setSubmitting(false)
      })
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-y-auto px-6 py-8">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col items-center justify-center">
        <div className="flex w-full flex-col items-center gap-6">
          <Logo />
          {selectedWorkspace && (
            <div className="flex flex-col items-center gap-2">
              <div className="flex max-w-full items-center gap-2 rounded-full border border-[var(--ui-border)] bg-[var(--ui-panel)] px-3 py-1 text-xs text-[var(--ui-text-muted)]">
                <span className="min-w-0 truncate">{selectedWorkspace.label}</span>
                {selectedWorkspace.current_branch && (
                  <span className="rounded bg-[var(--ui-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--ui-text-dim)]">
                    {selectedWorkspace.current_branch}
                  </span>
                )}
              </div>
              {workspaceNotAzure ? (
                <p className="max-w-md text-center text-[11px] text-amber-400">
                  Solo repositorios de Azure DevOps. Este workspace no apunta a
                  Azure y no puede iniciar una corrida.
                </p>
              ) : (
                <div className="flex items-center gap-1 rounded-full border border-[var(--ui-border)] bg-[var(--ui-panel-2)] p-0.5 text-[11px]">
                  {(
                    [
                      ["integration", "Rama nueva desde develop"],
                      ["local_branch", "Sobre mi rama (con develop)"],
                    ] as const
                  ).map(([mode, label]) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setBaseMode(mode)}
                      className={
                        baseMode === mode
                          ? "rounded-full bg-[var(--ui-accent)]/20 px-2.5 py-1 font-medium text-[color:var(--ui-text)]"
                          : "rounded-full px-2.5 py-1 text-[color:var(--ui-text-muted)] hover:text-[color:var(--ui-text)]"
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <ModelCatalogPicker
            selectedModelId={activeSelection?.modelId ?? null}
            onSelect={(modelId, defaultEffort) =>
              setSelection({
                modelId,
                effort: defaultEffort ?? activeSelection?.effort ?? "medium",
              })
            }
          />
          <AgentPromptBar
            onSubmit={handleSubmit}
            disabled={submitting}
            models={models}
            selection={activeSelection}
            onSelectionChange={setSelection}
            repos={selectedWorkspace ? undefined : reposQuery.data?.repositories}
            selectedRepo={selectedWorkspace ? null : repo}
            onRepoChange={selectedWorkspace ? undefined : setRepoOverride}
          />
          {composeError && (
            <div className="w-full max-w-2xl rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {composeError}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
