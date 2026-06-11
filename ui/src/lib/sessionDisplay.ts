import type { SessionUser } from "@/lib/api";

function clean(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export function sessionDisplayName(user: SessionUser): string {
  return clean(user.name) ?? clean(user.email) ?? user.login;
}

export function sessionSecondaryText(user: SessionUser): string | null {
  const display = sessionDisplayName(user).toLowerCase();
  const email = clean(user.email);
  if (email && email.toLowerCase() !== display) return email;
  if (user.auth_provider === "entra") return "Microsoft Entra";
  return clean(user.login);
}

export function sessionInitials(user: SessionUser): string {
  const source = sessionDisplayName(user);
  const parts = source
    .replace(/@.*/, "")
    .split(/\s+/)
    .filter(Boolean);
  const first = parts[0]?.[0];
  const second = parts[1]?.[0];
  if (first && second) return `${first}${second}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}
