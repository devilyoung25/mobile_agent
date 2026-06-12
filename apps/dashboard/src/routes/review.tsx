import { Navigate, createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { GitPullRequestIcon, ArrowSquareOutIcon } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api";
import type { AzurePullRequest } from "@/lib/api";
import { useSession } from "@/lib/session";

export const Route = createFileRoute("/review")({ component: PullRequestsPage });

function isNotAuthorized(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 403 || e.status === 401);
}

function formatDate(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" });
}

function PullRequestsPage() {
  const session = useSession();
  const [project, setProject] = useState<string | null>(null);

  const projects = useQuery({
    queryKey: ["azureProjects"],
    queryFn: api.azureProjects,
    enabled: !!session.data,
    retry: false,
  });

  // Default to the first project once the list resolves.
  useEffect(() => {
    const first = projects.data?.[0];
    if (!project && first) setProject(first.name);
  }, [project, projects.data]);

  const prs = useQuery({
    queryKey: ["azurePullRequests", project],
    queryFn: () => api.azurePullRequests(project as string),
    enabled: !!session.data && !!project,
    retry: false,
  });

  if (session.isLoading) {
    return (
      <main className="p-6">
        <Skeleton className="h-64 w-full" />
      </main>
    );
  }
  if (!session.data) return <Navigate to="/login" />;

  const notAuthorized = isNotAuthorized(projects.error) || isNotAuthorized(prs.error);

  return (
    <AppShell
      user={session.data}
      title="Pull Requests"
      description="Pull requests abiertos en tus proyectos de Azure DevOps. Solo lectura — los datos vienen en vivo de Azure."
    >
      {notAuthorized ? (
        <div className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">
          No tienes acceso a Azure DevOps todavía. Vuelve a iniciar sesión para
          conceder el permiso y poder ver los pull requests.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-muted-foreground">Proyecto</span>
            <Select
              value={project ?? undefined}
              onValueChange={(v) => v && setProject(v)}
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
          </div>

          <div className="rounded-lg border border-border bg-card">
            {prs.isLoading || projects.isLoading ? (
              <div className="space-y-2 p-4">
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </div>
            ) : (prs.data?.pull_requests.length ?? 0) === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-muted-foreground">
                No hay pull requests abiertos en este proyecto.
              </p>
            ) : (
              <div className="divide-y divide-border">
                {prs.data?.pull_requests.map((pr) => (
                  <PullRequestRow key={pr.id} pr={pr} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}

function PullRequestRow({ pr }: { pr: AzurePullRequest }) {
  const body = (
    <div className="flex items-start gap-3 px-4 py-3">
      <GitPullRequestIcon className="mt-0.5 size-4 shrink-0 text-[color:var(--onoff-green)]" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{pr.title}</span>
          {pr.is_draft && (
            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              Borrador
            </span>
          )}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          <span className="font-medium">!{pr.id}</span>
          {pr.repo && <span>· {pr.repo}</span>}
          {pr.author && <span>· {pr.author}</span>}
          {pr.source_branch && pr.target_branch && (
            <span className="truncate">
              · {pr.source_branch} → {pr.target_branch}
            </span>
          )}
          {pr.created_date && <span>· {formatDate(pr.created_date)}</span>}
        </div>
      </div>
      {pr.web_url && (
        <ArrowSquareOutIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      )}
    </div>
  );

  if (pr.web_url) {
    return (
      <a
        href={pr.web_url}
        target="_blank"
        rel="noopener noreferrer"
        className="block transition-colors hover:bg-muted/40"
      >
        {body}
      </a>
    );
  }
  return <div>{body}</div>;
}
