/** "just now", "5m ago", "3h ago", "2d ago", then a short date. */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000);
  if (Number.isNaN(seconds) || seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The server only stores app-relative paths; refuse anything else before navigating. */
export function safeActionPath(url: string | null | undefined): string | null {
  if (!url) return null;
  if (!url.startsWith("/") || url.startsWith("//") || url.includes("://")) return null;
  return url;
}
