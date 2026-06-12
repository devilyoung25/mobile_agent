import { SiAndroid } from "react-icons/si";

import { OnOffMark } from "@/components/OnOffBrand";

/**
 * ON Mobile Agent home hero mark — the official ON OFF monogram scaled up,
 * paired with the wordmark, an Android cue, and the product tagline. Keeps the
 * empty-state branding consistent with the sidebars and the login screen.
 */
export function Logo() {
  return (
    <div className="flex w-full flex-col items-center gap-3 select-none">
      <OnOffMark className="size-14 rounded-xl" />
      <div className="flex flex-col items-center gap-1">
        <div className="flex items-center gap-2 font-heading text-2xl font-semibold tracking-tight text-[var(--ui-text)]">
          ON <span className="text-[var(--ui-accent)]">Mobile Agent</span>
          <SiAndroid
            className="size-4 text-[color:var(--onoff-green)]"
            aria-label="Android"
          />
        </div>
        <div className="text-xs font-medium uppercase tracking-[0.2em] text-[var(--ui-text-dim)]">
          Enterprise mobile SDLC
        </div>
      </div>
    </div>
  );
}
