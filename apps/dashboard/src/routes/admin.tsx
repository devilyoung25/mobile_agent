import { Navigate, createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type {
  DatadogConnectBody,
  LangSmithConnectBody,
  ModelOption,
  TeamSettings,
} from "@/lib/api";
import { AppShell, SettingsRow, SettingsSection } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export const Route = createFileRoute("/admin")({ component: AdminPage });

function AdminPage() {
  const session = useSession();

  const options = useQuery({
    queryKey: ["options"],
    queryFn: api.options,
    enabled: !!session.data?.is_admin,
  });

  if (session.isLoading) {
    return (
      <main className="p-6">
        <Skeleton className="h-64 w-full" />
      </main>
    );
  }
  if (!session.data) return <Navigate to="/login" />;
  if (!session.data.is_admin) return <Navigate to="/my-settings" />;

  return (
    <AppShell
      user={session.data}
      title="Administración"
      description="Valores predeterminados y credenciales de todo el espacio de trabajo."
    >
      <GlobalDefaultsSection models={options.data?.models ?? []} />

      <ObservabilityCredentialsSection />
    </AppShell>
  );
}

function ObservabilityCredentialsSection() {
  const qc = useQueryClient();
  const creds = useQuery({
    queryKey: ["teamCredentials"],
    queryFn: api.getTeamCredentials,
  });
  const [error, setError] = useState<string | null>(null);

  const [ddSite, setDdSite] = useState("datadoghq.com");
  const [ddApiKey, setDdApiKey] = useState("");
  const [ddAppKey, setDdAppKey] = useState("");
  const [lsApiKey, setLsApiKey] = useState("");
  const [lsEndpoint, setLsEndpoint] = useState("");

  const onError = (e: Error) => setError(e.message);
  const onSuccess = (saved: Awaited<ReturnType<typeof api.getTeamCredentials>>) => {
    qc.setQueryData(["teamCredentials"], saved);
    setError(null);
  };

  const connectDd = useMutation({
    mutationFn: (body: DatadogConnectBody) => api.connectDatadog(body),
    onSuccess: (saved) => {
      onSuccess(saved);
      setDdApiKey("");
      setDdAppKey("");
    },
    onError,
  });
  const disconnectDd = useMutation({
    mutationFn: () => api.disconnectDatadog(),
    onSuccess,
    onError,
  });
  const connectLs = useMutation({
    mutationFn: (body: LangSmithConnectBody) => api.connectLangSmith(body),
    onSuccess: (saved) => {
      onSuccess(saved);
      setLsApiKey("");
    },
    onError,
  });
  const disconnectLs = useMutation({
    mutationFn: () => api.disconnectLangSmith(),
    onSuccess,
    onError,
  });

  const datadog = creds.data?.datadog;
  const langsmith = creds.data?.langsmith;
  const busy = creds.isLoading;

  return (
    <SettingsSection
      title="Credenciales de observabilidad"
      description="Credenciales de Datadog y LangSmith para todo el equipo. Se guardan cifradas en el servidor y nunca se exponen al sandbox. Conectarlas habilita herramientas de observabilidad de solo lectura para las ejecuciones del agente."
    >
      <div className="divide-y divide-border">
        <SettingsRow
          label="Datadog"
          description={
            datadog?.connected
              ? `Conectado · ${datadog.site ?? ""} · clave ••••${datadog.api_key_last4 ?? ""}`
              : "Conecta Datadog para habilitar métricas, logs, trazas y monitores de solo lectura."
          }
          control={
            datadog?.connected ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => disconnectDd.mutate()}
                disabled={disconnectDd.isPending}
              >
                Desconectar
              </Button>
            ) : (
              <div className="flex flex-col items-end gap-2">
                <Input
                  className="w-56"
                  placeholder="datadoghq.com"
                  value={ddSite}
                  onChange={(e) => setDdSite(e.target.value)}
                  disabled={busy}
                />
                <Input
                  className="w-56"
                  placeholder="Clave de API"
                  type="password"
                  value={ddApiKey}
                  onChange={(e) => setDdApiKey(e.target.value)}
                  disabled={busy}
                />
                <Input
                  className="w-56"
                  placeholder="Clave de aplicación"
                  type="password"
                  value={ddAppKey}
                  onChange={(e) => setDdAppKey(e.target.value)}
                  disabled={busy}
                />
                <Button
                  size="sm"
                  onClick={() =>
                    connectDd.mutate({
                      site: ddSite.trim(),
                      api_key: ddApiKey.trim(),
                      app_key: ddAppKey.trim(),
                    })
                  }
                  disabled={
                    connectDd.isPending ||
                    !ddSite.trim() ||
                    !ddApiKey.trim() ||
                    !ddAppKey.trim()
                  }
                >
                  Conectar
                </Button>
              </div>
            )
          }
        />
        <SettingsRow
          label="LangSmith"
          description={
            langsmith?.connected
              ? `Conectado · clave ••••${langsmith.api_key_last4 ?? ""}${langsmith.endpoint ? ` · ${langsmith.endpoint}` : ""}`
              : "Conecta LangSmith para habilitar herramientas de solo lectura de trazas y consulta de ejecuciones."
          }
          control={
            langsmith?.connected ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => disconnectLs.mutate()}
                disabled={disconnectLs.isPending}
              >
                Desconectar
              </Button>
            ) : (
              <div className="flex flex-col items-end gap-2">
                <Input
                  className="w-56"
                  placeholder="Clave de API"
                  type="password"
                  value={lsApiKey}
                  onChange={(e) => setLsApiKey(e.target.value)}
                  disabled={busy}
                />
                <Input
                  className="w-56"
                  placeholder="Endpoint (opcional)"
                  value={lsEndpoint}
                  onChange={(e) => setLsEndpoint(e.target.value)}
                  disabled={busy}
                />
                <Button
                  size="sm"
                  onClick={() =>
                    connectLs.mutate({
                      api_key: lsApiKey.trim(),
                      endpoint: lsEndpoint.trim() || null,
                    })
                  }
                  disabled={connectLs.isPending || !lsApiKey.trim()}
                >
                  Conectar
                </Button>
              </div>
            )
          }
        />
      </div>
      {error && <p className="px-4 pb-3 text-xs text-destructive">{error}</p>}
    </SettingsSection>
  );
}

function GlobalDefaultsSection({ models }: { models: Array<ModelOption> }) {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["teamSettings"],
    queryFn: api.getTeamSettings,
  });
  const [error, setError] = useState<string | null>(null);
  const [defaultRepoDraft, setDefaultRepoDraft] = useState("");

  useEffect(() => {
    setDefaultRepoDraft(settings.data?.default_repo ?? "");
  }, [settings.data?.default_repo]);

  const save = useMutation({
    mutationFn: (body: TeamSettings) => api.saveTeamSettings(body),
    onSuccess: (saved) => {
      qc.setQueryData(["teamSettings"], saved);
      setError(null);
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <SettingsSection
      title="Valores predeterminados globales"
      description="Modelos predeterminados para todo el espacio de trabajo. Las selecciones por usuario del Agente en la nube tienen prioridad sobre estos valores."
    >
      <div className="divide-y divide-border">
        <RolePicker
          label="Agente"
          description="Modelo usado en las ejecuciones de escritura de código disparadas desde Slack, Linear, GitHub y el agente."
          models={models}
          model={settings.data?.default_agent_model ?? null}
          effort={settings.data?.default_agent_reasoning_effort ?? null}
          onChange={(model, effort) =>
            settings.data &&
            save.mutate({
              ...settings.data,
              default_agent_model: model,
              default_agent_reasoning_effort: effort,
            })
          }
          disabled={!settings.data || save.isPending}
        />
        <RolePicker
          label="Subagentes del agente"
          description="Modelo usado por las tareas delegadas del agente principal."
          models={models}
          model={settings.data?.default_agent_subagent_model ?? null}
          effort={settings.data?.default_agent_subagent_reasoning_effort ?? null}
          onChange={(model, effort) =>
            settings.data &&
            save.mutate({
              ...settings.data,
              default_agent_subagent_model: model,
              default_agent_subagent_reasoning_effort: effort,
            })
          }
          disabled={!settings.data || save.isPending}
        />
        <SettingsRow
          label="Repositorio predeterminado"
          description="Reserva global usada cuando una ejecución no tiene repo explícito y el usuario no tiene uno predeterminado en su perfil. Usa owner/repo."
          control={
            <Input
              className="w-56"
              placeholder="owner/repo"
              value={defaultRepoDraft}
              onChange={(e) => setDefaultRepoDraft(e.target.value)}
              onBlur={() =>
                settings.data &&
                save.mutate({
                  ...settings.data,
                  default_repo: defaultRepoDraft.trim() || null,
                })
              }
              disabled={!settings.data || save.isPending}
            />
          }
        />
        <RolePicker
          label="Revisor de código"
          description="Modelo usado en las ejecuciones de revisión de PR."
          models={models}
          model={settings.data?.default_reviewer_model ?? null}
          effort={settings.data?.default_reviewer_reasoning_effort ?? null}
          onChange={(model, effort) =>
            settings.data &&
            save.mutate({
              ...settings.data,
              default_reviewer_model: model,
              default_reviewer_reasoning_effort: effort,
            })
          }
          disabled={!settings.data || save.isPending}
        />
        <RolePicker
          label="Subagentes del revisor"
          description="Modelo usado por las tareas delegadas del revisor."
          models={models}
          model={settings.data?.default_reviewer_subagent_model ?? null}
          effort={settings.data?.default_reviewer_subagent_reasoning_effort ?? null}
          onChange={(model, effort) =>
            settings.data &&
            save.mutate({
              ...settings.data,
              default_reviewer_subagent_model: model,
              default_reviewer_subagent_reasoning_effort: effort,
            })
          }
          disabled={!settings.data || save.isPending}
        />
      </div>
      {error && <p className="px-4 pb-3 text-xs text-destructive">{error}</p>}
    </SettingsSection>
  );
}

interface RolePickerProps {
  label: string;
  description: string;
  models: Array<ModelOption>;
  model: string | null;
  effort: string | null;
  onChange: (model: string, effort: string) => void;
  disabled: boolean;
}

function RolePicker({
  label,
  description,
  models,
  model,
  effort,
  onChange,
  disabled,
}: RolePickerProps) {
  const [localModel, setLocalModel] = useState<string>(model ?? "");
  const [localEffort, setLocalEffort] = useState<string>(effort ?? "");

  useEffect(() => {
    setLocalModel(model ?? "");
    setLocalEffort(effort ?? "");
  }, [model, effort]);

  const selectedModel = models.find((m) => m.id === localModel);
  const availableEfforts = selectedModel?.efforts ?? [];

  const handleModelChange = (value: string | null) => {
    if (!value) return;
    const nextModel = models.find((m) => m.id === value);
    if (!nextModel) return;
    const nextEffort = nextModel.efforts.includes(localEffort)
      ? localEffort
      : nextModel.default_effort;
    setLocalModel(value);
    setLocalEffort(nextEffort);
    onChange(value, nextEffort);
  };

  const handleEffortChange = (value: string | null) => {
    if (!value || !localModel) return;
    setLocalEffort(value);
    onChange(localModel, value);
  };

  return (
    <SettingsRow
      label={label}
      description={description}
      control={
        <div className="flex items-center gap-2">
          <Select value={localModel} onValueChange={handleModelChange} disabled={disabled}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={localEffort}
            onValueChange={handleEffortChange}
            disabled={disabled || !localModel}
          >
            <SelectTrigger className="w-28">
              <SelectValue placeholder="effort" />
            </SelectTrigger>
            <SelectContent>
              {availableEfforts.map((e) => (
                <SelectItem key={e} value={e}>
                  {e}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      }
    />
  );
}
