import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Readable document title: stored titles are identifier-style (e.g. ACCOUNT_OPENING_PROCEDURE) */
export function formatTitle(title: string): string {
  const text = title.replace(/_/g, ' ').trim();
  return text === text.toUpperCase()
    ? text.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())
    : text;
}
