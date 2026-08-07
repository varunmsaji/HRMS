# 01 — Design System

**UI Sprint 0 — Design Foundation, Document 2 of 5**
Status: Foundational. Defines the token language every screen and component consumes.

This document names decisions and explains **why** each was made. It is not a Tailwind config, not
a `tokens.json`, and not a Figma file — those are code/design artifacts for a later sprint. What's
below is the reasoning and specification those artifacts must implement faithfully. Values given
(hex, px, ms) are precise enough to implement without further debate, which is the point of doing
this now rather than leaving it to whoever builds the first screen.

---

## 1. Color philosophy

### 1.1 The problem with "just pick a palette"

Most B2B SaaS products default to one of: (a) generic blue-on-white, indistinguishable from every
competitor, or (b) an over-designed consumer palette that fights the actual job — reading a
40-column payroll table for two hours. `files/24` §1.2 explicitly calls out the risk of the
default "system-font-everywhere" sameness and asks for a deliberate choice. Here it is, with the
reasoning.

### 1.2 The model: one workhorse scale, one committed hue, one semantic set

**Three separate color systems, never blended:**

| System | Role | Why separate |
|---|---|---|
| **Neutral scale** | Backgrounds, borders, dividers, body text, disabled states — the surface that 90% of the UI is built from | This product is dominated by dense tabular data (`files/24` D1). A neutral scale that is genuinely neutral (not a tinted "warm gray" or "cool gray" that fights every other color placed on it) is what makes a 12-column attendance matrix legible for hours at a stretch. Tinted neutrals are a common mistake — they look fine in isolation and muddy every semantic color placed against them. |
| **Brand hue** | Primary actions only: primary buttons, active nav state, focus rings, links, selected states | Spending the brand color everywhere dilutes it to decoration. Reserving it exclusively for "the thing you can click that matters most on this screen" makes it functional — a user's eye learns that the brand color *is* the action color, which speeds up scanning dense screens. This is the same discipline Linear and Notion use, and it is exactly what an enterprise tool full of secondary/tertiary content needs. |
| **Semantic set** | Status meaning: success/approved, warning/pending, danger/rejected, info, plus HRMS-specific states (absent, on-leave, holiday, half-day, work-from-home) | These carry meaning independent of brand or navigation. They must remain legible and distinguishable regardless of what brand hue a future white-label tenant might request, so they are defined as their own closed set, never derived from the brand hue. |

### 1.3 Why this specific brand hue: deep indigo-blue

**Decision: a desaturated, slightly cool indigo (`#4F46E5`-family) as the single brand hue**, used
at 5–6 tonal steps for interactive states (default, hover, active, disabled, subtle background).

Reasoning:

- **Trust without cliché.** Blue is the safe, expected choice for enterprise software (banks, HR
  platforms, productivity tools) precisely because it reads as stable and non-alarming over long,
  repeated use — this is a tool opened forty times a month (`files/24` §1.2), not a landing page
  competing for a five-second first impression. Pure novelty color choices fatigue users who live
  in the product daily.
- **Indigo over pure blue** shifts the hue slightly toward violet, which is what keeps the palette
  from reading as "generic SaaS blue" while staying inside the same trust register. It's the
  restrained differentiation `files/24` asks for without gambling on an unusual hue that could
  clash with the semantic red/green/amber set.
- **Desaturated, not vivid.** A fully saturated indigo fights for attention against the semantic
  colors that need to stand out (red for rejected, amber for pending). Desaturating the brand hue
  ~15–20% below the semantic colors' saturation is what lets "pending" and "rejected" pull the eye
  correctly on an approval screen even though the primary "Approve" button next to them is also a
  strong color.
- **AA-contrast at the default step** against both the light-mode white surface and dark-mode base
  surface, at the exact button-fill weight — verified in the component sprint, not assumed here.

This is a starting decision for the built-in theme, not a hard constraint on multi-tenant
branding — see §11.

### 1.4 The semantic set: legible without color alone

`files/24` §1.2 makes this a hard requirement, not a nice-to-have: **attendance calendars and
status indicators must carry meaning through shape/pattern/glyph as well as hue**, because (a)
color-blind users need it and (b) HR teams still print things in grayscale.

| Status | Hue | Glyph/pattern (mandatory, not optional) |
|---|---|---|
| Approved / Present / Success | Green | Solid checkmark glyph |
| Pending / Awaiting action | Amber | Clock/half-fill glyph |
| Rejected / Absent / Error | Red | X glyph |
| On leave | Violet (distinct from brand indigo — see note) | Diagonal stripe pattern on calendar cells |
| Holiday | Blue-gray | Dot pattern |
| Half-day | Amber | Half-fill split cell |
| Work-from-home | Teal | House glyph |
| Info / neutral notice | Blue | Info-i glyph |

**Note on violet vs. brand indigo:** "On leave" uses a violet distinguishable from the brand hue at
a glance (different enough in hue angle, not just lightness) specifically so a leave-status pill
sitting next to a primary brand-colored button is never ambiguous. This is checked explicitly
because both are in the blue-violet family.

### 1.5 Why not a "warm, friendly" palette

Considered and rejected: a warmer, rounder palette (oranges, warm neutrals) in the style of
consumer productivity apps. Rejected because the product's stated personality (§5 of
[`00_UI_Vision.md`](00_UI_Vision.md)) is "precise, calm, direct" — a warm palette reads as casual,
which undersells the product in front of the compliance officers, finance controllers and auditors
who are real users of this system (`files/19` Auditor role) and who judge trustworthiness partly by
visual register.

---

## 2. Typography

### 2.1 The requirement that drives the choice

`files/24` §1.2 is explicit: payroll and attendance are number-dense, so **lining tabular figures
are non-negotiable** — every digit must occupy the same width so columns of numbers align without
the eye having to hunt. This single requirement eliminates most default system-font choices, which
either lack tabular figures entirely or require them to be enabled per-context (easy to forget on
one of 185 screens).

### 2.2 Decision: a two-family system

| Role | Family | Why |
|---|---|---|
| **Body / UI (default)** | A grotesk sans with true tabular lining figures as a built-in feature, not an OpenType feature nobody remembers to enable (e.g., Inter, IBM Plex Sans, or a comparable metrics-compatible alternative selected in the component sprint) | Neutral, highly legible at small sizes (12–14px table rows), designed for interface use rather than editorial reading, wide language support for future locales. |
| **Display (headers, empty states, dashboard hero numbers)** | A distinct but related display face, used sparingly | `files/24` §1.2 explicitly warns against the "default system-font-everywhere" sameness. A small, deliberate departure in headers and empty-state illustration text gives the product a recognizable identity at the moments a user actually looks up from the data — without touching the 95% of the UI that is body/table text, where consistency matters more than personality. |
| **Numeric-heavy contexts (payslip breakdown, pay run figures)** | Body family, tabular-lining variant, at a slightly increased letter-spacing for amount columns | Money is the highest-stakes content in the product (`files/24` §4.3). It gets the most conservative, most legible treatment — no display face ever touches a currency figure. |

### 2.3 Type scale

A modular scale with a small number of steps, because 185 screens with an unconstrained scale is
how inconsistency creeps in:

| Token | Size | Use |
|---|---|---|
| `text-xs` | 12px | Table cell secondary text, timestamps, helper text |
| `text-sm` | 13px | Table body default, form labels |
| `text-base` | 14px | Default body text, form input text |
| `text-md` | 16px | Card titles, section labels |
| `text-lg` | 18px | Page section headers |
| `text-xl` | 24px | Page titles |
| `text-2xl` | 32px | Dashboard hero numbers, display face territory |
| `text-3xl` | 40px | Reserved: empty states, marketing-adjacent surfaces (careers page, offer acceptance) |

Base size is **14px, not 16px** — a deliberate departure from typical web defaults, because this is
a data-density-first product (`files/24` D1) viewed primarily on 1024–1440px+ desktop monitors
(§9 of `00_UI_Vision.md`), and 16px body text measurably reduces the number of table columns and
rows visible without scrolling. Line height compensates (1.5 for body, 1.3 for table rows) to
protect legibility at the smaller base.

---

## 3. Grid

**12-column grid, 1280px max content width on standard desktop, full-bleed for dense data
screens.**

- Admin/HR pages that are primarily forms or dashboards respect the 1280px max width with centered
  content — matching human reading-line-length expectations for forms.
- Admin/HR pages that are primarily tables (Attendance Matrix, Directory, Payroll reports) go
  **full-bleed** at widths above 1440px — `files/24` §6 explicitly states "no max-width stretching
  of dense data screens" at that breakpoint, because a payroll table gains real value from every
  extra visible column, while prose gains nothing from extra width.
- Gutter: 24px at desktop, 16px at tablet, 16px at mobile — kept in a 4px-multiple relationship with
  the spacing scale (§4) so grid and spacing never fight.

---

## 4. Spacing

**4px base unit, exponential-ish scale, not arbitrary.**

| Token | Value | Typical use |
|---|---|---|
| `space-1` | 4px | Icon-to-label gap, tightest inline spacing |
| `space-2` | 8px | Form field internal padding, chip padding |
| `space-3` | 12px | Table cell padding, compact card padding |
| `space-4` | 16px | Standard card padding, form field vertical gap |
| `space-6` | 24px | Section spacing within a page |
| `space-8` | 32px | Page-level section separation |
| `space-12` | 48px | Major layout separation (sidebar-to-content gutter) |
| `space-16` | 64px | Empty-state vertical rhythm |

**Why 4px and not 8px:** an 8px-only base is common but too coarse for the density this product
needs — a table row that must fit an approve/reject action pair, a status pill and three data
columns in one 36px-tall row needs 4px-granular control over internal padding. Every spacing value
in the entire system is a multiple of 4px, no exceptions, which is what keeps 185 screens built by
different sessions of AI-assisted development (`files/01` §2) visually consistent without a human
eyeballing every screen.

---

## 5. Radius

| Token | Value | Use |
|---|---|---|
| `radius-sm` | 4px | Inputs, buttons, badges/pills, table row hover state |
| `radius-md` | 8px | Cards, dropdowns, popovers |
| `radius-lg` | 12px | Modals, drawers |
| `radius-full` | 9999px | Avatars, status dots, pill-shaped badges |

**Reasoning:** a small, consistent radius (not sharp 0px corners, not the heavily-rounded
"friendly consumer app" 16–20px trend) signals structure and precision without softness — matching
the "precise, calm" personality (§5, `00_UI_Vision.md`). Radius scales *up* slightly with
elevation/size (small controls get small radius, large surfaces like modals get a marginally larger
one) so nothing ever looks like a rounded rectangle stamped from the same cookie cutter regardless
of size, which is a subtle but common tell of an unconsidered system.

---

## 6. Shadows (elevation)

Elevation exists to communicate **stacking order and interactivity**, not decoration:

| Token | Use | Value direction |
|---|---|---|
| `elevation-0` | Flat content, table rows, page background | none |
| `elevation-1` | Cards at rest | 1px border preferred over shadow where possible; a near-invisible shadow only if a border would conflict with a table's own borders |
| `elevation-2` | Dropdowns, popovers, tooltips | Soft, tight-radius shadow — signals "floating above content, dismissible" |
| `elevation-3` | Modals, drawers | Stronger shadow + scrim behind — signals "blocking, must resolve" |

**Reasoning for border-over-shadow at rest:** a UI this saturated with cards and tables
accumulates shadow noise fast if every card casts one — the eye can no longer tell which shadow
means "this is elevated and important" versus "this is just how cards look." Reserving visible
shadow for genuinely floating/transient surfaces (dropdowns, modals) keeps shadow meaningful. Cards
at rest use a 1px neutral border instead, consistent with the "structure over decoration" reasoning
in §5.

---

## 7. Icons

**A single outline-style icon set, 20px and 16px sizes, 1.5–2px stroke weight, no mixing with a
second icon family.**

- Outline over filled: filled icons read as "selected/active" in most conventions, so reserving
  fill exclusively for active/selected states (nav items, toggled filters) gives the UI a free,
  consistent signal for state that a filled-by-default icon set would waste.
- One consistent stroke weight across all sizes so icons never look like they came from different
  vendors — a real risk across 185 screens with placeholder icons picked ad hoc.
- Icons never carry meaning alone in status contexts (§1.4) — always paired with a text label or
  used purely decoratively next to a labeled action.

---

## 8. Animation

**Motion is restricted to state transitions and loading feedback — no ambient animation** (`files/24`
§1.2, and Performance principles in `00_UI_Vision.md` §10).

| Token | Duration | Easing | Use |
|---|---|---|---|
| `motion-instant` | 100ms | ease-out | Hover states, focus rings |
| `motion-fast` | 150ms | ease-in-out | Button press feedback, checkbox/toggle state change |
| `motion-base` | 200ms | ease-in-out | Dropdown/popover open-close, tab switch |
| `motion-slow` | 300ms | ease-in-out | Modal/drawer enter-exit, approval-card swipe-away (`files/24` §4.5) |

- No motion durations above 300ms anywhere — this is a tool opened dozens of times a month; slow
  chrome is a tax paid every single time.
- All motion respects `prefers-reduced-motion` (§7, `00_UI_Vision.md`) by collapsing to an instant
  state change plus opacity crossfade only.
- Skeleton loading states use a subtle shimmer at low contrast — enough to read as "loading," not
  enough to be distracting on a screen that's mostly skeleton during a slow query.

---

## 9. Light mode

Light mode is the **primary, default mode** — this is a desktop-first, office-context enterprise
tool (§9, `00_UI_Vision.md`), and light mode remains the norm in that context (print/screenshot
parity with payslips and reports also favors light-on-dark-text as the default, per `files/24`
§4.3's password-protected, printable-in-one-page PDF requirement).

| Layer | Treatment |
|---|---|
| App background | Near-white neutral (not pure `#FFFFFF` — a very slightly warm-neutral off-white reduces eye strain over hours of table-reading) |
| Surface (cards, table rows) | Pure white, to create just enough separation from the app background without a shadow |
| Borders/dividers | Light neutral, ~10% contrast step from surface — visible but not loud |
| Primary text | Near-black neutral (not pure black — softer on the eyes at high contrast ratios sustained for hours) |
| Secondary text | Mid-neutral, meets AA for text ≥14px |

---

## 10. Dark mode

Dark mode is a **first-class, fully designed second mode** — not an inverted-filter afterthought —
because shift-based and field workforce users (security, logistics, manufacturing verticals the
product targets per `files/01`) often use the mobile app in low-light conditions, and because
enterprise buyers increasingly expect it as table stakes.

| Layer | Treatment |
|---|---|
| App background | Deep neutral, not pure black — pure black causes excessive contrast halation against white text over long sessions |
| Surface (cards, table rows) | One step lighter than app background, using elevation (a lighter neutral fill), not shadow — shadows are nearly invisible on dark backgrounds, so dark-mode elevation is communicated by surface lightness steps instead (a deliberate divergence from the light-mode shadow model in §6) |
| Borders/dividers | Low-contrast light neutral at reduced opacity |
| Primary text | Off-white, not pure white — same halation reasoning as background |
| Brand hue | Lightened 1 step from the light-mode value to maintain AA contrast against the darker surface, never the identical hex reused verbatim across modes |
| Semantic colors | Each semantic hue gets an explicit dark-mode variant (typically desaturated slightly, lightened) verified for contrast independently — never assumed to "just work" inverted |

**Rule:** every token in this document is defined as a **light/dark pair**, never a single value
with a CSS filter or opacity trick applied for dark mode. This is what prevents the "dark mode was
bolted on" look that undermines trust in a precision-positioned product.

---

## 11. Multi-tenant branding boundary

Because the product serves many tenants (§6, `00_UI_Vision.md` — "multi-tenant coherence"), a
future branding capability (tenant logo, limited accent override) must not be allowed to break this
system:

- Tenants may override the **brand hue only**, within a guardrail that enforces minimum contrast
  and a minimum hue distance from every semantic color (§1.4) — preventing a tenant from
  accidentally choosing a brand color indistinguishable from "rejected" red.
- Neutral scale, semantic set, typography, spacing, radius and motion are **never
  tenant-overridable**. This is what keeps the product recognizable as one system and keeps the
  component library from having to be tested against arbitrary tenant color combinations.

---

## 12. What's deferred to later sprints

- Exact hex/HSL values for every tonal step (this document commits to the brand hue family and
  the reasoning; full token tables are produced when the component library is built, so they can
  be contrast-tested against real components rather than specified in the abstract).
- The specific font families' final license/selection (candidates named in §2.2; final pick is a
  procurement + license-check step).
- Component-level shadow/elevation exceptions (e.g., a sticky table header may need a special-cased
  shadow-on-scroll treatment — decided when that component is built, following the elevation
  *principles* in §6).
