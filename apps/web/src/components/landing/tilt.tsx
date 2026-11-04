"use client";

import { useRef, type PointerEvent, type ReactNode } from "react";

const MOUSE_ONLY = "(hover: hover) and (prefers-reduced-motion: no-preference)";

/** Leans its contents towards the mouse, and moves a soft sheen with it. Touch and reduced-motion visitors get a plain frame. */
export function Tilt({ className, maxDegrees = 4, children }: { className: string; maxDegrees?: number; children: ReactNode }) {
  // Measured once on entry: the tilt itself changes the frame's box, which would feed back into the angle.
  const rect = useRef<DOMRect | null>(null);

  const enter = (ev: PointerEvent<HTMLDivElement>) => {
    if (ev.pointerType !== "mouse" || !window.matchMedia(MOUSE_ONLY).matches) return;
    rect.current = ev.currentTarget.getBoundingClientRect();
    ev.currentTarget.classList.add("is-tilting");
  };

  const move = (ev: PointerEvent<HTMLDivElement>) => {
    const box = rect.current;
    if (!box) return;
    const x = (ev.clientX - box.left) / box.width;
    const y = (ev.clientY - box.top) / box.height;
    const { style } = ev.currentTarget;
    style.setProperty("--tilt-x", `${(0.5 - y) * 2 * maxDegrees}deg`);
    style.setProperty("--tilt-y", `${(x - 0.5) * 2 * maxDegrees}deg`);
    style.setProperty("--sheen-x", `${x * 100}%`);
    style.setProperty("--sheen-y", `${y * 100}%`);
  };

  const leave = (ev: PointerEvent<HTMLDivElement>) => {
    rect.current = null;
    ev.currentTarget.classList.remove("is-tilting");
    ev.currentTarget.style.removeProperty("--tilt-x");
    ev.currentTarget.style.removeProperty("--tilt-y");
  };

  return (
    <div className={`tilt ${className}`} onPointerEnter={enter} onPointerMove={move} onPointerLeave={leave}>
      {children}
    </div>
  );
}
