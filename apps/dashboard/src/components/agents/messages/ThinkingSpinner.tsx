import { useEffect, useRef, useState } from "react";

// Pantalla de carga con guiños reales de desarrollo Android.
const BUSY_TEXTS: Array<{ present: string; past: string }> = [
  { present: "Esperando al daemon de Gradle...", past: "Gradle respondió" },
  { present: "Descargando dependencias de Gradle...", past: "Dependencias descargadas" },
  { present: "Resolviendo dependencias...", past: "Dependencias resueltas" },
  { present: "Invalidando cachés y reiniciando...", past: "Cachés invalidadas" },
  { present: "Levantando el emulador...", past: "Emulador listo" },
  { present: "Esperando al emulador...", past: "Emulador iniciado" },
  { present: "Acariciando a Bugdroid...", past: "Bugdroid motivado" },
  { present: "Esquivando un NullPointerException...", past: "NPE esquivado" },
  { present: "Subiendo el targetSdkVersion...", past: "targetSdk actualizado" },
  { present: "Consultando el oráculo de Stack Overflow...", past: "Oráculo consultado" },
  { present: "Aplastando bugs...", past: "Bugs aplastados" },
  { present: "Domando reglas de ProGuard...", past: "ProGuard domesticado" },
  { present: "Peleando con R8...", past: "R8 cooperó" },
  { present: "Alineando píxeles a la grilla de 8dp...", past: "Píxeles alineados" },
  { present: "Corriendo ./gradlew clean otra vez...", past: "Gradle limpiado" },
  { present: "Convenciendo al build de pasar...", past: "Build aprobado" },
  { present: "Mirando logcat con cara seria...", past: "Logcat revisado" },
  { present: "Buscando el bug entre muchos logs...", past: "Bug acorralado" },
  { present: "Sincronizando Gradle otra vez...", past: "Gradle sincronizado" },
  { present: "Esperando a Android Studio...", past: "Android Studio respondió" },
  { present: "Recomponiendo Compose sin romper nada...", past: "Compose recompuesto" },
  { present: "Calmando una recomposición infinita...", past: "Recomposición calmada" },
  { present: "Persuadiendo al ViewModel...", past: "ViewModel colaboró" },
  { present: "Observando StateFlow...", past: "StateFlow emitió" },
  { present: "Inyectando dependencias...", past: "Dependencias inyectadas" },
  { present: "Buscando quién rompió Hilt...", past: "Hilt estabilizado" },
  { present: "Negociando con Koin...", past: "Koin cedió" },
  { present: "Validando el Manifest...", past: "Manifest validado" },
  { present: "Revisando permisos peligrosos...", past: "Permisos revisados" },
  { present: "Ordenando recursos en res/...", past: "Recursos ordenados" },
  { present: "Peleando con AAPT...", past: "AAPT pasó" },
  { present: "Buscando el color perdido en themes.xml...", past: "Tema ajustado" },
  { present: "Acomodando constraints rebeldes...", past: "Constraints alineadas" },
  { present: "Migrando Room con cuidado...", past: "Room migrado" },
  { present: "Protegiendo la base local...", past: "Base local intacta" },
  { present: "Ejecutando pruebas unitarias...", past: "Pruebas ejecutadas" },
  { present: "Mirando si Espresso se despierta...", past: "Espresso despertó" },
  { present: "Preparando un APK decente...", past: "APK preparado" },
  { present: "Firmando como si fuera release...", past: "Firma lista" },
  { present: "Evitando invocar un ANR...", past: "ANR evitado" },
  { present: "Haciendo que el main thread respire...", past: "Main thread respiró" },
  { present: "Bajando memoria antes del OOM...", past: "OOM evitado" },
  { present: "Limpiando imports olvidados...", past: "Imports limpios" },
  { present: "Buscando TODOs sospechosos...", past: "TODOs detectados" },
  { present: "Revisando si el botón hace algo...", past: "Botón obedeció" },
  { present: "Probando el happy path...", past: "Happy path validado" },
  { present: "Buscando el edge case incómodo...", past: "Edge case encontrado" },
];

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
        ? "Sandbox preparado"
        : BUSY_TEXTS[textIdxRef.current]?.past ?? "Listo",
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
        <span className="text-xs text-[color:var(--ui-text-dim)]">{done.past} en {done.elapsed}</span>
      </div>
    );
  }

  return (
    <div className="my-2 flex items-center gap-2">
      <span className="shimmer-text text-xs">
        {settingUpSandbox ? "Preparando sandbox Android..." : BUSY_TEXTS[textIdx]?.present ?? ""}
      </span>
    </div>
  );
}
