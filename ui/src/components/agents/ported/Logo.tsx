/**
 * ON Mobile Agent brand mark — an Android-droid head badge in the ON OFF
 * green, paired with the wordmark. Replaces the legacy open-swe ASCII art.
 */
export function Logo() {
  return (
    <div className="flex w-full flex-col items-center gap-3 select-none">
      <AndroidBadge className="size-14" />
      <div className="flex flex-col items-center gap-0.5">
        <div className="font-heading text-2xl font-semibold tracking-tight text-[var(--ui-text)]">
          ON <span className="text-[var(--ui-accent)]">Mobile Agent</span>
        </div>
        <div className="text-xs font-medium uppercase tracking-[0.2em] text-[var(--ui-text-dim)]">
          Enterprise mobile SDLC
        </div>
      </div>
    </div>
  );
}

/** Minimal Android-style droid head inside a rounded brand badge. */
export function AndroidBadge({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden role="img">
      <rect width="64" height="64" rx="16" fill="var(--ui-accent)" />
      {/* antennae */}
      <line x1="24" y1="20" x2="21" y2="15" stroke="#fefefe" strokeWidth="2.4" strokeLinecap="round" />
      <line x1="40" y1="20" x2="43" y2="15" stroke="#fefefe" strokeWidth="2.4" strokeLinecap="round" />
      {/* head dome */}
      <path d="M20 30a12 12 0 0 1 24 0v1H20z" fill="#fefefe" />
      {/* body */}
      <rect x="20" y="33" width="24" height="15" rx="3" fill="#fefefe" />
      {/* eyes */}
      <circle cx="27" cy="27" r="1.9" fill="var(--ui-accent)" />
      <circle cx="37" cy="27" r="1.9" fill="var(--ui-accent)" />
    </svg>
  );
}
