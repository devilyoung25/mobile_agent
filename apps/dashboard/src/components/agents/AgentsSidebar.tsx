import { ContextMenu } from "@base-ui/react/context-menu"
import { Dialog } from "@base-ui/react/dialog"
import { Link } from "@tanstack/react-router"
import {
  CalendarBlankIcon,
  CaretDownIcon,
  CaretRightIcon,
  ChartLineUpIcon,
  ChatCircleIcon,
  CircleNotchIcon,
  GitMergeIcon,
  GitPullRequestIcon,
  LightningIcon,
  PlusIcon,
  FolderIcon,
  FolderPlusIcon,
  TrashIcon,
  TreeStructureIcon,
  XIcon,
} from "@phosphor-icons/react"
import { IoLogoGithub, IoLogoSlack } from "react-icons/io5"
import { SiLinear } from "react-icons/si"
import { useEffect, useMemo, useState } from "react"
import type { ComponentType, SVGProps } from "react"

import type { SessionUser } from "@/lib/api"
import type { AgentSource, AgentThread } from "@/lib/agents/types"
import { SidebarUserMenu } from "@/components/SidebarUserMenu"
import { OnOffBrand } from "@/components/OnOffBrand"
import { Button } from "@/components/ui/button"
import {
  SidebarCollapseButton,
  SidebarFrame,
  useSidebarLayout,
} from "@/components/sidebar-layout"
import { groupThreads } from "@/lib/agents/api"
import {
  useAgentThreads,
  useDeleteAgentThread,
  useSeedAgentThreadDetails,
} from "@/lib/agents/queries"
import { usePickWorkspace, useWorkspaces } from "@/lib/profile"
import { cn } from "@/lib/utils"

type SourceIcon = ComponentType<SVGProps<SVGSVGElement>>

const SOURCE_META: Record<AgentSource, { icon: SourceIcon; label: string }> = {
  dashboard: { icon: ChatCircleIcon, label: "Started from the dashboard" },
  github: { icon: IoLogoGithub, label: "Triggered from GitHub" },
  slack: { icon: IoLogoSlack, label: "Triggered from Slack" },
  linear: { icon: SiLinear, label: "Triggered from Linear" },
  schedule: { icon: CalendarBlankIcon, label: "Triggered from a schedule" },
}

type PrState = NonNullable<AgentThread["pr"]>["state"]

const PR_STATE_META: Record<
  PrState,
  { icon: SourceIcon; label: string; className: string }
> = {
  draft: {
    icon: GitPullRequestIcon,
    label: "Draft pull request",
    className: "text-[var(--ui-text-dim)]",
  },
  open: {
    icon: GitPullRequestIcon,
    label: "Open pull request",
    className: "text-[var(--ui-success)]",
  },
  merged: {
    icon: GitMergeIcon,
    label: "Merged pull request",
    className: "text-[var(--ui-accent)]",
  },
  closed: {
    icon: GitPullRequestIcon,
    label: "Closed pull request",
    className: "text-[var(--ui-danger)]",
  },
}

interface AgentsSidebarProps {
  user: SessionUser
  activeThreadId?: string
}

const NAV = [
  { to: "/agents/automations", label: "Automatizaciones", icon: LightningIcon },
  { to: "/my-settings", label: "Panel", icon: ChartLineUpIcon },
] as const

export const SELECTED_WORKSPACE_STORAGE_KEY =
  "on-mobile-agent.selected-workspace-id"
export const WORKSPACE_SELECTION_EVENT = "on-mobile-agent:workspace-selected"

export function AgentsSidebar({ user, activeThreadId }: AgentsSidebarProps) {
  const threadsQuery = useAgentThreads()
  const threads = threadsQuery.data ?? []
  const workspacesQuery = useWorkspaces()
  const pickWorkspace = usePickWorkspace()
  useSeedAgentThreadDetails(threads, activeThreadId)
  const layout = useSidebarLayout()
  const workspaces = workspacesQuery.data?.workspaces ?? []
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    () =>
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(SELECTED_WORKSPACE_STORAGE_KEY)
  )
  const selectedWorkspace = workspaces.find(
    (workspace) => workspace.id === selectedWorkspaceId
  )
  const visibleThreads = useMemo(
    () =>
      selectedWorkspaceId
        ? threads.filter((thread) => thread.workspaceId === selectedWorkspaceId)
        : threads.filter((thread) => !thread.workspaceId),
    [selectedWorkspaceId, threads]
  )
  const groups = groupThreads(visibleThreads)

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

  const onPickWorkspace = () => {
    if (pickWorkspace.isPending) return
    pickWorkspace.reset()
    pickWorkspace.mutate()
  }

  const clearWorkspaceSelection = () => {
    window.localStorage.removeItem(SELECTED_WORKSPACE_STORAGE_KEY)
    window.dispatchEvent(new Event(WORKSPACE_SELECTION_EVENT))
    layout.closeOnMobile()
  }

  return (
    <SidebarFrame
      {...layout}
      className="border-r border-[var(--ui-border)] bg-[var(--ui-sidebar)]"
    >
      <div className="flex items-center justify-between px-4 pt-5 pb-4">
        <Link to="/my-settings" className="min-w-0">
          <OnOffBrand showMobileCue />
        </Link>
        <SidebarCollapseButton onToggle={layout.toggle} />
      </div>

      <div className="px-2 pb-1">
        <Link
          to="/agents"
          onClick={clearWorkspaceSelection}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--ui-text)] transition-colors hover:bg-[var(--ui-sidebar-hover)]"
        >
          <PlusIcon className="size-4" />
          Nuevo agente
        </Link>
      </div>

      <nav className="flex flex-col gap-0.5 px-2 pb-4">
        {NAV.map((item) => {
          const Icon = item.icon
          return (
            <Link
              key={item.to}
              to={item.to}
              onClick={layout.closeOnMobile}
              className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs text-[var(--ui-text-muted)] transition-colors hover:bg-[var(--ui-sidebar-hover)] hover:text-[var(--ui-text)]"
              activeProps={{
                className:
                  "bg-[var(--ui-sidebar-hover)] !text-[var(--ui-text)] font-medium",
              }}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          )
        })}
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <ChatScopeSection
          isSelected={!selectedWorkspaceId}
          threadCount={threads.filter((thread) => !thread.workspaceId).length}
          onSelect={clearWorkspaceSelection}
        />
        <WorkspaceSection
          workspaces={workspaces}
          loading={workspacesQuery.isLoading}
          picking={pickWorkspace.isPending}
          error={
            pickWorkspace.isPending
              ? null
              : pickWorkspace.error instanceof Error
              ? pickWorkspace.error.message
              : workspacesQuery.error instanceof Error
                ? workspacesQuery.error.message
                : null
          }
          onPickWorkspace={onPickWorkspace}
          onNavigate={layout.closeOnMobile}
          selectedWorkspaceId={selectedWorkspaceId}
        />
        <div className="px-2 py-1 text-[10px] font-semibold tracking-wide text-[var(--ui-text-dim)] uppercase">
          {selectedWorkspace
            ? `Chats de ${selectedWorkspace.label}`
            : "Chats corrientes"}
        </div>
        <ThreadGroup
          label="Hoy"
          threads={groups.today}
          activeThreadId={activeThreadId}
          onNavigate={layout.closeOnMobile}
        />
        <ThreadGroup
          label="Últimos 7 días"
          threads={groups.last7}
          activeThreadId={activeThreadId}
          onNavigate={layout.closeOnMobile}
          defaultCollapsed
        />
        <ThreadGroup
          label="Últimos 30 días"
          threads={groups.last30}
          activeThreadId={activeThreadId}
          onNavigate={layout.closeOnMobile}
          defaultCollapsed
        />
        <ThreadGroup
          label="Anteriores"
          threads={groups.older}
          activeThreadId={activeThreadId}
          onNavigate={layout.closeOnMobile}
        />
      </div>

      <div className="p-2">
        <SidebarUserMenu user={user} showSettingsLink />
      </div>
    </SidebarFrame>
  )
}

function ChatScopeSection({
  isSelected,
  threadCount,
  onSelect,
}: {
  isSelected: boolean
  threadCount: number
  onSelect: () => void
}) {
  return (
    <div className="mb-4">
      <div className="px-2 py-1 text-[10px] font-semibold tracking-wide text-[var(--ui-text-dim)] uppercase">
        Chats
      </div>
      <Link
        to="/agents"
        onClick={onSelect}
        className={cn(
          "flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs transition-colors hover:bg-[var(--ui-sidebar-hover)] hover:text-[var(--ui-text)]",
          isSelected
            ? "bg-[var(--ui-sidebar-hover)] text-[var(--ui-text)]"
            : "text-[var(--ui-text-muted)]"
        )}
      >
        <ChatCircleIcon className="size-3.5 shrink-0 text-[var(--ui-text-dim)]" />
        <span className="min-w-0 flex-1 truncate">Chats corrientes</span>
        <span className="shrink-0 rounded bg-[var(--ui-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--ui-text-dim)]">
          {threadCount}
        </span>
      </Link>
    </div>
  )
}

function WorkspaceSection({
  workspaces,
  loading,
  picking,
  error,
  onPickWorkspace,
  onNavigate,
  selectedWorkspaceId,
}: {
  workspaces: Array<{
    id: string
    label: string
    path: string
    current_branch: string | null
    is_dirty: boolean
  }>
  loading: boolean
  picking: boolean
  error: string | null
  onPickWorkspace: () => void
  onNavigate?: () => void
  selectedWorkspaceId?: string | null
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-1 px-2 py-1 text-[10px] font-semibold tracking-wide text-[var(--ui-text-dim)] uppercase">
        <span className="min-w-0 flex-1 truncate">Proyectos</span>
        <button
          type="button"
          onClick={onPickWorkspace}
          disabled={picking}
          className="grid size-5 place-items-center rounded text-[var(--ui-text-dim)] transition-colors hover:bg-[var(--ui-sidebar-hover)] hover:text-[var(--ui-text)] disabled:opacity-50"
          aria-label="Agregar proyecto local"
          title="Usar una carpeta existente"
        >
          {picking ? (
            <CircleNotchIcon className="size-3 animate-spin" />
          ) : (
            <FolderPlusIcon className="size-3.5" />
          )}
        </button>
      </div>
      {loading ? (
        <div className="px-2 py-1 text-xs text-[var(--ui-text-dim)]">
          Cargando proyectos...
        </div>
      ) : workspaces.length === 0 ? (
        <button
          type="button"
          onClick={onPickWorkspace}
          disabled={picking}
          className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-[var(--ui-text-dim)] transition-colors hover:bg-[var(--ui-sidebar-hover)] hover:text-[var(--ui-text)] disabled:opacity-50"
        >
          <FolderPlusIcon className="size-3.5 shrink-0" />
          <span>Agregar carpeta local</span>
        </button>
      ) : (
        <div className="space-y-0.5">
          {workspaces.map((workspace) => (
            <Link
              key={workspace.id}
              to="/agents"
              onClick={() => {
                window.localStorage.setItem(
                  SELECTED_WORKSPACE_STORAGE_KEY,
                  workspace.id
                )
                window.dispatchEvent(new Event(WORKSPACE_SELECTION_EVENT))
                onNavigate?.()
              }}
              title={workspace.path}
              className={cn(
                "group flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs transition-colors hover:bg-[var(--ui-sidebar-hover)] hover:text-[var(--ui-text)]",
                workspace.id === selectedWorkspaceId
                  ? "bg-[var(--ui-sidebar-hover)] text-[var(--ui-text)]"
                  : "text-[var(--ui-text-muted)]"
              )}
            >
              <FolderIcon className="size-3.5 shrink-0 text-[var(--ui-text-dim)]" />
              <span className="min-w-0 flex-1 truncate">{workspace.label}</span>
              {workspace.current_branch && (
                <span className="max-w-20 truncate rounded bg-[var(--ui-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--ui-text-dim)]">
                  {workspace.current_branch}
                </span>
              )}
              {workspace.is_dirty && (
                <span
                  className="size-1.5 shrink-0 rounded-full bg-[var(--ui-accent)]"
                  aria-label="Cambios locales"
                />
              )}
            </Link>
          ))}
        </div>
      )}
      {error && (
        <div className="mt-1 px-2 text-[10px] leading-snug text-[var(--ui-danger)]">
          {workspaceErrorLabel(error)}
        </div>
      )}
    </div>
  )
}

function workspaceErrorLabel(error: string): string {
  if (error.startsWith("workspace_git_error:")) {
    return "Selecciona una carpeta que sea un repositorio Git conectado a Azure DevOps."
  }
  const labels: Record<string, string> = {
    workspace_picker_cancelled: "Selección cancelada.",
    workspace_picker_disabled: "Selector de carpetas deshabilitado.",
    workspace_picker_unsupported: "Selector no soportado en este sistema.",
    workspace_path_not_directory: "La ruta seleccionada no es una carpeta.",
    workspace_path_not_git_repo:
      "Selecciona una carpeta que sea un repositorio Git.",
    workspace_path_missing_origin:
      "El repositorio seleccionado no tiene remote origin configurado.",
    workspace_path_not_azure_repo:
      "Selecciona un repositorio conectado a Azure DevOps.",
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
    workspace_fetch_failed:
      "No se pudo actualizar desde el remoto. Revisa conexión, permisos o credenciales.",
    workspace_base_mode_invalid: "Modo de base de workspace inválido.",
    workspace_not_attached: "Este hilo no tiene un workspace asociado.",
  }
  return labels[error] ?? error
}

function ThreadGroup({
  label,
  threads,
  activeThreadId,
  onNavigate,
  defaultCollapsed = false,
}: {
  label: string
  threads: Array<AgentThread>
  activeThreadId?: string
  onNavigate?: () => void
  defaultCollapsed?: boolean
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)
  if (threads.length === 0) return null

  const ToggleIcon = collapsed ? CaretRightIcon : CaretDownIcon

  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={() => setCollapsed((value) => !value)}
        className="flex w-full items-center gap-1 px-2 py-1 text-left text-[10px] font-semibold tracking-wide text-[var(--ui-text-dim)] uppercase transition-colors hover:text-[var(--ui-text-muted)]"
        aria-expanded={!collapsed}
      >
        <ToggleIcon className="size-3" />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <span>{threads.length}</span>
      </button>
      {!collapsed &&
        threads.map((thread) => (
          <ThreadRow
            key={thread.id}
            thread={thread}
            isActive={thread.id === activeThreadId}
            onNavigate={onNavigate}
          />
        ))}
    </div>
  )
}

function ThreadRow({
  thread,
  isActive,
  onNavigate,
}: {
  thread: AgentThread
  isActive: boolean
  onNavigate?: () => void
}) {
  const deleteThread = useDeleteAgentThread()
  const [deleteOpen, setDeleteOpen] = useState(false)
  const badge =
    thread.diffStats && thread.diffStats.additions > 0
      ? `+${thread.diffStats.additions}`
      : null
  const isDeleting =
    deleteThread.isPending && deleteThread.variables === thread.id

  const onDelete = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (isDeleting) return
    setDeleteOpen(true)
  }

  const onConfirmDelete = () => {
    if (isDeleting) return
    deleteThread.mutate(thread.id, {
      onSuccess: () => setDeleteOpen(false),
    })
  }

  const source =
    thread.source && thread.source !== "dashboard"
      ? SOURCE_META[thread.source]
      : null
  const SourceIcon = source?.icon
  const prMeta = thread.pr ? PR_STATE_META[thread.pr.state] : null
  const PrIcon = prMeta?.icon
  const showFinishedIndicator = thread.status === "finished" && !thread.viewed

  const openTrace = () => {
    if (!thread.traceUrl) return
    window.open(thread.traceUrl, "_blank", "noopener,noreferrer")
  }

  return (
    <>
      <ContextMenu.Root>
        <ContextMenu.Trigger
          render={
            <Link
              to="/agents/$threadId"
              params={{ threadId: thread.id }}
              onClick={onNavigate}
              className={cn(
                "group mb-0.5 flex items-center gap-2 rounded-lg px-2.5 py-1.5 transition-colors",
                isActive
                  ? "bg-[var(--ui-accent-bubble)] text-[var(--ui-text)]"
                  : "text-[var(--ui-text-muted)] hover:bg-[var(--ui-sidebar-hover)]",
                isDeleting && "opacity-50"
              )}
            />
          }
        >
          {thread.status === "running" ? (
            <CircleNotchIcon
              className="size-3 shrink-0 animate-spin text-[var(--ui-accent)]"
              aria-label="Hilo en ejecución"
            />
          ) : (
            <span
              className={cn(
                "size-2 shrink-0 rounded-full",
                showFinishedIndicator
                  ? "bg-[var(--ui-accent)]"
                  : "bg-[var(--ui-border)]"
              )}
              aria-label={
                showFinishedIndicator ? "Hilo terminado" : "Hilo visto"
              }
            />
          )}
          {source && SourceIcon && (
            <SourceIcon
              className="size-3.5 shrink-0 text-[var(--ui-text-dim)]"
              aria-label={source.label}
            >
              <title>{source.label}</title>
            </SourceIcon>
          )}
          <span className="min-w-0 flex-1 truncate text-xs">
            {thread.title}
          </span>
          {prMeta && PrIcon && (
            <PrIcon
              className={cn(
                "size-3.5 shrink-0 group-hover:hidden",
                prMeta.className
              )}
              aria-label={prMeta.label}
            >
              <title>{prMeta.label}</title>
            </PrIcon>
          )}
          {badge && (
            <span className="shrink-0 rounded bg-[var(--ui-panel-2)] px-1.5 py-0.5 text-[10px] text-[var(--ui-text-dim)] group-hover:hidden">
              {badge}
            </span>
          )}
          <button
            type="button"
            aria-label="Eliminar hilo"
            onClick={onDelete}
            disabled={isDeleting}
            className="hidden size-4 shrink-0 items-center justify-center rounded text-[var(--ui-text-dim)] group-hover:flex hover:bg-[var(--ui-panel-2)] hover:text-[var(--ui-text)]"
          >
            <XIcon className="size-3" weight="bold" />
          </button>
        </ContextMenu.Trigger>
        <ContextMenu.Portal>
          <ContextMenu.Positioner className="z-50 outline-none">
            <ContextMenu.Popup className="min-w-[10rem] overflow-hidden rounded-md border border-[var(--ui-border)] bg-popover p-1 text-popover-foreground shadow-md outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95">
              <ContextMenu.Item
                disabled={!thread.traceUrl}
                onClick={openTrace}
                className="flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-xs outline-none select-none data-highlighted:bg-[var(--ui-sidebar-hover)] data-disabled:pointer-events-none data-disabled:opacity-50"
              >
                <TreeStructureIcon className="size-3.5" />
                Ver traza
              </ContextMenu.Item>
              <ContextMenu.Item
                onClick={onDelete}
                disabled={isDeleting}
                className="flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-xs text-[var(--ui-danger)] outline-none select-none data-highlighted:bg-[var(--ui-sidebar-hover)] data-disabled:pointer-events-none data-disabled:opacity-50"
              >
                <TrashIcon className="size-3.5" />
                Eliminar hilo
              </ContextMenu.Item>
            </ContextMenu.Popup>
          </ContextMenu.Positioner>
        </ContextMenu.Portal>
      </ContextMenu.Root>
      <Dialog.Root open={deleteOpen} onOpenChange={setDeleteOpen}>
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/50 data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0" />
          <Dialog.Popup className="fixed top-1/2 left-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-popover p-6 text-popover-foreground shadow-md ring-1 ring-foreground/10 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95">
            <div className="flex flex-col gap-4">
              <Dialog.Title className="text-base font-semibold">
                Eliminar hilo
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                ¿Eliminar «{thread.title}»? Esta acción no se puede deshacer.
              </Dialog.Description>
              <div className="mt-2 flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setDeleteOpen(false)}
                  disabled={isDeleting}
                >
                  Cancelar
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={onConfirmDelete}
                  disabled={isDeleting}
                >
                  {isDeleting ? "Eliminando..." : "Eliminar"}
                </Button>
              </div>
            </div>
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  )
}

export function AgentsShell({
  user,
  activeThreadId,
  children,
}: {
  user: SessionUser
  activeThreadId?: string
  children: React.ReactNode
}) {
  return (
    <div className="agents-ui flex h-svh overflow-hidden bg-[var(--ui-bg)]">
      <AgentsSidebar user={user} activeThreadId={activeThreadId} />
      <div className="flex min-w-0 flex-1">{children}</div>
    </div>
  )
}
