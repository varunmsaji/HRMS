"use client";

import { useEffect, useRef, useState, type CSSProperties, type PointerEvent, type RefObject } from "react";

const MOTION_OK = "(prefers-reduced-motion: no-preference)";

/** Stagger position for a `data-rv` element: each step waits a little longer than the one before. */
export const rv = (i: number) => ({ "--rv-i": i }) as CSSProperties;

/**
 * Reveals every `[data-rv]` under the root as it scrolls into view, by adding `.in` once.
 * The hidden state only exists while `.rv-on` is on the root, so without JS, or with reduced motion, everything is simply visible.
 */
export function useReveal(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current;
    if (!el || !("IntersectionObserver" in window) || !window.matchMedia(MOTION_OK).matches) return;
    const targets = Array.from(el.querySelectorAll<HTMLElement>("[data-rv]"));
    // Anything already on screen is marked before the hidden state switches on, so it never flashes out and back.
    for (const t of targets) if (t.getBoundingClientRect().top < window.innerHeight) t.classList.add("in");
    el.classList.add("rv-on");
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("in");
          io.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.12 },
    );
    for (const t of targets) if (!t.classList.contains("in")) io.observe(t);
    return () => {
      io.disconnect();
      el.classList.remove("rv-on");
    };
  }, [root]);
}

const COUNT_MS = 1400;

/** A figure that counts up from zero the first time it scrolls into view. Renders the final value on the server and under reduced motion. */
export function CountUp({ to }: { to: number }) {
  const ref = useRef<HTMLElement>(null);
  const [n, setN] = useState(to);

  useEffect(() => {
    const el = ref.current;
    if (!el || !("IntersectionObserver" in window) || !window.matchMedia(MOTION_OK).matches) return;
    let frame = 0;
    setN(0);
    const io = new IntersectionObserver(([entry]) => {
      if (!entry?.isIntersecting) return;
      io.disconnect();
      const start = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / COUNT_MS);
        setN(Math.round(to * (1 - Math.pow(1 - t, 3))));
        if (t < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    }, { threshold: 0.6 });
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
      setN(to);
    };
  }, [to]);

  return <b ref={ref}>{n}</b>;
}

/** Pointer handler for a group of `.spot` cards: moves each card's soft glow to follow the mouse. */
export function spotlight(ev: PointerEvent<HTMLElement>) {
  if (ev.pointerType !== "mouse") return;
  const card = (ev.target as HTMLElement).closest<HTMLElement>(".spot");
  if (!card) return;
  const box = card.getBoundingClientRect();
  card.style.setProperty("--mx", `${ev.clientX - box.left}px`);
  card.style.setProperty("--my", `${ev.clientY - box.top}px`);
}
