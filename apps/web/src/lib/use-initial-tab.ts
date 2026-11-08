import { useEffect } from "react";

/** Opens the tab named in `?tab=` once the page has mounted, so a link such as
 * `/app/attendance-policies/<id>?tab=followers` lands on that tab. Reading the URL after mount
 * keeps the server render and the first client render the same. */
export function useInitialTab<T extends string>(
  allowed: readonly { key: T }[],
  setTab: (tab: T) => void,
): void {
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    const match = allowed.find((item) => item.key === requested);
    if (match) setTab(match.key);
    // Only on first mount: later tab clicks are the user's choice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
