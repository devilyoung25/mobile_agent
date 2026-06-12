import { useEffect, useRef, useState } from "react";

// Video-game-loading-screen energy, but make it Android dev. The agent shows a
// random one of these while it thinks — equal parts Gradle trauma and droid love.
const BUSY_TEXTS: Array<{ present: string; past: string }> = [
  { present: "waiting for Gradle daemon...", past: "Waited for Gradle" },
  { present: "downloading the internet (Gradle)...", past: "Downloaded the internet" },
  { present: "resolving dependencies...", past: "Resolved dependencies" },
  { present: "invalidating caches & restarting...", past: "Invalidated caches" },
  { present: "booting the emulator...", past: "Booted the emulator" },
  { present: "still waiting for the emulator...", past: "Outlasted the emulator" },
  { present: "reticulating splines...", past: "Reticulated splines" },
  { present: "dodging a NullPointerException...", past: "Dodged the NPE" },
  { present: "bumping targetSdkVersion...", past: "Bumped the targetSdk" },
  { present: "consulting the StackOverflow oracle...", past: "Consulted StackOverflow" },
  { present: "petting Bugdroid...", past: "Petted Bugdroid" },
  { present: "squashing bugs...", past: "Squashed the bugs" },
  { present: "wrangling ProGuard rules...", past: "Wrangled ProGuard" },
  { present: "aligning pixels to the 8dp grid...", past: "Aligned to the grid" },
  { present: "running ./gradlew clean (again)...", past: "Ran gradlew clean" },
  { present: "convincing the build to succeed...", past: "Convinced the build" },
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
