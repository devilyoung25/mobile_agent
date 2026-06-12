import { Link, Navigate, createFileRoute } from "@tanstack/react-router"
import { CaretRightIcon } from "@phosphor-icons/react"
import { useEffect, useRef, useState } from "react"

import type { ModelOption } from "@/lib/api"
import { AppShell, SettingsRow, SettingsSection } from "@/components/AppShell"
import { Button } from "@/components/ui/button"
import { RepoSelector } from "@/components/agents/RepoSelector"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  buildProfileUpdate,
  useOptions,
  useProfile,
  useRepos,
  useSaveProfile,
} from "@/lib/profile"
import { useSession } from "@/lib/session"

export const Route = createFileRoute("/cloud-agents")({
  component: CloudAgentsPage,
})

function CloudAgentsPage() {
  const session = useSession()
  const profile = useProfile()
  const options = useOptions()
  const repos = useRepos()
  const save = useSaveProfile()

  const [modelId, setModelId] = useState("")
  const [effort, setEffort] = useState("")
  const [subagentModelId, setSubagentModelId] = useState("")
  const [subagentEffort, setSubagentEffort] = useState("")
  const [defaultRepo, setDefaultRepo] = useState("")
  const [baseBranch, setBaseBranch] = useState("")
  const [branchPrefix, setBranchPrefix] = useState("")
  const [error, setError] = useState<string | null>(null)
  const initialized = useRef(false)

  const firstModel: ModelOption | undefined = options.data?.models[0]
  const defaultAgentModel =
    options.data?.default_agent_model ?? firstModel?.id ?? ""
  const defaultAgentEffort =
    options.data?.default_agent_reasoning_effort ??
    firstModel?.default_effort ??
    ""
  const defaultSubagentModel =
    options.data?.default_agent_subagent_model ?? defaultAgentModel
  const defaultSubagentEffort =
    options.data?.default_agent_subagent_reasoning_effort ?? defaultAgentEffort
  const currentModel: ModelOption | undefined =
    options.data?.models.find((m) => m.id === modelId) ?? firstModel
  const currentSubagentModel: ModelOption | undefined =
    options.data?.models.find((m) => m.id === subagentModelId) ?? firstModel

  useEffect(() => {
    if (!profile.data || initialized.current) return
    const hasModel = !!profile.data.default_model || !!defaultAgentModel
    if (!hasModel) return
    initialized.current = true
    setModelId(profile.data.default_model ?? defaultAgentModel)
    setEffort(profile.data.reasoning_effort ?? defaultAgentEffort)
    setSubagentModelId(
      profile.data.default_subagent_model ??
        profile.data.default_model ??
        defaultSubagentModel
    )
    setSubagentEffort(
      profile.data.subagent_reasoning_effort ??
        profile.data.reasoning_effort ??
        defaultSubagentEffort
    )
    setDefaultRepo(profile.data.default_repo ?? "")
    setBaseBranch(profile.data.base_branch ?? "")
    setBranchPrefix(profile.data.branch_prefix ?? "")
  }, [
    profile.data,
    defaultAgentModel,
    defaultAgentEffort,
    defaultSubagentModel,
    defaultSubagentEffort,
  ])

  useEffect(() => {
    if (currentModel && !currentModel.efforts.includes(effort)) {
      setEffort(currentModel.default_effort)
    }
  }, [currentModel, effort])

  useEffect(() => {
    if (
      currentSubagentModel &&
      !currentSubagentModel.efforts.includes(subagentEffort)
    ) {
      setSubagentEffort(currentSubagentModel.default_effort)
    }
  }, [currentSubagentModel, subagentEffort])

  if (session.isLoading) {
    return (
      <main className="p-6">
        <Skeleton className="h-64 w-full" />
      </main>
    )
  }
  if (!session.data) return <Navigate to="/login" />

  const fallbackModel = defaultAgentModel
  const fallbackEffort = defaultAgentEffort

  const persist = (patch: Parameters<typeof buildProfileUpdate>[1]) => {
    setError(null)
    save
      .mutateAsync(
        buildProfileUpdate(profile.data, patch, fallbackModel, fallbackEffort)
      )
      .catch((e: Error) => setError(e.message))
  }

  const persistDefaults = () => {
    persist({
      default_model: modelId,
      reasoning_effort: effort,
      default_subagent_model: subagentModelId,
      subagent_reasoning_effort: subagentEffort,
      default_repo: defaultRepo || null,
      base_branch: baseBranch || null,
      branch_prefix: branchPrefix || null,
    })
  }

  return (
    <AppShell
      user={session.data}
      title="Agente en la nube"
      description="Configura cómo el agente elige modelo, repositorio y valores predeterminados de PR."
    >
      <SettingsSection title="Valores predeterminados">
        <div className="divide-y divide-border">
          <SettingsRow
            label="Modelo predeterminado"
            description="Se usa cuando no se especifica un modelo"
            control={
              <Select value={modelId} onValueChange={(v) => v && setModelId(v)}>
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Elige un modelo" />
                </SelectTrigger>
                <SelectContent>
                  {options.data?.models.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />
          <SettingsRow
            label="Esfuerzo de razonamiento"
            description="Cuánto piensa el modelo antes de responder"
            control={
              <Select value={effort} onValueChange={(v) => v && setEffort(v)}>
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {currentModel?.efforts.map((e) => (
                    <SelectItem key={e} value={e}>
                      {e}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />
          <SettingsRow
            label="Modelo de subagente predeterminado"
            description="Se usa para las tareas delegadas que lanza tu agente"
            control={
              <Select
                value={subagentModelId}
                onValueChange={(v) => v && setSubagentModelId(v)}
              >
                <SelectTrigger className="w-40">
                  <SelectValue placeholder="Elige un modelo" />
                </SelectTrigger>
                <SelectContent>
                  {options.data?.models.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />
          <SettingsRow
            label="Esfuerzo de razonamiento del subagente"
            description="Cuánto piensan los subagentes delegados antes de responder"
            control={
              <Select
                value={subagentEffort}
                onValueChange={(v) => v && setSubagentEffort(v)}
              >
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {currentSubagentModel?.efforts.map((e) => (
                    <SelectItem key={e} value={e}>
                      {e}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            }
          />
          <SettingsRow
            label="Repositorio predeterminado"
            description="Se usa cuando no se especifica un repositorio"
            control={
              repos.data?.repositories?.length ? (
                <div className="w-56">
                  <RepoSelector
                    repos={repos.data.repositories}
                    selectedRepo={defaultRepo || null}
                    onRepoChange={(repo) => setDefaultRepo(repo ?? "")}
                    placeholder="Elige un repositorio…"
                    emptySelectionLabel="Sin repositorio predeterminado"
                    triggerClassName="h-7 w-full max-w-none rounded-md border border-input bg-input/20 px-2 py-1.5 text-xs/relaxed text-foreground transition-colors hover:opacity-100 dark:bg-input/30"
                    dropdownClassName="w-56"
                  />
                </div>
              ) : (
                <Input
                  className="w-56"
                  placeholder="owner/repo"
                  value={defaultRepo}
                  onChange={(e) => setDefaultRepo(e.target.value)}
                />
              )
            }
          />
          <SettingsRow
            label="Base branch"
            description="Si se deja vacío, el agente usará la branch por defecto del repositorio (recomendado)"
            htmlFor="base-branch"
            control={
              <Input
                id="base-branch"
                className="w-56"
                placeholder="Nombre de la branch…"
                value={baseBranch}
                onChange={(e) => setBaseBranch(e.target.value)}
              />
            }
          />
          <SettingsRow
            label="Prefijo de branch"
            description="Prefijo para los nombres de branch que crea el agente"
            htmlFor="branch-prefix"
            control={
              <Input
                id="branch-prefix"
                className="w-56"
                placeholder="open-swe/"
                value={branchPrefix}
                onChange={(e) => setBranchPrefix(e.target.value)}
              />
            }
          />
          <div className="flex justify-end px-4 py-3">
            <Button
              size="sm"
              onClick={persistDefaults}
              disabled={save.isPending}
            >
              {save.isPending ? "Guardando…" : "Guardar valores"}
            </Button>
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title="Pull Requests">
        <div className="divide-y divide-border">
          <SettingsRow
            label="Corregir fallos de CI automáticamente"
            description="El agente intentará corregir los checks de CI que fallen en los PRs que abre."
            comingSoon
            control={
              <Switch
                checked={profile.data?.auto_fix_ci ?? true}
                onCheckedChange={(v) => persist({ auto_fix_ci: v })}
                disabled
              />
            }
          />
          <SettingsRow
            label="Crear PRs siempre"
            description="Crear siempre un pull request para los cambios de código. Si se desactiva, los agentes crean PRs solo cuando es necesario o se solicita."
            control={
              <Switch
                checked={profile.data?.create_prs ?? false}
                onCheckedChange={(v) => persist({ create_prs: v })}
              />
            }
          />
        </div>
      </SettingsSection>

      <SettingsSection title="Rules">
        <Link
          to="/agents/instructions"
          className="flex items-center justify-between gap-6 px-4 py-3 hover:bg-muted/40"
        >
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-medium text-foreground">Repository Instructions</span>
            <span className="text-xs text-muted-foreground">
              Per-repo custom instructions injected into the agent's system prompt.
            </span>
          </div>
          <CaretRightIcon className="size-3.5 shrink-0 text-muted-foreground" />
        </Link>
      </SettingsSection>

      {error && <p className="text-xs text-destructive">{error}</p>}
    </AppShell>
  )
}
