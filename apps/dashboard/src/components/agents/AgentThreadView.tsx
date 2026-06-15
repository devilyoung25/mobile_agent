import { useCallback, useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useStreamContext as useAgentThreadStream } from "@langchain/react"

import type { AgentThread, Message } from "@/lib/agents/types"
import type { ModelSelection } from "@/lib/agents/provider/useModelOptions"
import { AgentGitPanel } from "@/components/agents/AgentGitPanel"
import { AgentPromptBar } from "@/components/agents/AgentPromptBar"
import { Messages } from "@/components/agents/messages"
import { streamMessagesToUi } from "@/lib/agents/streamMessagesToUi"
import { useSubmitAgentMessage } from "@/lib/agents/provider/useSubmitAgentMessage"
import { useModelOptions } from "@/lib/agents/provider/useModelOptions"
import { AgentsApiError, agentsApi } from "@/lib/agents/api"
import { agentThreadKeys } from "@/lib/agents/queries"

interface AgentThreadViewProps {
  thread: AgentThread
}

interface QueuedFollowUp {
  id: string
  text: string
  imageCount: number
}

function userMessageText(message: Message): string {
  return message.chunks
    .filter((chunk) => chunk.kind === "text")
    .map((chunk) => chunk.text)
    .join("")
    .trim()
}

// The stream lives at the `/agents` layout (one persistent provider that
// survives the home → thread navigation), so this view only consumes it.
export function AgentThreadView({ thread }: AgentThreadViewProps) {
  const sendMessage = useSubmitAgentMessage(thread.id)
  const stream = useAgentThreadStream()
  const queryClient = useQueryClient()

  const [snapshotting, setSnapshotting] = useState(false)
  const [snapshotError, setSnapshotError] = useState<string | null>(null)
  const handleRefreshChanges = useCallback(async () => {
    setSnapshotting(true)
    setSnapshotError(null)
    try {
      await agentsApi.snapshotWorkspace(thread.id)
      await queryClient.invalidateQueries({
        queryKey: agentThreadKeys.detail(thread.id),
      })
      await queryClient.invalidateQueries({
        queryKey: agentThreadKeys.all,
        exact: true,
      })
    } catch (err) {
      setSnapshotError(
        err instanceof AgentsApiError ? err.message : "workspace_snapshot_failed"
      )
    } finally {
      setSnapshotting(false)
    }
  }, [queryClient, thread.id])

  const { models, defaultSelection } = useModelOptions()
  const threadSelection = useMemo<ModelSelection | null>(() => {
    if (!thread.model || !thread.effort) return null
    const supported = models.some(
      (m) => m.id === thread.model && m.efforts.includes(thread.effort ?? "")
    )
    if (!supported) return null
    return { modelId: thread.model, effort: thread.effort }
  }, [models, thread.model, thread.effort])
  const [selection, setSelection] = useState<ModelSelection | null>(null)
  const activeSelection = selection ?? threadSelection ?? defaultSelection
  const [queuedFollowUps, setQueuedFollowUps] = useState<Array<QueuedFollowUp>>([])
  // Directed follow-ups (the "Dirigir" action) are injected into the active run
  // server-side, so they don't echo through the SDK's optimistic submit. Mirror
  // top-agent UX by surfacing the directed message as a user bubble immediately;
  // it's deduped by id/text against the hydrated transcript (see below).
  const [directedOptimistic, setDirectedOptimistic] = useState<Array<Message>>([])
  // The interrupt id the user has already approved/rejected (to hide its card).
  const [resolvedInterruptId, setResolvedInterruptId] = useState<string | null>(null)

  const refreshQueuedFollowUps = useCallback(async () => {
    const queued = await agentsApi.getQueuedMessages(thread.id)
    setQueuedFollowUps(
      queued.messages.map((message) => ({
        id: message.id,
        text: message.text.trim(),
        imageCount: message.image_count,
      }))
    )
  }, [thread.id])

  const baseMessages = useMemo<Array<Message>>(() => {
    const live = streamMessagesToUi(stream.messages, stream.toolCalls, stream.subagents)
    // Optimistic transcript seeded by `AgentsHome` on thread creation (the
    // only case where a fetched thread carries messages — `getThread` returns
    // none). Bridges the brief gap before the SDK's optimistic `submit` echo
    // lands in `stream.messages`.
    const base = live.length > 0 ? live : thread.messages.length > 0 ? thread.messages : live
    if (directedOptimistic.length === 0) return base
    // Append directed follow-ups that haven't yet landed in the real transcript
    // (deduped by id and by committed user text), so they show as the latest
    // user turn the instant "Dirigir" is pressed.
    const seenIds = new Set(base.map((message) => message.id))
    const seenTexts = new Set(
      base.filter((message) => message.author === "user").map(userMessageText).filter(Boolean)
    )
    const pending = directedOptimistic.filter(
      (message) => !seenIds.has(message.id) && !seenTexts.has(userMessageText(message))
    )
    return pending.length > 0 ? [...base, ...pending] : base
  }, [
    stream.messages,
    stream.toolCalls,
    stream.subagents,
    thread.messages,
    directedOptimistic,
  ])

  // Prune optimistic directed messages once the real one lands in the live
  // stream (matched by id, or by text for the start-a-new-run path).
  useEffect(() => {
    setDirectedOptimistic((current) => {
      if (current.length === 0) return current
      const live = streamMessagesToUi(stream.messages, stream.toolCalls, stream.subagents)
      const liveIds = new Set(live.map((message) => message.id))
      const liveTexts = new Set(
        live.filter((message) => message.author === "user").map(userMessageText).filter(Boolean)
      )
      const next = current.filter(
        (message) => !liveIds.has(message.id) && !liveTexts.has(userMessageText(message))
      )
      return next.length === current.length ? current : next
    })
  }, [stream.messages, stream.toolCalls, stream.subagents])

  useEffect(() => {
    let cancelled = false
    setDirectedOptimistic([])
    setResolvedInterruptId(null)

    async function loadQueuedFollowUps() {
      try {
        const queued = await agentsApi.getQueuedMessages(thread.id)
        if (cancelled) return
        setQueuedFollowUps(
          queued.messages.map((message) => ({
            id: message.id,
            text: message.text.trim(),
            imageCount: message.image_count,
          }))
        )
      } catch (error) {
        console.warn("Could not load queued follow-up messages", error)
      }
    }

    void loadQueuedFollowUps()
    return () => {
      cancelled = true
    }
  }, [thread.id])

  useEffect(() => {
    const committedUserTexts = new Set(
      baseMessages
        .filter((message) => message.author === "user")
        .map(userMessageText)
        .filter(Boolean)
    )
    if (committedUserTexts.size === 0) return

    setQueuedFollowUps((current) => {
      const next = current.filter(
        (followUp) => !followUp.text || !committedUserTexts.has(followUp.text)
      )
      return next.length === current.length ? current : next
    })
  }, [baseMessages])

  useEffect(() => {
    function handleQueuedContinuation(event: Event) {
      const detail = (event as CustomEvent<{ threadId?: string }>).detail
      if (detail.threadId === thread.id) {
        setQueuedFollowUps([])
      }
    }

    window.addEventListener("agent-thread-queued-continued", handleQueuedContinuation)
    return () => {
      window.removeEventListener("agent-thread-queued-continued", handleQueuedContinuation)
    }
  }, [thread.id])

  const hasMessages = baseMessages.length > 0
  const isStreaming = thread.status === "running" || stream.isLoading
  const isThinking = stream.isLoading
  const settingUpSandbox = isThinking && baseMessages.length === 0
  // Surface a run-level failure (live SDK error, or a hydrated `error` status)
  // so a failed agent turn doesn't just stop in silence.
  const streamError = (stream as unknown as { error?: unknown }).error
  // A user Stop (or a paused HITL run) reports "interrupted" — neutral, not a
  // failure. Don't render the abort as a red error banner.
  const runStopped = !isStreaming && thread.status === "interrupted"
  const runError =
    !isStreaming && !runStopped && (Boolean(streamError) || thread.status === "error")
      ? thread.errorMessage
        ? thread.errorMessage
        : streamError instanceof Error
          ? streamError.message
          : typeof streamError === "string" && streamError
            ? streamError
            : "El modelo o el sandbox fallaron. Revisa la traza o reintenta."
      : null
  const lastUserText = useMemo(() => {
    for (let index = baseMessages.length - 1; index >= 0; index--) {
      const message = baseMessages[index]
      if (message && message.author === "user") return userMessageText(message)
    }
    return ""
  }, [baseMessages])
  const isWorkspaceThread = Boolean(thread.workspaceId ?? thread.workspaceLabel)
  const handleRetry = () => {
    if (!lastUserText || isStreaming || sendMessage.isPending) return
    sendMessage.mutate({
      content: lastUserText,
      images: [],
      model_id: activeSelection?.modelId ?? null,
      effort: activeSelection?.effort ?? null,
    })
  }

  // Human-approval gate: when the engine pauses on a gated tool call, the SDK
  // surfaces a LangGraph interrupt whose value is the HITL request. Render it as
  // an approval card and resume the run with one decision per pending action.
  const approvalValue = stream.interrupt?.value as
    | {
        action_requests?: Array<{
          name?: string
          args?: Record<string, unknown>
          description?: string
        }>
      }
    | undefined
  const approvalActions = approvalValue?.action_requests ?? []
  const currentInterruptId = stream.interrupt?.id ?? null
  // The resume runs as a *new* run, so the original run's __interrupt__ lingers in
  // stream.interrupt; hide the card once its interrupt has been acted on.
  const showApproval = approvalActions.length > 0 && currentInterruptId !== resolvedInterruptId
  const handleApproval = (type: "approve" | "reject") => {
    const count = approvalActions.length || 1
    const decisions = Array.from({ length: count }, () => ({ type }))
    setResolvedInterruptId(currentInterruptId)
    // Resume server-side via Command(resume=...). The SDK's respond() over the
    // stateless SSE /commands transport fails interrupt validation
    // ("already-consumed"); the dashboard /resume endpoint creates the run.
    void agentsApi.resumeInterrupt(thread.id, decisions)
  }
  // The transcript hydrates from the SDK (`GET …/state` → `stream.messages`).
  // Show a loading state during that one-time fetch instead of the empty state.
  const isHydrating = stream.isThreadLoading && !hasMessages

  const handleClearQueuedFollowUps = async () => {
    await agentsApi.clearQueuedMessages(thread.id)
    setQueuedFollowUps([])
  }

  const handleDiscardQueuedFollowUp = async (messageId: string) => {
    const result = await agentsApi.deleteQueuedMessage(thread.id, messageId)
    setQueuedFollowUps(
      result.messages.map((message) => ({
        id: message.id,
        text: message.text.trim(),
        imageCount: message.image_count,
      }))
    )
  }

  const handleDirectQueuedFollowUp = async (messageId: string) => {
    // Surface the directed message as a user bubble right away so it never
    // vanishes from the queue into a void (pruned once the real one hydrates).
    const followUp = queuedFollowUps.find((item) => item.id === messageId)
    if (followUp?.text) {
      setDirectedOptimistic((current) => [
        ...current.filter((message) => message.id !== messageId),
        {
          id: messageId,
          author: "user",
          timestamp: new Date().toISOString(),
          chunks: [{ kind: "text", text: followUp.text }],
        },
      ])
    }
    try {
      const result = await agentsApi.directQueuedMessage(thread.id, messageId)
      if (result.status === "started" || result.status === "empty") {
        await refreshQueuedFollowUps()
      } else {
        setQueuedFollowUps(
          result.queued.messages
            .filter((message) => message.id !== messageId)
            .map((message) => ({
              id: message.id,
              text: message.text.trim(),
              imageCount: message.image_count,
            }))
        )
      }
    } catch (error) {
      // Roll back the optimistic bubble if directing failed.
      setDirectedOptimistic((current) => current.filter((message) => message.id !== messageId))
      if (error instanceof AgentsApiError && error.status === 409) return
      throw error
    }
  }

  return (
    <div className="flex min-w-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="shrink-0 px-4 pt-3">
          <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--ui-border)] bg-[var(--ui-panel-2)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--ui-text-muted)]">
              {isWorkspaceThread
                ? `Workspace · ${thread.workspaceLabel ?? "repo"}${
                    thread.workspaceBranch ? ` · ${thread.workspaceBranch}` : ""
                  }`
                : "Sin workspace"}
            </span>
            {isWorkspaceThread ? (
              <div className="flex items-center gap-2">
                {thread.diffStats ? (
                  <span className="text-[11px] font-medium text-[color:var(--ui-text-muted)]">
                    {thread.diffStats.files}{" "}
                    {thread.diffStats.files === 1 ? "archivo" : "archivos"}{" "}
                    <span className="text-[var(--ui-success)]">
                      +{thread.diffStats.additions}
                    </span>{" "}
                    <span className="text-[var(--ui-danger)]">
                      -{thread.diffStats.deletions}
                    </span>
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={handleRefreshChanges}
                  disabled={snapshotting}
                  className="rounded-full border border-[var(--ui-border)] bg-[var(--ui-panel-2)] px-2.5 py-1 text-[11px] font-medium text-[color:var(--ui-text-muted)] transition-colors hover:border-[var(--ui-accent)]/40 disabled:opacity-50"
                >
                  {snapshotting ? "Actualizando…" : "Actualizar cambios"}
                </button>
              </div>
            ) : null}
          </div>
          {snapshotError ? (
            <div className="mx-auto mt-1 w-full max-w-3xl text-[11px] text-red-300">
              {snapshotError}
            </div>
          ) : null}
        </div>
        {hasMessages ? (
          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
            <Messages
              messages={baseMessages}
              isStreaming={isStreaming}
              streamIsLoading={stream.isLoading}
              isThinking={isThinking}
              settingUpSandbox={settingUpSandbox}
              contentWidthClass="max-w-3xl"
            />
            {showApproval ? (
              <div className="shrink-0 px-4 pb-2">
                <div className="mx-auto w-full max-w-3xl rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-200">
                  <p className="font-medium">Aprobación requerida</p>
                  <p className="mt-0.5 break-words opacity-90">
                    {approvalActions[0]?.description ??
                      `El agente quiere ejecutar una acción persistente (${
                        approvalActions[0]?.name ?? "acción"
                      }) y necesita tu aprobación.`}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      onClick={() => handleApproval("approve")}
                      className="rounded-md bg-amber-400/90 px-2.5 py-1 text-[11px] font-medium text-black hover:bg-amber-300"
                    >
                      Aprobar
                    </button>
                    <button
                      type="button"
                      onClick={() => handleApproval("reject")}
                      className="rounded-md border border-amber-400/40 px-2.5 py-1 text-[11px] font-medium text-amber-200 hover:bg-amber-500/10"
                    >
                      Rechazar
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
            {runError ? (
              <div className="shrink-0 px-4 pb-2">
                <div className="mx-auto flex w-full max-w-3xl items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
                  <span className="mt-0.5">⚠️</span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">El agente se detuvo por un error</p>
                    <p className="mt-0.5 break-words opacity-90">{runError}</p>
                    {thread.traceUrl ? (
                      <a
                        href={thread.traceUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-block underline opacity-80 hover:opacity-100"
                      >
                        Ver traza
                      </a>
                    ) : null}
                  </div>
                  {lastUserText ? (
                    <button
                      type="button"
                      onClick={handleRetry}
                      disabled={sendMessage.isPending}
                      className="shrink-0 rounded-md border border-red-400/40 px-2 py-1 text-[11px] font-medium text-red-200 hover:bg-red-500/10 disabled:opacity-40"
                    >
                      Reintentar
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}
            {runStopped ? (
              <div className="shrink-0 px-4 pb-2">
                <div className="mx-auto flex w-full max-w-3xl items-center gap-2 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-panel-2)] px-3 py-2 text-[12px] text-[color:var(--ui-text-muted)]">
                  <span>⏹</span>
                  <span>Ejecución detenida por el usuario.</span>
                </div>
              </div>
            ) : null}
            <div className="shrink-0 px-4 pb-4">
              <div className="mx-auto w-full min-w-0 max-w-3xl">
                <AgentPromptBar
                  placeholder="Escribe un seguimiento"
                  compact
                  busy={isStreaming}
                  disabled={sendMessage.isPending}
                  queuedFollowUps={queuedFollowUps}
                  onQueuedDiscard={handleDiscardQueuedFollowUp}
                  onQueuedClearAll={handleClearQueuedFollowUps}
                  onQueuedDirect={handleDirectQueuedFollowUp}
                  onSubmit={(content, images) =>
                    sendMessage.mutate({
                      content,
                      images,
                      model_id: activeSelection?.modelId ?? null,
                      effort: activeSelection?.effort ?? null,
                    }, {
                      onSuccess: (result) => {
                        if (result.queued) {
                          void refreshQueuedFollowUps()
                        }
                      },
                    })
                  }
                  models={models}
                  selection={activeSelection}
                  onSelectionChange={setSelection}
                />
              </div>
            </div>
          </div>
        ) : isHydrating ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6">
            <p className="text-sm text-[var(--ui-text-dim)]">Cargando conversación…</p>
          </div>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6">
            <p className="text-sm text-[var(--ui-text-dim)]">
              Este hilo aún no tiene mensajes.
            </p>
            <div className="w-full max-w-3xl">
              <AgentPromptBar
                placeholder="Envía el primer mensaje"
                compact
                busy={isStreaming}
                disabled={sendMessage.isPending}
                queuedFollowUps={queuedFollowUps}
                onQueuedDiscard={handleDiscardQueuedFollowUp}
                onQueuedClearAll={handleClearQueuedFollowUps}
                onQueuedDirect={handleDirectQueuedFollowUp}
                onSubmit={(content, images) =>
                  sendMessage.mutate({
                    content,
                    images,
                    model_id: activeSelection?.modelId ?? null,
                    effort: activeSelection?.effort ?? null,
                  }, {
                    onSuccess: (result) => {
                      if (result.queued) {
                        void refreshQueuedFollowUps()
                      }
                    },
                  })
                }
                models={models}
                selection={activeSelection}
                onSelectionChange={setSelection}
              />
            </div>
          </div>
        )}
      </div>
      <AgentGitPanel thread={thread} messages={baseMessages} />
    </div>
  )
}
