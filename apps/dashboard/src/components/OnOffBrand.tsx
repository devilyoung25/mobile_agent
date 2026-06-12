import { SiAndroid } from "react-icons/si"

import { cn } from "@/lib/utils"

interface OnOffMarkProps {
  className?: string
}

export function OnOffMark({ className }: OnOffMarkProps) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid size-6 place-items-center rounded-md border border-[color:var(--onoff-green)] bg-[color:var(--onoff-black)] shadow-[0_0_0_1px_rgba(65,165,44,0.18)]",
        className
      )}
    >
      <span className="flex flex-col items-center font-heading text-[8px] leading-[0.78] font-bold tracking-normal">
        <span className="text-[color:var(--onoff-white)]">ON</span>
        <span className="text-[color:var(--onoff-white)]">OFF</span>
      </span>
    </span>
  )
}

interface OnOffBrandProps {
  className?: string
  showMobileCue?: boolean
}

export function OnOffBrand({
  className,
  showMobileCue = false,
}: OnOffBrandProps) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <OnOffMark />
      <span className="min-w-0 truncate font-heading text-sm font-semibold tracking-normal text-[color:var(--ui-text,var(--foreground))]">
        ON Mobile Agent
      </span>
      {showMobileCue && (
        <SiAndroid
          className="size-3.5 shrink-0 text-[color:var(--onoff-green)]"
          aria-label="Android"
        />
      )}
    </span>
  )
}
