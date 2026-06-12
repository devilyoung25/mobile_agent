import { useEffect, useRef, useState } from "react";

// Video-game-loading-screen energy, but make it Android dev. The agent shows a
// random one of these while it thinks — equal parts Gradle trauma and droid love.
const BUSY_TEXTS: Array<{ present: string; past: string }> = [
  { present: "esperando al daemon de Gradle...", past: "Gradle despertó" },
  {
    present: "descargando medio internet con Gradle...",
    past: "Dependencias descargadas",
  },
  { present: "resolviendo dependencias...", past: "Dependencias resueltas" },
  { present: "invalidando cachés y rezando...", past: "Cachés invalidadas" },
  { present: "levantando el emulador...", past: "Emulador listo" },
  {
    present: "esperando a que el emulador deje de sufrir...",
    past: "Emulador sobrevivió",
  },
  { present: "acariciando a Bugdroid...", past: "Bugdroid motivado" },
  { present: "esquivando un NullPointerException...", past: "NPE esquivado" },
  { present: "subiendo el targetSdkVersion...", past: "targetSdk actualizado" },
  {
    present: "consultando el oráculo de Stack Overflow...",
    past: "Oráculo consultado",
  },
  { present: "aplastando bugs...", past: "Bugs aplastados" },
  { present: "domando reglas de ProGuard...", past: "ProGuard domesticado" },
  { present: "peleando con R8...", past: "R8 cooperó" },
  {
    present: "alineando píxeles a la grilla de 8dp...",
    past: "Píxeles alineados",
  },
  { present: "corriendo ./gradlew clean otra vez...", past: "Gradle limpiado" },
  { present: "convenciendo al build de pasar...", past: "Build convencido" },

  { present: "mirando logcat con cara seria...", past: "Logcat revisado" },
  { present: "buscando el bug entre 500 logs...", past: "Bug acorralado" },
  { present: "sincronizando Gradle, otra vez...", past: "Gradle sincronizado" },
  {
    present: "esperando a Android Studio...",
    past: "Android Studio respondió",
  },
  {
    present: "recomponiendo Compose sin romper nada...",
    past: "Compose recompuesto",
  },
  {
    present: "calmando una recomposición infinita...",
    past: "Recomposición calmada",
  },
  { present: "persuadiendo al ViewModel...", past: "ViewModel colaboró" },
  { present: "observando StateFlow...", past: "StateFlow emitió" },
  {
    present: "inyectando dependencias sin drama...",
    past: "Dependencias inyectadas",
  },
  { present: "buscando quién rompió Hilt...", past: "Hilt estabilizado" },
  { present: "negociando con Koin...", past: "Koin cedió" },
  { present: "validando el Manifest...", past: "Manifest validado" },
  { present: "revisando permisos peligrosos...", past: "Permisos revisados" },
  { present: "ordenando recursos en res/...", past: "Recursos ordenados" },
  { present: "peleando con AAPT...", past: "AAPT pasó" },
  {
    present: "buscando el color perdido en themes.xml...",
    past: "Tema ajustado",
  },
  {
    present: "acomodando constraints rebeldes...",
    past: "Constraints alineadas",
  },
  { present: "migrando Room con cuidado...", past: "Room migrado" },
  { present: "evitando romper la base local...", past: "Base local intacta" },
  { present: "ejecutando pruebas unitarias...", past: "Pruebas ejecutadas" },
  { present: "mirando si Espresso se despierta...", past: "Espresso despertó" },
  { present: "preparando un APK decente...", past: "APK preparado" },
  { present: "firmando como si fuera release...", past: "Firma lista" },
  { present: "optimizando sin invocar un ANR...", past: "ANR evitado" },
  {
    present: "haciendo que el main thread respire...",
    past: "Main thread respiró",
  },
  { present: "bajando memoria antes del OOM...", past: "OOM evitado" },
  { present: "limpiando imports olvidados...", past: "Imports limpios" },
  { present: "buscando TODOs sospechosos...", past: "TODOs detectados" },
  { present: "revisando si el botón hace algo...", past: "Botón obedeció" },
  { present: "probando el happy path...", past: "Happy path validado" },
  {
    present: "buscando el edge case incómodo...",
    past: "Edge case encontrado",
  },
]

function formatElapsed(ms: number): string {
  const secs = Math.max(1, Math.ceil(ms / 1000));
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

const THINKING_SETTLE_MS = 300;

export function ThinkingSpinner({
  isActive,
  settingUpSandbox = false,
}: {
  isActive: boolean;
  settingUpSandbox?: boolean;
}) {
  const [textIdx, setTextIdx] = useState(0);
  const [done, setDone] = useState<{ past: string; elapsed: string } | null>(null);
  const [settledActive, setSettledActive] = useState(isActive);
  const startTimeRef = useRef(0);
  const sessionActiveRef = useRef(false);
  const textIdxRef = useRef(textIdx);
  const settingUpSandboxRef = useRef(settingUpSandbox);
  textIdxRef.current = textIdx;

  useEffect(() => {
    settingUpSandboxRef.current = settingUpSandbox;
  }, [settingUpSandbox]);

  useEffect(() => {
    if (isActive) {
      setSettledActive(true);
      return;
    }
    const id = window.setTimeout(() => setSettledActive(false), THINKING_SETTLE_MS);
    return () => window.clearTimeout(id);
  }, [isActive]);

  useEffect(() => {
    if (settledActive) {
      if (!sessionActiveRef.current) {
        sessionActiveRef.current = true;
        startTimeRef.current = Date.now();
        setTextIdx(Math.floor(Math.random() * BUSY_TEXTS.length));
        setDone(null);
      }
      return;
    }
    if (!sessionActiveRef.current) return;
    sessionActiveRef.current = false;
    setDone({
      past: settingUpSandboxRef.current
        ? "Set up sandbox"
        : BUSY_TEXTS[textIdxRef.current]?.past ?? "",
      elapsed: formatElapsed(Date.now() - startTimeRef.current),
    });
  }, [settledActive]);

  useEffect(() => {
    if (!settledActive || settingUpSandbox) return;
    const BUSY_TEXT_ROTATE_INTERVAL_MS = 12000;
    const id = setInterval(() => setTextIdx((i) => (i + 1) % BUSY_TEXTS.length), BUSY_TEXT_ROTATE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [settledActive, settingUpSandbox]);

  const showActive = isActive || settledActive;
  if (!showActive && !done) return null;

  if (done && !showActive) {
    return (
      <div className="my-2 flex items-center gap-2">
        <span className="text-xs text-[color:var(--ui-text-dim)]">{done.past} for {done.elapsed}</span>
      </div>
    );
  }

  return (
    <div className="my-2 flex items-center gap-2">
      <span className="shimmer-text text-xs">
        {settingUpSandbox ? "Setting up sandbox..." : BUSY_TEXTS[textIdx]?.present ?? ""}
      </span>
    </div>
  );
}
