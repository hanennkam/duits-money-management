---
name: Duits HIG Expense Architecture
colors:
  surface: '#faf9fe'
  surface-dim: '#dad9df'
  surface-bright: '#faf9fe'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f3f8'
  surface-container: '#eeedf3'
  surface-container-high: '#e9e7ed'
  surface-container-highest: '#e3e2e7'
  on-surface: '#1a1b1f'
  on-surface-variant: '#414754'
  inverse-surface: '#2f3034'
  inverse-on-surface: '#f1f0f5'
  outline: '#717786'
  outline-variant: '#c0c6d6'
  surface-tint: '#005db8'
  primary: '#005ab3'
  on-primary: '#ffffff'
  primary-container: '#0073e0'
  on-primary-container: '#fefcff'
  inverse-primary: '#aac7ff'
  secondary: '#006e28'
  on-secondary: '#ffffff'
  secondary-container: '#6ffb85'
  on-secondary-container: '#00732a'
  tertiary: '#bc000a'
  on-tertiary: '#ffffff'
  tertiary-container: '#e2241f'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d6e3ff'
  primary-fixed-dim: '#aac7ff'
  on-primary-fixed: '#001b3e'
  on-primary-fixed-variant: '#00468d'
  secondary-fixed: '#72fe88'
  secondary-fixed-dim: '#53e16f'
  on-secondary-fixed: '#002107'
  on-secondary-fixed-variant: '#00531c'
  tertiary-fixed: '#ffdad5'
  tertiary-fixed-dim: '#ffb4aa'
  on-tertiary-fixed: '#410001'
  on-tertiary-fixed-variant: '#930005'
  background: '#faf9fe'
  on-background: '#1a1b1f'
  surface-variant: '#e3e2e7'
typography:
  large-title:
    fontFamily: Manrope
    fontSize: 34px
    fontWeight: '700'
    lineHeight: 41px
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Manrope
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Manrope
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Manrope
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 25px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Hanken Grotesk
    fontSize: 17px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: -0.01em
  body-strong:
    fontFamily: Hanken Grotesk
    fontSize: 17px
    fontWeight: '600'
    lineHeight: 22px
    letterSpacing: -0.01em
  subheadline:
    fontFamily: Hanken Grotesk
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: -0.005em
  footnote:
    fontFamily: Hanken Grotesk
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  caption:
    fontFamily: Hanken Grotesk
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0em
  currency-display:
    fontFamily: Manrope
    fontSize: 38px
    fontWeight: '800'
    lineHeight: 44px
    letterSpacing: -0.03em
  currency-cell:
    fontFamily: Hanken Grotesk
    fontSize: 17px
    fontWeight: '600'
    lineHeight: 22px
    letterSpacing: 0.01em
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  gutter: 1rem
  margin: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.25rem
  space-xl: 1.75rem
---

## Brand & Style

This design system delivers an authentic, hyper-refined iOS native experience tailored for personal expense management. Inspired directly by Apple Wallet and iOS Settings, the aesthetic blends utilitarian clarity with tactile precision. The interface projects reliability, quiet luxury, and financial control without visual clutter.

Key personality attributes:
- **Discreet Utility:** Interfaces remain nearly invisible, highlighting user data and actionable insights above decorative chrome.
- **Tactile Fineness:** Native iOS material behaviors—including continuous corner curves, vibrant system tinting, and sub-pixel borders—evoke the tactile polish of Apple hardware.
- **Cognitive Ease:** High structural contrast and strict spatial hierarchy allow rapid expense logging and frictionless budget auditing.

## Colors

The color palette mirrors the dynamic range of iOS system colors, balanced specifically for clean readability across light mode surfaces:

- **Primary Canvas (`#F2F2F7`):** Maps to `systemGroupedBackground`. Establishes depth separation underneath elevated content cards.
- **Card Surfaces (`#FFFFFF`):** Maps to `secondarySystemGroupedBackground`. Pure white inset panels that frame transactional rows and aggregate widgets.
- **Accent Blue (`#0A84FF`):** Maps to Apple System Blue for interactive elements, primary callouts, and selection states.
- **Income Positive (`#34C759`):** Apple System Green, applied strictly to inflows, savings milestones, and positive balances.
- **Expense Negative (`#FF3B30`):** Apple System Red, reserved for debit transactions, spend limits, and critical alerts.
- **System Chrome & Dividers:** Separators utilize `rgba(60, 60, 67, 0.18)` (`#C6C6C8`), ensuring low-contrast hairline division between stacked cells.
- **Labels & Hierarchy:** Primary text uses `#000000`, secondary labels use `#8E8E93`, and tertiary helper text uses `rgba(60, 60, 67, 0.3)`.

## Typography

Typography adapts Human Interface Guidelines proportioning to modern geometric font pairing: `Manrope` for display and titles, combined with `Hanken Grotesk` for body copy, lists, and metadata.

- **Numerics & Currency:** All currency amounts (e.g., RM 1,280.50) must enforce tabular figures (`font-variant-numeric: tabular-nums`) to ensure vertical decimal alignment across dynamic transaction tables.
- **Title Tracking:** Large titles enforce tight negative letter-spacing to reproduce native iOS navigation bar typography.
- **Section Headers:** Uppercase group labels are styled using `caption` with increased letter-spacing (`0.06em`), paired with secondary label coloring (`#8E8E93`).

## Layout & Spacing

Layout geometry follows standard iOS Inset Grouped conventions:

- **Horizontal Rhythm:** Full-width screens feature standard 16px (`1rem`) outer margins. Content groups sit within cards inset 16px from each edge.
- **Section Headers & Footers:** Grouped card modules maintain 24px vertical separation, preceded by an 8px bottom-spaced section header and followed by a 6px top-spaced section note.
- **Cell Padding:** Inset grouped list items maintain an internal padding of 11px vertically and 16px horizontally (`space-md`).
- **Responsive Handling:** On wider viewports (tablets or expanded displays), the content container limits maximum width to 640px, centered horizontally within `#F2F2F7` margins.

## Elevation & Depth

Visual hierarchy uses physical material separation rather than heavy skeuomorphic shading:

- **Base Layer:** Dynamic flat background (`#F2F2F7`).
- **Card Tier:** Raised surfaces (`#FFFFFF`) with a diffuse, ultra-subtle ambient shadow: `0 2px 10px rgba(0, 0, 0, 0.03)`. Edge definition is reinforced with a `0.5px` border of `rgba(60, 60, 67, 0.08)`.
- **Translucent Navigation & Tab Chrome:** Modals, navigation bars, and the bottom tab bar utilize frosted glass blur (`backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px)`), with a translucent wash (`rgba(249, 249, 249, 0.85)`). Separators are rendered as bottom/top 0.5px hairline rules (`rgba(60, 60, 67, 0.18)`).
- **Modals & Sheets:** Floating modal bottom sheets incorporate an elevated shadow: `0 -4px 24px rgba(0, 0, 0, 0.08)`.

## Shapes

The design system employs continuous curve corner geometries (iOS squircles):

- **Inset Grouped Containers:** Radii between 16px and 20px (standardized at `18px`).
- **Pill Elements:** Interactive tags, category chips, and search inputs implement pill radius (`9999px` / `rounded-full`).
- **List Dividers:** Inner dividers indent 56px from the left to clear the 36px icon container while extending flush to the right boundary.

## Components

### Buttons
- **Primary Action (Filled):** Solid `#0A84FF` background, pill-rounded, white text with `body-strong` weight. Touch feedback scales down slightly (`scale(0.98)`) with dynamic spring easing.
- **Secondary Plain:** Transparent background with `#0A84FF` text, no border.

### Inset Grouped Lists & Cells
- Cards are grouped modules (`#FFFFFF`) containing interactive cells.
- **Cell Structure:** Left-aligned 36x36px squircle icon container with tinted category-specific background; title (`body-lg`) stacked above subtitle (`footnote`); right-aligned tabular currency value (`currency-cell`) and optional subtle chevron icon (`#C7C7CC`).
- Hairline dividers sit between rows, indented past the leading icon.

### Form Inputs & Text Fields
- Clean inline rows within grouped lists. Labels sit on the left; input fields occupy right-aligned space with muted placeholder text (`rgba(60, 60, 67, 0.3)`).
- Direct currency entry components utilize large centered displays (`currency-display`) with immediate reactive formatting.

### Segmented Controls & Chips
- Embedded within card headers or navigation bars. Encapsulated in a light grey track (`rgba(118, 118, 128, 0.12)`), with active items indicated by a white sliding pill card casting a soft shadow (`0 2px 4px rgba(0, 0, 0, 0.08)`).

### Bottom Navigation Tab Bar
- Persistent bottom bar with translucent background (`rgba(249, 249, 249, 0.85)`), 20px blur, and 0.5px top divider.
- Icons use 24px glyphs with 2px stroke weight; active tabs highlight in `#0A84FF`, inactive tabs sit in `#8E8E93`.