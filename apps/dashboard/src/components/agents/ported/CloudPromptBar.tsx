import {
  ArrowUp,
  ChevronDown,
  CornerDownRight,
  ImagePlus,
  LoaderCircle,
  MoreHorizontal,
  Trash2,
  X,
} from "lucide-react"
import { StopIcon } from "@phosphor-icons/react"
import { useQueryClient } from "@tanstack/react-query"
import { useStreamContext as useAgentThreadStream } from "@langchain/react"
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import type { ModelOption } from "@/lib/api"
import type { ImageChunk } from "@/lib/agents/types"
import type { ModelSelection } from "@/lib/agents/provider/useModelOptions"
import { RepoSelector } from "@/components/agents/RepoSelector"
import { useIsInAgentThreadStream } from "@/lib/agents/provider/useIsInAgentThreadStream"
import { agentsApi } from "@/lib/agents/api"
import { agentThreadKeys } from "@/lib/agents/queries"
import { formatModelSelection } from "@/lib/agents/provider/useModelOptions"
import { IconButton } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const PROMPT_TEXTAREA_MAX_HEIGHT = 200

interface SubmitButtonProps {
  canSubmit: boolean
  disabled: boolean
  onSubmit: () => void
}

function PlainSubmitButton({ canSubmit, disabled, onSubmit }: SubmitButtonProps) {
  return (
    <IconButton
      type="button"
      onClick={onSubmit}
      disabled={!canSubmit}
      aria-label="Enviar mensaje"
      className="shrink-0 rounded-full bg-[var(--ui-accent)] text-white hover:bg-[var(--ui-accent)] hover:opacity-90 disabled:cursor-default disabled:opacity-40"
    >
      {disabled ? (
        <LoaderCircle className="size-3.5 animate-spin" />
      ) : (
        <ArrowUp className="size-3.5" strokeWidth={2.5} />
      )}
    </IconButton>
  )
}

function SubmitButton(props: SubmitButtonProps) {
  const inAgentThreadStream = useIsInAgentThreadStream()

  if (inAgentThreadStream) return <StreamSubmitButton {...props} />

  return <PlainSubmitButton {...props} />
}

function StreamSubmitButton(props: SubmitButtonProps) {
  const stream = useAgentThreadStream()
  const queryClient = useQueryClient()
  const [stopping, setStopping] = useState(false)

  const handleStop = async () => {
    if (stopping) return
    setStopping(true)
    const threadId = stream.threadId
    try {
      // Stop = stop everything AND discard the queue (standard agent UX). Clear
      // the queue BEFORE stopping so the stream provider's `onCompleted` sees an
      // empty queue and doesn't auto-continue the next queued message.
      if (threadId) {
        try {
          await agentsApi.clearQueuedMessages(threadId)
        } catch {
          /* best-effort; stopping still proceeds */
        }
      }
      await stream.stop()
      if (threadId) {
        queryClient.setQueryData(agentThreadKeys.detail(threadId), (prev) =>
          prev ? { ...prev, status: "interrupted" as const } : prev
        )
        void queryClient.invalidateQueries({ queryKey: agentThreadKeys.all, exact: true })
        // Clear the queue rows in the thread view (it listens for this event).
        window.dispatchEvent(
          new CustomEvent("agent-thread-queued-continued", { detail: { threadId } })
        )
      }
    } finally {
      setStopping(false)
    }
  }

  if (!stream.isLoading || props.canSubmit) return <PlainSubmitButton {...props} />

  return (
    <IconButton
      type="button"
      onClick={() => void handleStop()}
      disabled={stopping}
      aria-label="Detener ejecución"
      title="Detener ejecución"
      className="shrink-0 rounded-full bg-[var(--ui-accent)] text-white hover:bg-[var(--ui-accent)] hover:opacity-90 disabled:cursor-default disabled:opacity-40"
    >
      {stopping ? (
        <LoaderCircle className="size-3.5 animate-spin" />
      ) : (
        <StopIcon className="size-3.5" weight="fill" />
      )}
    </IconButton>
  )
}
const MAX_IMAGE_COUNT = 5
const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const SUPPORTED_IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
])

export interface CloudPromptBarProps {
  placeholder?: string
  compact?: boolean
  disabled?: boolean
  busy?: boolean
  onSubmit?: (value: string, images: Array<ImageChunk>) => void
  queuedFollowUps?: Array<{ id: string; text: string; imageCount: number }>
  onQueuedDiscard?: (id: string) => void | Promise<void>
  onQueuedDirect?: (id: string) => void | Promise<void>
  onQueuedClearAll?: () => void | Promise<void>
  models?: Array<ModelOption>
  selection?: ModelSelection | null
  onSelectionChange?: (next: ModelSelection) => void
  /** Repos the user can target. When provided with onRepoChange, a repo picker is shown. */
  repos?: Array<{ full_name: string }>
  selectedRepo?: string | null
  onRepoChange?: (repo: string | null) => void
}

function fileToImageChunk(file: File): Promise<ImageChunk | null> {
  if (!SUPPORTED_IMAGE_TYPES.has(file.type) || file.size > MAX_IMAGE_BYTES) {
    return Promise.resolve(null)
  }

  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = typeof reader.result === "string" ? reader.result : ""
      const base64 = dataUrl.split(",")[1]
      resolve(
        base64
          ? {
            kind: "image",
            base64,
            mimeType: file.type,
            fileName: file.name,
          }
          : null
      )
    }
    reader.onerror = () => resolve(null)
    reader.readAsDataURL(file)
  })
}

/** Web-adapted PromptBar from open-swe-app — local state, no Electron/Zustand deps. */
export const CloudPromptBar = memo(function CloudPromptBarComponent({
  placeholder = "Pídele al agente construir, arreglar bugs o explorar",
  compact = false,
  disabled = false,
  busy = false,
  onSubmit,
  queuedFollowUps = [],
  onQueuedDiscard,
  onQueuedDirect,
  onQueuedClearAll,
  models = [],
  selection = null,
  onSelectionChange,
  repos,
  selectedRepo = null,
  onRepoChange,
}: CloudPromptBarProps) {
  const [value, setValue] = useState("")
  const [pendingImages, setPendingImages] = useState<Array<ImageChunk>>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const [queuedMenuOpen, setQueuedMenuOpen] = useState<string | null>(null)
  const [queuedActionPending, setQueuedActionPending] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragDepthRef = useRef(0)
  const modelDropdownRef = useRef<HTMLDivElement>(null)

  const combos = useMemo<Array<ModelSelection>>(() => {
    const list: Array<ModelSelection> = []
    for (const model of models) {
      for (const effort of model.efforts) {
        list.push({ modelId: model.id, effort })
      }
    }
    return list
  }, [models])

  const selectionLabel = formatModelSelection(models, selection)

  const canSubmit =
    !disabled && (value.trim().length > 0 || pendingImages.length > 0)

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim()
    if (!canSubmit) return
    onSubmit?.(trimmed, pendingImages)
    setValue("")
    setPendingImages([])
  }, [canSubmit, onSubmit, pendingImages, value])

  const handleQueuedAction = useCallback(
    async (action?: () => void | Promise<void>) => {
      if (!action || queuedActionPending) return
      setQueuedActionPending(true)
      try {
        await action()
      } catch (error) {
        console.warn("Queued follow-up action failed", error)
      } finally {
        setQueuedActionPending(false)
      }
    },
    [queuedActionPending]
  )

  const handleQueuedReplace = useCallback(async (id: string) => {
    if (!canSubmit || !onQueuedDiscard || queuedActionPending) return
    const trimmed = value.trim()
    const images = pendingImages
    setQueuedActionPending(true)
    try {
      await onQueuedDiscard(id)
      onSubmit?.(trimmed, images)
      setValue("")
      setPendingImages([])
      setQueuedMenuOpen(null)
    } catch (error) {
      console.warn("Queued follow-up replace failed", error)
    } finally {
      setQueuedActionPending(false)
    }
  }, [
    canSubmit,
    onQueuedDiscard,
    onSubmit,
    pendingImages,
    queuedActionPending,
    value,
  ])

  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el) return

    el.style.height = "auto"
    const clampedHeight = Math.min(el.scrollHeight, PROMPT_TEXTAREA_MAX_HEIGHT)
    el.style.height = `${clampedHeight}px`
    el.style.overflowY =
      el.scrollHeight > PROMPT_TEXTAREA_MAX_HEIGHT ? "auto" : "hidden"
  }, [value])

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node
      if (
        modelDropdownRef.current &&
        !modelDropdownRef.current.contains(target)
      ) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  const addFiles = useCallback(async (files: FileList | Array<File>) => {
    const nextImages = await Promise.all(
      Array.from(files).map(fileToImageChunk)
    )
    const validImages = nextImages.filter(
      (image): image is ImageChunk => image !== null
    )
    if (validImages.length === 0) return
    setPendingImages((prev) =>
      [...prev, ...validImages].slice(0, MAX_IMAGE_COUNT)
    )
  }, [])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files
      if (files) void addFiles(files)
      e.target.value = ""
    },
    [addFiles]
  )

  const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return
    e.preventDefault()
    dragDepthRef.current += 1
    setIsDragOver(true)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes("Files")) return
    e.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setIsDragOver(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer.types.includes("Files")) return
      e.preventDefault()
      dragDepthRef.current = 0
      setIsDragOver(false)
      void addFiles(e.dataTransfer.files)
    },
    [addFiles]
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && canSubmit) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const pickerDisabled = combos.length === 0 || !onSelectionChange

  return (
    <div
      className={cn(
        "relative w-full font-sans text-[13px]",
        compact ? "max-w-none" : "max-w-2xl"
      )}
    >
      {onRepoChange && (
        <div className="mb-2 flex items-center gap-2 px-1 text-xs">
          <RepoSelector
            repos={repos}
            selectedRepo={selectedRepo}
            onRepoChange={onRepoChange}
          />
        </div>
      )}
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "relative flex min-h-[106px] flex-col rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-3 py-2.5 shadow-sm",
          compact && "min-h-[88px]",
          isDragOver && "border-[var(--ui-accent)]"
        )}
      >
        {queuedFollowUps.length > 0 && (
          <div className="mb-2 space-y-1 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-panel-2)]/70 px-2.5 py-2 text-[12px] text-[color:var(--ui-text-muted)]">
            {queuedFollowUps.map((followUp) => (
              <div key={followUp.id} className="relative flex min-w-0 items-center gap-2">
                <CornerDownRight className="size-3.5 shrink-0 text-[color:var(--ui-text-dim)]" />
                <div className="min-w-0 flex-1 truncate">
                  {followUp.text || `${followUp.imageCount} imagen(es) en cola`}
                </div>
                <button
                  type="button"
                  disabled={queuedActionPending || !onQueuedDirect}
                  onClick={() =>
                    void handleQueuedAction(() => onQueuedDirect?.(followUp.id))
                  }
                  className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[color:var(--ui-text-muted)] transition-colors hover:bg-[var(--ui-surface)] hover:text-[color:var(--ui-text)] disabled:opacity-50"
                  title="Forzar este seguimiento en el run activo"
                >
                  <CornerDownRight className="size-3" />
                  Dirigir
                </button>
                <button
                  type="button"
                  disabled={queuedActionPending || !onQueuedDiscard}
                  onClick={() =>
                    void handleQueuedAction(() => onQueuedDiscard?.(followUp.id))
                  }
                  className="flex size-6 shrink-0 items-center justify-center rounded-md text-[color:var(--ui-text-dim)] transition-colors hover:bg-[var(--ui-surface)] hover:text-[color:var(--ui-text)] disabled:opacity-50"
                  aria-label="Descartar seguimiento en cola"
                  title="Descartar seguimiento en cola"
                >
                  <Trash2 className="size-3.5" />
                </button>
                <button
                  type="button"
                  disabled={queuedActionPending}
                  onClick={() =>
                    setQueuedMenuOpen((open) => (open === followUp.id ? null : followUp.id))
                  }
                  className="flex size-6 shrink-0 items-center justify-center rounded-md text-[color:var(--ui-text-dim)] transition-colors hover:bg-[var(--ui-surface)] hover:text-[color:var(--ui-text)] disabled:opacity-50"
                  aria-label="Más opciones de cola"
                  title="Más opciones de cola"
                >
                  <MoreHorizontal className="size-3.5" />
                </button>
                {queuedMenuOpen === followUp.id && (
                  <div className="absolute top-7 right-0 z-30 min-w-44 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-panel-2)] p-1 shadow-lg">
                    <button
                      type="button"
                      disabled={!canSubmit || queuedActionPending || !onQueuedDiscard}
                      onClick={() => void handleQueuedReplace(followUp.id)}
                      className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[color:var(--ui-text-muted)] transition-colors hover:bg-[var(--ui-surface)] hover:text-[color:var(--ui-text)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Reemplazar por borrador
                    </button>
                    {queuedFollowUps.length > 1 && onQueuedClearAll && (
                      <button
                        type="button"
                        disabled={queuedActionPending}
                        onClick={() => void handleQueuedAction(onQueuedClearAll)}
                        className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[color:var(--ui-text-muted)] transition-colors hover:bg-[var(--ui-surface)] hover:text-[color:var(--ui-text)] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Borrar todos
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {isDragOver && (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-2xl bg-[var(--ui-surface)]/80 backdrop-blur-sm">
            <span className="rounded-md bg-[var(--ui-panel-2)] px-3 py-1.5 text-sm font-medium text-[color:var(--ui-accent)]">
              Drop images here
            </span>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />

        {pendingImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {pendingImages.map((image, index) => (
              <div
                key={`${image.fileName ?? "image"}-${index}`}
                className="group relative"
              >
                <img
                  src={`data:${image.mimeType};base64,${image.base64}`}
                  alt={image.fileName || "pending image"}
                  className="size-16 rounded-lg border border-[var(--ui-border)] object-cover"
                />
                <button
                  type="button"
                  aria-label="Quitar imagen"
                  onClick={() =>
                    setPendingImages((prev) =>
                      prev.filter((_, i) => i !== index)
                    )
                  }
                  className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full border border-[var(--ui-border)] bg-[var(--ui-panel-2)] text-[color:var(--ui-text-muted)] opacity-0 shadow-sm transition-opacity group-hover:opacity-100 hover:text-[color:var(--ui-text)]"
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={inputRef}
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={busy ? "Enviar seguimiento al finalizar el run" : placeholder}
          disabled={disabled}
          className={cn(
            "w-full min-w-0 resize-none overflow-hidden bg-transparent text-[13px] leading-[1.45] text-[color:var(--ui-text)] outline-none placeholder:text-[color:var(--ui-text-dim)]",
            compact ? "min-h-[36px]" : "min-h-[52px]"
          )}
          style={{ maxHeight: PROMPT_TEXTAREA_MAX_HEIGHT }}
        />

        <div className="mt-auto flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 pt-2 text-xs text-[color:var(--ui-text-dim)]">
          <div ref={modelDropdownRef} className="relative min-w-0 shrink">
            <button
              type="button"
              disabled={pickerDisabled}
              onClick={() => setModelDropdownOpen((open) => !open)}
              className="flex max-w-[220px] cursor-pointer items-center gap-0.5 text-[13px] text-[color:var(--ui-text-muted)] transition-opacity hover:opacity-80 disabled:cursor-default disabled:opacity-60"
            >
              <span className="truncate">{selectionLabel}</span>
              {!pickerDisabled && (
                <ChevronDown className="size-3.5 shrink-0 opacity-60" />
              )}
            </button>
            {modelDropdownOpen && combos.length > 0 && (
              <div className="absolute bottom-full left-0 z-50 mb-1 max-h-72 overflow-hidden overflow-y-auto rounded border border-[var(--ui-border)] bg-[var(--ui-surface)] shadow-lg">
                {combos.map((combo) => {
                  const selected =
                    !!selection &&
                    selection.modelId === combo.modelId &&
                    selection.effort === combo.effort
                  return (
                    <button
                      key={`${combo.modelId}::${combo.effort}`}
                      type="button"
                      onClick={() => {
                        onSelectionChange?.(combo)
                        setModelDropdownOpen(false)
                      }}
                      className={cn(
                        "flex w-full items-center gap-2 px-3 py-1.5 text-left whitespace-nowrap transition-colors hover:bg-[var(--ui-panel-2)]",
                        selected
                          ? "text-[color:var(--ui-text)]"
                          : "text-[color:var(--ui-text-muted)]"
                      )}
                    >
                      {formatModelSelection(models, combo)}
                      {selected && (
                        <span className="ml-auto pl-3 text-[color:var(--ui-text-dim)]">
                          ✓
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || pendingImages.length >= MAX_IMAGE_COUNT}
            aria-label="Adjuntar imágenes"
            className="ml-auto flex size-7 shrink-0 items-center justify-center rounded-full text-[color:var(--ui-text-muted)] transition-colors hover:bg-[var(--ui-panel-2)] hover:text-[color:var(--ui-text)] disabled:cursor-default disabled:opacity-40"
          >
            <ImagePlus className="size-4" />
          </button>

          <SubmitButton
            canSubmit={canSubmit}
            disabled={disabled}
            onSubmit={handleSubmit}
          />
        </div>
      </div>
    </div>
  )
})
