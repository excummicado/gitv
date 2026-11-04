import { useEffect } from "react";

// Space kept between a popup and its trigger, as in the popups' own styles.
const GAP = 8;

function place(tip: Element, host: Element) {
  const box = host.getBoundingClientRect();
  const below = document.documentElement.clientHeight - box.bottom;
  tip.toggleAttribute("data-above", tip.getBoundingClientRect().height + GAP > below && box.top > below);
}

// The site's hover popups ([role="tooltip"] inside their trigger) open below it: one that wouldn't fit on the screen
// opens above instead (app.css), when there's more room there. Their size is watched while open, as some load what
// they list on hover.
export function useTooltipPlacement() {
  useEffect(() => {
    let host: Element | null = null;
    let tip: Element | null = null;
    const observer = new ResizeObserver(() => { if (tip && host) place(tip, host); });

    const open = (event: Event) => {
      for (let el = event.target as Element | null; el; el = el.parentElement) {
        const found = el.querySelector(':scope > [role="tooltip"]');
        if (!found) continue;
        if (found !== tip) {
          observer.disconnect();
          observer.observe(found);
          host = el;
          tip = found;
        }
        place(found, el);
        return;
      }
    };

    document.addEventListener("pointerover", open);
    document.addEventListener("focusin", open);
    return () => {
      document.removeEventListener("pointerover", open);
      document.removeEventListener("focusin", open);
      observer.disconnect();
    };
  }, []);
}
