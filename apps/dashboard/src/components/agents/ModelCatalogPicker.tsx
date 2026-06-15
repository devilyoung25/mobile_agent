import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import type { ModelCatalog } from "@/lib/api"
import { api } from "@/lib/api"
import { useSession } from "@/lib/session"

interface ModelCatalogPickerProps {
  selectedModelId: string | null
  onSelect: (modelId: string, defaultEffort?: string) => void
}

/**
 * Provider-tabbed model picker driven by the gateway catalog. Models that the
 * gateway reports as unavailable (rate-limited / no access) render greyed out
 * and are not selectable.
 */
export function ModelCatalogPicker({ selectedModelId, onSelect }: ModelCatalogPickerProps) {
  const session = useSession()
  const { data } = useQuery<ModelCatalog>({
    queryKey: ["model-catalog"],
    queryFn: api.modelCatalog,
    enabled: !!session.data,
    refetchInterval: 60_000, // pick up availability changes (rate-limit recovery)
  })

  const providers = data?.providers ?? []
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null)
  const active = useMemo(
    () => providers.find((p) => p.id === activeProviderId) ?? providers[0],
    [providers, activeProviderId],
  )

  if (providers.length === 0) return null

  return (
    <div className="flex w-full max-w-2xl flex-col gap-2">
      {providers.length > 1 && (
        <div className="flex items-center gap-1 self-center rounded-full border border-[var(--ui-border)] bg-[var(--ui-panel-2)] p-0.5 text-[11px]">
          {providers.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setActiveProviderId(p.id)}
              className={
                active?.id === p.id
                  ? "rounded-full bg-[var(--ui-accent)]/20 px-2.5 py-1 font-medium text-[color:var(--ui-text)]"
                  : "rounded-full px-2.5 py-1 text-[color:var(--ui-text-muted)] hover:text-[color:var(--ui-text)]"
              }
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        {active?.models.map((m) => {
          const selected = m.id === selectedModelId
          const disabled = !m.available
          return (
            <button
              key={m.id}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(m.id, m.default_effort)}
              title={disabled ? "No disponible (rate limit o sin acceso)" : m.id}
              className={[
                "rounded-md border px-2.5 py-1 text-[11px] transition-colors",
                disabled
                  ? "cursor-not-allowed border-[var(--ui-border)] text-[var(--ui-text-dim)] opacity-50 line-through"
                  : selected
                    ? "border-[var(--ui-accent)] bg-[var(--ui-accent)]/15 text-[color:var(--ui-text)]"
                    : "border-[var(--ui-border)] text-[color:var(--ui-text-muted)] hover:border-[var(--ui-accent)]/40",
              ].join(" ")}
            >
              {m.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
