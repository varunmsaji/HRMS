import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

/**
 * Design tokens per docs/design/01_Design_System.md.
 * Every color is a CSS custom property (see globals.css) so light/dark
 * pairs swap via the `data-theme` attribute without a page reload — §9-10.
 * Uses `color-mix` for alpha-capable tokens so Tailwind opacity modifiers
 * (e.g. `bg-primary/10`, `border-danger/30`) work seamlessly with hex variables.
 */
const withAlpha = (cssVar: string) =>
  `color-mix(in srgb, var(${cssVar}) calc(<alpha-value> * 100%), transparent)`;

const config: Config = {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
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
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "Liberation Mono",
          "Courier New",
          "monospace",
        ],
      },
      colors: {
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

        background: withAlpha("--color-background"),
        surface: {
          DEFAULT: withAlpha("--color-surface"),
          secondary: withAlpha("--color-surface-secondary"),
          elevated: withAlpha("--color-surface-elevated"),
        },
        border: {
          DEFAULT: withAlpha("--color-border"),
          subtle: withAlpha("--color-border-subtle"),
          strong: withAlpha("--color-border-strong"),
        },
        foreground: {
          DEFAULT: withAlpha("--color-foreground"),
          secondary: withAlpha("--color-foreground-secondary"),
          muted: withAlpha("--color-foreground-muted"),
          disabled: withAlpha("--color-foreground-disabled"),
        },

        primary: {
          DEFAULT: withAlpha("--color-primary"),
          hover: withAlpha("--color-primary-hover"),
          active: withAlpha("--color-primary-active"),
          subtle: withAlpha("--color-primary-subtle"),
          border: withAlpha("--color-primary-border"),
          disabled: withAlpha("--color-primary-disabled"),
          foreground: "var(--color-on-primary)",
        },
        "on-primary": "var(--color-on-primary)",

        success: {
          DEFAULT: withAlpha("--color-success"),
          subtle: withAlpha("--color-success-subtle"),
          border: withAlpha("--color-success-border"),
        },
        warning: {
          DEFAULT: withAlpha("--color-warning"),
          subtle: withAlpha("--color-warning-subtle"),
          border: withAlpha("--color-warning-border"),
        },
        danger: {
          DEFAULT: withAlpha("--color-danger"),
          subtle: withAlpha("--color-danger-subtle"),
          border: withAlpha("--color-danger-border"),
        },
        info: {
          DEFAULT: withAlpha("--color-info"),
          subtle: withAlpha("--color-info-subtle"),
          border: withAlpha("--color-info-border"),
        },

        "on-leave": {
          DEFAULT: withAlpha("--color-on-leave"),
          subtle: withAlpha("--color-on-leave-subtle"),
          border: withAlpha("--color-on-leave-border"),
        },
        holiday: {
          DEFAULT: withAlpha("--color-holiday"),
          subtle: withAlpha("--color-holiday-subtle"),
          border: withAlpha("--color-holiday-border"),
        },
        "half-day": {
          DEFAULT: withAlpha("--color-half-day"),
          subtle: withAlpha("--color-half-day-subtle"),
          border: withAlpha("--color-half-day-border"),
        },
        wfh: {
          DEFAULT: withAlpha("--color-wfh"),
          subtle: withAlpha("--color-wfh-subtle"),
          border: withAlpha("--color-wfh-border"),
        },

        card: {
          DEFAULT: withAlpha("--color-surface"),
          foreground: withAlpha("--color-foreground"),
        },
        popover: {
          DEFAULT: withAlpha("--color-surface-elevated"),
          foreground: withAlpha("--color-foreground"),
        },
        destructive: {
          DEFAULT: withAlpha("--color-danger"),
          foreground: "var(--color-on-primary)",
        },
        muted: {
          DEFAULT: withAlpha("--color-muted"),
          foreground: withAlpha("--color-foreground-muted"),
        },
        secondary: {
          DEFAULT: withAlpha("--color-muted"),
          foreground: withAlpha("--color-foreground"),
        },
        accent: {
          DEFAULT: withAlpha("--color-muted"),
          foreground: withAlpha("--color-foreground"),
        },
        ring: withAlpha("--color-primary"),
        input: withAlpha("--color-border"),
      },

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

      borderRadius: {
        xs: "2px",
        sm: "4px",
        DEFAULT: "6px",
        md: "6px",
        lg: "8px",
        xl: "12px",
        full: "9999px",
      },

      boxShadow: {
        "elevation-1": "var(--shadow-elevation-1)",
        "elevation-2": "var(--shadow-elevation-2)",
        "elevation-3": "var(--shadow-elevation-3)",
      },

      fontSize: {
        "2xs": ["11px", { lineHeight: "16px", letterSpacing: "0.04em" }],
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["13px", { lineHeight: "18px" }],
        base: ["14px", { lineHeight: "20px" }],
        md: ["16px", { lineHeight: "24px" }],
        lg: ["18px", { lineHeight: "26px", letterSpacing: "-0.01em" }],
        xl: ["22px", { lineHeight: "30px", letterSpacing: "-0.015em" }],
        "2xl": ["28px", { lineHeight: "36px", letterSpacing: "-0.02em" }],
        "3xl": ["36px", { lineHeight: "44px", letterSpacing: "-0.025em" }],
      },

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
