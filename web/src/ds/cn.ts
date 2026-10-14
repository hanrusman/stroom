/** Join class names, dropping falsy values. Internal helper for DS components. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
