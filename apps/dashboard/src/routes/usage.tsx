import { Navigate, createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  ChartBarIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import { AppShell, SettingsSection } from "@/components/AppShell";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api";
import type {
  AzureBuild,
  AzureUsageCounterRow,
  AzureUsagePeriod,
} from "@/lib/api";
import { useSession } from "@/lib/session";

export const Route = createFileRoute("/usage")({
  validateSearch: (search: Record<string, unknown>) => ({
    period: typeof search.period === "string" ? search.period : undefined,
    project: typeof search.project === "string" ? search.project : undefined,
  }),
  component: AzureUsagePage,
});

const PERIOD_LABELS: Record<AzureUsagePeriod, string> = {
  "7d": "Últimos 7 días",
  "30d": "Últimos 30 días",
  all: "Todo",
};

function isNotAuthorized(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

function AzureUsagePage() {
  const session = useSession();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const requestedPeriod = search.period as AzureUsagePeriod | undefined;
  const activePeriod: AzureUsagePeriod = ["7d", "30d", "all"].includes(
    requestedPeriod ?? "",
  )
    ? requestedPeriod!
    : "30d";
  const [project, setProject] = useState<string | null>(
    typeof search.project === "string" ? search.project : null,
  );

  const projects = useQuery({
    queryKey: ["azureProjects"],
    queryFn: api.azureProjects,
    enabled: !!session.data,
    retry: false,
  });

  useEffect(() => {
    const first = projects.data?.[0];
    if (!project && first) setProject(first.name);
  }, [project, projects.data]);

  const usage = useQuery({
    queryKey: ["azureUsage", project, activePeriod],
    queryFn: () => api.azureUsage(project as string, activePeriod),
    enabled: !!session.data && !!project,
    retry: false,
    staleTime: 2 * 60 * 1000,
  });

  const buildSummary = useMemo(
    () => summarizeBuilds(usage.data?.recent_builds ?? []),
    [usage.data?.recent_builds],
  );

  if (session.isLoading) {
    return (
      <main className="p-6">
        <Skeleton className="h-64 w-full" />
      </main>
    );
  }
  if (!session.data) return <Navigate to="/login" />;

  const notAuthorized = isNotAuthorized(projects.error) || isNotAuthorized(usage.error);

  return (
    <AppShell
      user={session.data}
      title="Uso Azure"
      description="Actividad read-only de Azure DevOps por proyecto: work items y builds recientes."
    >
      {notAuthorized ? (
        <div className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          No tienes acceso a Azure DevOps todavía. Vuelve a iniciar sesión para
          conceder el permiso y poder ver estas métricas.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-medium text-muted-foreground">Proyecto</span>
            <Select
              value={project ?? undefined}
              onValueChange={(value) => {
                if (!value) return;
                setProject(value);
                void navigate({
                  to: "/usage",
                  search: { project: value, period: activePeriod },
                });
              }}
              disabled={projects.isLoading || !projects.data?.length}
            >
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Elige un proyecto" />
              </SelectTrigger>
              <SelectContent>
                {(projects.data ?? []).map((p) => (
                  <SelectItem key={p.id} value={p.name}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <span className="ml-0 text-xs font-medium text-muted-foreground sm:ml-2">
              Periodo
            </span>
            <Select
              value={activePeriod}
              onValueChange={(value) =>
                navigate({
                  to: "/usage",
                  search: {
                    project: project ?? undefined,
                    period: value as AzureUsagePeriod,
                  },
                })
              }
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(PERIOD_LABELS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {projects.isLoading || usage.isLoading ? (
            <div className="grid gap-4 md:grid-cols-2">
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-64 w-full md:col-span-2" />
            </div>
          ) : usage.isError ? (
            <div className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
              No se pudo cargar Azure DevOps: {usage.error.message}
            </div>
          ) : !usage.data ? (
            <div className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
              Elige un proyecto para ver sus métricas.
            </div>
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <MetricCard
                  label="Work items"
                  value={usage.data.work_items.total}
                  helper={PERIOD_LABELS[activePeriod].toLowerCase()}
                  icon={<ChartBarIcon className="size-4" />}
                />
                <MetricCard
                  label="Builds OK"
                  value={buildSummary.succeeded}
                  helper="últimos builds"
                  icon={<CheckCircleIcon className="size-4" />}
                />
                <MetricCard
                  label="Builds fallidos"
                  value={buildSummary.failed}
                  helper="requieren revisión"
                  icon={<WarningCircleIcon className="size-4" />}
                />
                <MetricCard
                  label="En progreso"
                  value={buildSummary.inProgress}
                  helper="running / queued"
                  icon={<ClockCounterClockwiseIcon className="size-4" />}
                />
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <SettingsSection
                  title="Work items por estado"
                  description={
                    usage.data.work_items.limited
                      ? "Muestra los 500 work items más recientes del periodo."
                      : "Conteo de work items visibles para tu usuario."
                  }
                >
                  <CounterList rows={usage.data.work_items.states} empty="No hay work items." />
                </SettingsSection>

                <SettingsSection
                  title="Work items por tipo"
                  description="Distribución por Bug, Task, User Story u otros tipos configurados."
                >
                  <CounterList rows={usage.data.work_items.types} empty="No hay tipos para mostrar." />
                </SettingsSection>
              </div>

              <SettingsSection
                title="Builds recientes"
                description="Últimos builds visibles del proyecto seleccionado en Azure DevOps."
              >
                {usage.data.recent_builds.length ? (
                  <div className="divide-y divide-border">
                    {usage.data.recent_builds.map((build) => (
                      <BuildRow key={build.id} build={build} />
                    ))}
                  </div>
                ) : (
                  <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                    No hay builds recientes para este proyecto.
                  </p>
                )}
              </SettingsSection>
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}

function MetricCard({
  label,
  value,
  helper,
  icon,
}: {
  label: string;
  value: number;
  helper: string;
  icon: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className="text-[color:var(--onoff-green)]">{icon}</span>
      </div>
      <div className="mt-3 text-2xl font-semibold tabular-nums text-foreground">
        {formatNumber(value)}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{helper}</div>
    </div>
  );
}

function CounterList({
  rows,
  empty,
}: {
  rows: Array<AzureUsageCounterRow>;
  empty: string;
}) {
  if (!rows.length) {
    return <p className="px-4 py-8 text-center text-sm text-muted-foreground">{empty}</p>;
  }
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  return (
    <div className="divide-y divide-border">
      {rows.map((row) => {
        const percent = total ? Math.round((row.count / total) * 100) : 0;
        return (
          <div key={row.name} className="px-4 py-3">
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="truncate font-medium text-foreground">{row.name}</span>
              <span className="text-muted-foreground tabular-nums">
                {formatNumber(row.count)}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-[color:var(--onoff-green)]"
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BuildRow({ build }: { build: AzureBuild }) {
  const content = (
    <div className="flex items-start justify-between gap-4 px-4 py-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">
            {build.definition ?? "Build sin definición"}
          </span>
          <BuildBadge build={build} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          {build.build_number && <span>#{build.build_number}</span>}
          {build.source_branch && <span>· {build.source_branch}</span>}
          {build.requested_for && <span>· {build.requested_for}</span>}
          <span>· {formatDate(build.finish_time ?? build.start_time ?? build.queue_time)}</span>
        </div>
      </div>
    </div>
  );

  if (!build.web_url) return content;
  return (
    <a
      href={build.web_url}
      target="_blank"
      rel="noopener noreferrer"
      className="block transition-colors hover:bg-muted/40"
    >
      {content}
    </a>
  );
}

function BuildBadge({ build }: { build: AzureBuild }) {
  const value = build.result ?? build.status ?? "unknown";
  const label = translateBuildState(value);
  const variant = build.result === "succeeded" ? "default" : "secondary";
  return <Badge variant={variant}>{label}</Badge>;
}

function summarizeBuilds(builds: Array<AzureBuild>) {
  return builds.reduce(
    (summary, build) => {
      if (build.result === "succeeded") summary.succeeded += 1;
      else if (build.result && build.result !== "succeeded") summary.failed += 1;
      else if (build.status === "inProgress" || build.status === "notStarted") {
        summary.inProgress += 1;
      }
      return summary;
    },
    { succeeded: 0, failed: 0, inProgress: 0 },
  );
}

function translateBuildState(value: string): string {
  const labels: Record<string, string> = {
    canceled: "Cancelado",
    failed: "Fallido",
    inProgress: "En progreso",
    none: "Sin resultado",
    notStarted: "En cola",
    partiallySucceeded: "Parcial",
    succeeded: "OK",
  };
  return labels[value] ?? value;
}

function formatDate(value: string | null): string {
  if (!value) return "sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "sin fecha";
  return date.toLocaleDateString("es", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("es").format(value);
}
