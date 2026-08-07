---
name: Enterprise Productivity System
colors:
  surface: '#FFFFFF'
  surface-dim: '#d8d9e3'
  surface-bright: '#f9f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3fd'
  surface-container: '#ecedf7'
  surface-container-high: '#e6e7f2'
  surface-container-highest: '#e1e2ec'
  on-surface: '#191b23'
  on-surface-variant: '#424754'
  inverse-surface: '#2e3038'
  inverse-on-surface: '#eff0fa'
  outline: '#727785'
  outline-variant: '#c2c6d6'
  surface-tint: '#005ac2'
  primary: '#0058be'
  on-primary: '#ffffff'
  primary-container: '#2170e4'
  on-primary-container: '#fefcff'
  inverse-primary: '#adc6ff'
  secondary: '#006a63'
  on-secondary: '#ffffff'
  secondary-container: '#99efe5'
  on-secondary-container: '#006f67'
  tertiary: '#924700'
  on-tertiary: '#ffffff'
  tertiary-container: '#b75b00'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d8e2ff'
  primary-fixed-dim: '#adc6ff'
  on-primary-fixed: '#001a42'
  on-primary-fixed-variant: '#004395'
  secondary-fixed: '#9cf2e8'
  secondary-fixed-dim: '#80d5cb'
  on-secondary-fixed: '#00201d'
  on-secondary-fixed-variant: '#00504a'
  tertiary-fixed: '#ffdcc6'
  tertiary-fixed-dim: '#ffb786'
  on-tertiary-fixed: '#311400'
  on-tertiary-fixed-variant: '#723600'
  background: '#f9f9ff'
  on-background: '#191b23'
  surface-variant: '#e1e2ec'
  primary-hover: '#2563EB'
  primary-subtle: '#EFF6FF'
  bg-main: '#F8FAFC'
  border-weak: '#E2E8F0'
  border-strong: '#CBD5E1'
  text-primary: '#0F172A'
  text-secondary: '#475569'
  text-muted: '#64748B'
  disabled: '#94A3B8'
  success: '#16A34A'
  warning: '#F59E0B'
  danger: '#DC2626'
typography:
  display:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  h1:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
  h2:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 30px
  h3:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
  body-default:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-medium:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
  small:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  caption:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  overline:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  h1-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  2xl: 48px
  3xl: 64px
  gutter: 24px
  margin-desktop: 64px
  margin-tablet: 32px
  margin-mobile: 16px
  max-width-form: 760px
---

> **⚠ Superseded — not a canonical token source.** This file (and its duplicate at the repo root,
> `DESIGN.md`) predates the UI Sprint 0 design foundation and is **not** part of the five-document
> canonical set referenced by `docs/README.md` §"Read order" and by
> [`00_UI_Vision.md`](00_UI_Vision.md) §1 ("Everything downstream ... is a derivative of the five
> documents in this folder"). Its color/typography frontmatter (Material-style `surface-container-*`
> keys, primary `#3B82F6`/`#0058be`) **conflicts** with the approved tokens in
> [`01_Design_System.md`](01_Design_System.md) (brand indigo `#4F46E5` family, HRMS-specific
> semantic states). `docs/sprints/SPRINT_3_COMPANY_FOUNDATION.md` Task 1.1.1 implements against
> `01_Design_System.md` — treat that document as canonical for all design tokens. This file is kept
> for historical reference only; do not implement new tokens from it.

# Enterprise HRMS Design System v0.1
Version: 0.1
Status: Approved
Purpose: Visual Foundation
---
# 1. Design Philosophy
This HRMS is enterprise software.
It is used by HR professionals for 6–10 hours every day.
Every design decision must reduce cognitive load, increase readability, and maximize productivity.
The interface should feel:
- Professional
- Calm
- Modern
- Trustworthy
- Premium
- Information-dense
- Predictable
Avoid:
- Bright gradients
- Playful colors
- Heavy animations
- Glassmorphism
- Neumorphism
- Consumer app aesthetics
Think:
- Linear
- Atlassian
- GitHub
- Notion
- BambooHR
---
# 2. Color Palette
## Primary
Purpose
Primary actions
Links
Selected navigation
Active states
Focus ring
Token
Primary Blue
HEX
#3B82F6
---
## Primary Hover
#2563EB
---
## Primary Subtle
#EFF6FF
Used for
Selected rows
Active tabs
Selected navigation
Background highlight
---
## Secondary
Purpose
Module accents
Tags
Charts
HEX
#0F766E
---
# Neutral Colors
Background
#F8FAFC
Surface
#FFFFFF
Border
#E2E8F0
Border Strong
#CBD5E1
Text Primary
#0F172A
Text Secondary
#475569
Text Muted
#64748B
Disabled
#94A3B8
---
# Semantic Colors
Success
#16A34A
Warning
#F59E0B
Danger
#DC2626
Information
#2563EB
---
# 3. Typography
Primary Font
Inter
Fallback
system-ui
Segoe UI
Roboto
Helvetica Neue
Arial
Font Weights
Regular
400
Medium
500
SemiBold
600
Bold
700
No other font families allowed.
---
# Font Sizes
Display
36
H1
28
H2
22
H3
18
Body
14
Small
13
Caption
12
Overline
11
---
# 4. Layout
Desktop First
Minimum width
1440px
Tablet
1024px
Mobile
Responsive adaptation
Forms
Maximum readable width
760px
Tables
Full width
Dashboard
Fluid width
---
# 5. Grid
12 Columns
Desktop Margin
64px
Tablet
32px
Mobile
16px
Gutter
24px
Base spacing unit
4px
---
# 6. Spacing Scale
4
8
12
16
24
32
48
64
Every spacing value must be a multiple of 4.
---
# 7. Border Radius
Checkbox
4px
Buttons
6px
Inputs
6px
Cards
8px
Dropdowns
8px
Dialogs
12px
Avatar
999px
---
# 8. Elevation
Level 0
Flat
Tables
Rows
Panels
Level 1
Cards
Level 2
Dropdown
Popover
Level 3
Dialog
Modal
Never use heavy shadows.
---
# 9. Icons
Library
Lucide
Style
Outline
Stroke
1.5px
Default Size
20px
Do not mix icon libraries.
---
# 10. Motion
Hover
120ms
Dropdown
180ms
Dialog
240ms
Animation Style
Ease Out
No bounce
No elastic motion
No exaggerated scaling
Motion should communicate state.
Never decoration.
---
# 11. Dark Mode
Supported
Default
Light Mode
Dark Mode
Optional
Near-black surfaces
Never pure black
---
# 12. Accessibility
WCAG AA
Visible keyboard focus
Keyboard navigation
Semantic HTML
Color is never the only indicator.
---
# 13. Product Personality
Professional
Modern
Minimal
Reliable
Fast
Enterprise
Calm
Dense
Consistent
---
# 14. Design Rules
Every screen must follow this design system.
Never introduce:
- New colors
- New fonts
- New spacing scales
- New radius values
- New animation styles
Consistency is more important than creativity.
The goal is to make every module feel like it belongs to the same product.
