import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

/**
 * Design tokens per docs/design/01_Design_System.md.
 * Every color is a CSS custom property (see globals.css) so light/dark
 * pairs swap via the `data-theme` attribute without a page reload — §9-10.
 */
const config: Config = {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      // §2.2 — Inter, self-hosted via next/font (see layout.tsx), exposed
      // as --font-inter. Tailwind's Preflight applies fontFamily.sans to
      // <html> automatically, so this is the only place the font is wired
      // in; no component needs to reference next/font directly.
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Ubuntu",
          "Cantarell",
          "Noto Sans",
          "sans-serif",
        ],
      },
      colors: {
        // Neutral scale — genuinely neutral, never tinted (§1.2)
        neutral: {
          50: "#fafafa",
          100: "#f5f5f5",
          200: "#e5e5e5",
          300: "#d4d4d4",
          400: "#a3a3a3",
          500: "#737373",
          600: "#525252",
          700: "#404040",
          800: "#262626",
          900: "#171717",
          950: "#0a0a0a",
        },

        // Surface & text tokens (§9 light / §10 dark)
        background: "var(--color-background)",
        surface: "var(--color-surface)",
        border: {
          DEFAULT: "var(--color-border)",
          strong: "var(--color-border-strong)",
        },
        foreground: {
          DEFAULT: "var(--color-foreground)",
          secondary: "var(--color-foreground-secondary)",
          muted: "var(--color-foreground-muted)",
          disabled: "var(--color-foreground-disabled)",
        },

        // Brand hue — primary actions only, never decoration (§1.3)
        primary: {
          DEFAULT: "var(--color-primary)",
          hover: "var(--color-primary-hover)",
          active: "var(--color-primary-active)",
          subtle: "var(--color-primary-subtle)",
          disabled: "var(--color-primary-disabled)",
          foreground: "var(--color-on-primary)",
        },
        "on-primary": "var(--color-on-primary)",

        // Semantic set — status meaning, closed set, never derived from brand (§1.4)
        success: { DEFAULT: "var(--color-success)", subtle: "var(--color-success-subtle)" },
        warning: { DEFAULT: "var(--color-warning)", subtle: "var(--color-warning-subtle)" },
        danger: { DEFAULT: "var(--color-danger)", subtle: "var(--color-danger-subtle)" },
        info: { DEFAULT: "var(--color-info)", subtle: "var(--color-info-subtle)" },

        // HRMS-specific status states (§1.4 table) — always paired with a glyph, never color alone
        "on-leave": { DEFAULT: "var(--color-on-leave)", subtle: "var(--color-on-leave-subtle)" },
        holiday: { DEFAULT: "var(--color-holiday)", subtle: "var(--color-holiday-subtle)" },
        "half-day": { DEFAULT: "var(--color-half-day)", subtle: "var(--color-half-day-subtle)" },
        wfh: { DEFAULT: "var(--color-wfh)", subtle: "var(--color-wfh-subtle)" },

        // shadcn/ui primitive slots (Task 1.2.1) — mapped onto the tokens
        // above rather than a second, parallel color system. `card` and
        // `popover` reuse `surface`/`foreground` (same elevated-surface
        // concept); `destructive` reuses `danger`/`on-primary`; `ring`
        // reuses `primary` per §1.3's "focus rings" brand-hue use case;
        // `input` reuses `border`. `muted`/`secondary`/`accent` share one
        // new neutral-subtle pair (`--color-muted`) since the design
        // system doesn't distinguish between them — see globals.css.
        card: { DEFAULT: "var(--color-surface)", foreground: "var(--color-foreground)" },
        popover: { DEFAULT: "var(--color-surface)", foreground: "var(--color-foreground)" },
        destructive: { DEFAULT: "var(--color-danger)", foreground: "var(--color-on-primary)" },
        muted: { DEFAULT: "var(--color-muted)", foreground: "var(--color-foreground-muted)" },
        secondary: { DEFAULT: "var(--color-muted)", foreground: "var(--color-foreground)" },
        accent: { DEFAULT: "var(--color-muted)", foreground: "var(--color-foreground)" },
        ring: "var(--color-primary)",
        input: "var(--color-border)",
      },

      // 4px base unit, curated steps only (§4) — matches Tailwind's default
      // numeric scale 1:1; named here so token names in the doc are directly
      // usable as utilities (p-space-4, gap-space-2, ...).
      spacing: {
        "space-1": "4px",
        "space-2": "8px",
        "space-3": "12px",
        "space-4": "16px",
        "space-6": "24px",
        "space-8": "32px",
        "space-12": "48px",
        "space-16": "64px",
      },

      // §5 — radius scales up slightly with elevation/size, never a single
      // value reused everywhere.
      borderRadius: {
        sm: "4px",
        md: "8px",
        lg: "12px",
        full: "9999px",
      },

      // §2.3 type scale — base is 14px, a deliberate departure from the web
      // default, to fit more table columns/rows without scrolling.
      fontSize: {
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["13px", { lineHeight: "18px" }],
        base: ["14px", { lineHeight: "20px" }],
        md: ["16px", { lineHeight: "24px" }],
        lg: ["18px", { lineHeight: "26px" }],
        xl: ["24px", { lineHeight: "32px" }],
        "2xl": ["32px", { lineHeight: "40px" }],
        "3xl": ["40px", { lineHeight: "48px" }],
      },

      // §8 — no motion above 300ms anywhere; state transitions only.
      transitionDuration: {
        "motion-instant": "100ms",
        "motion-fast": "150ms",
        "motion-base": "200ms",
        "motion-slow": "300ms",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
