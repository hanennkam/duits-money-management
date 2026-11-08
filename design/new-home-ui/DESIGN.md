---
name: Aetherial Liquid Capital
colors:
  surface: '#f9f9ff'
  surface-dim: '#d4dae9'
  surface-bright: '#f9f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f0f3ff'
  surface-container: '#e8eefd'
  surface-container-high: '#e3e8f7'
  surface-container-highest: '#dde2f2'
  on-surface: '#161c26'
  on-surface-variant: '#414755'
  inverse-surface: '#2b313c'
  inverse-on-surface: '#ecf0ff'
  outline: '#717786'
  outline-variant: '#c1c6d7'
  surface-tint: '#005bc1'
  primary: '#0058bc'
  on-primary: '#ffffff'
  primary-container: '#0070eb'
  on-primary-container: '#fefcff'
  inverse-primary: '#adc6ff'
  secondary: '#006398'
  on-secondary: '#ffffff'
  secondary-container: '#6cbdfe'
  on-secondary-container: '#004b75'
  tertiary: '#006a43'
  on-tertiary: '#ffffff'
  tertiary-container: '#008656'
  on-tertiary-container: '#f6fff6'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d8e2ff'
  primary-fixed-dim: '#adc6ff'
  on-primary-fixed: '#001a41'
  on-primary-fixed-variant: '#004493'
  secondary-fixed: '#cde5ff'
  secondary-fixed-dim: '#94ccff'
  on-secondary-fixed: '#001d32'
  on-secondary-fixed-variant: '#004b74'
  tertiary-fixed: '#81f9bb'
  tertiary-fixed-dim: '#64dca0'
  on-tertiary-fixed: '#002112'
  on-tertiary-fixed-variant: '#005233'
  background: '#f9f9ff'
  on-background: '#161c26'
  surface-variant: '#dde2f2'
typography:
  display-hero:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.03em
  display-hero-mobile:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-lg:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 18px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
  metric-tabular:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-base: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
  space-2xl: 3rem
---

## Brand & Style

The design system embodies a pristine, fluid, and hyper-reliable financial ecosystem engineered for modern iOS and mobile-first wealth management. It balances high-precision institutional banking clarity with tactile, light-refracting frosted glassmorphism derived from translucent physical materials.

### Visual Character
- **Aesthetic Movement:** Modern iOS Glassmorphism combined with clean HIG-inspired structural minimalism. Surfaces feel layered, optical, and weightless, using subtle translucent materials, specular rim highlights, and ambient azure illumination.
- **Tone & Mood:** Effortless, crystalline, secure, and serene. It eliminates financial anxiety through spacious layouts, calm cool-spectrum tones, and high-legibility typographic hierarchies.
- **Target Audience:** Digital natives, wealth managers, and modern personal finance users who demand the tactile polish of Apple interface standards coupled with seamless financial telemetry.

## Colors

The palette establishes an airy, light-refracting canvas anchored by Apple-standard cobalt blue and airy sky azure, complemented by calibrated financial semaphores.

### Palette Architecture
- **Primary Cobalt (`#007AFF` / `#1E60E2`):** Delivers decisive call-to-action power, key navigation highlights, and interactive states.
- **Secondary Sky Glass (`#64B5F6` / `#70A1FF`):** Powers liquid linear gradients, soft active indicators, and volumetric frosted layers matching the icon's translucent body.
- **Background & Canvas (`#F4F7FC` / `#F0F4FA`):** An ultra-light cool tinted white providing low-glare depth beneath transparent frosted glass modules.
- **Surfaces (`#FFFFFF` & Frosted Glass):** Crisp, elevated white opaque cards alternating with backdrop-blurred translucent layers (`rgba(255, 255, 255, 0.75)` with `backdrop-filter: blur(24px)`).
- **Semantics:**
  - **Inflow / Yield (`#30B078` / `#34C759`):** Soft emerald and mint for incoming revenue, asset growth, and positive status.
  - **Outflow / Alert (`#EB5757` / `#FF453A`):** Calibrated crimson-coral for expenses, negative variance, and urgent notices.

## Typography

Typography relies on a crisp, utilitarian Inter type scale optimized for Apple HIG proportions, high micro-legibility, and dense numeric data.

- **Numerics & Tabular Figures:** All financial tables, account values, and transaction feeds must enforce `font-feature-settings: "tnum" 1, "cv05" 1` to ensure alignment across decimal points and dynamic tickers.
- **Visual Weight & Hierarchy:** Primary financial balance heads use negative tracking (`-0.02em` to `-0.03em`) and heavy weights to command authority. Tertiary meta-labels maintain distinct spacing and uppercase or title-case micro-weights.
- **Scale Continuity:** Displays collapse proportionally from desktop down to handheld devices to ensure no metric truncates on narrower mobile viewports.

## Layout & Spacing

The layout operates on an 8pt baseline rhythmic grid adapted into flexible container units.

- **Mobile First Framework:** Content structures conform to a fluid 4-column setup on mobile devices with `16px` margins, expanding into an 8-column tablet array, and resolving to a 12-column desktop bento matrix with a max-width envelope of `1200px`.
- **Bento Composition:** Layouts prioritize modular cards and bento dashboard blocks. Modules nest content using strict internal padding (`16px` for auxiliary metrics, `20px` to `24px` for hero transaction summaries).
- **Rhythmic Gaps:** Layout spacing preserves generous negative breathing room to accentuate the optical glow of translucent frosted cards.

## Elevation & Depth

Visual hierarchy does not use murky, dark drop shadows. Instead, it relies on light transmission, soft ambient azure diffusion, and specular border highlights.

### Elevation Levels
- **Base Canvas (Level 0):** `#F4F7FC` ultra-light blue-tinted matte surface.
- **Glass Module (Level 1):** Translucent frosted glass with `background: rgba(255, 255, 255, 0.72)`, `backdrop-filter: blur(20px)`, a 1px border highlight of `rgba(255, 255, 255, 0.85)` on top/left, and a subtle drop shadow: `0 8px 32px -4px rgba(30, 96, 226, 0.06), 0 2px 6px -1px rgba(30, 96, 226, 0.04)`.
- **Elevated Interactive Card (Level 2):** Pure opaque `#FFFFFF` surface accompanied by a dual-component shadow: `0 12px 36px -6px rgba(0, 122, 255, 0.08), 0 4px 12px -2px rgba(29, 35, 46, 0.03)`.
- **Floating Modals & Sheets (Level 3):** High-blur frosted treatment (`backdrop-filter: blur(36px)`) with `rgba(255, 255, 255, 0.88)` and a deep diffused floor glow: `0 24px 64px -12px rgba(0, 70, 180, 0.14)`.

## Shapes

The design system incorporates full pill and hyper-radiused geometry, matching native Apple interface curvature and the pill-like closure of the wallet reference.

### Corner Radius System
- **Pill Badges & Buttons (`rounded-full` / `9999px`):** Used universally for all action chips, category filters, interactive buttons, and wallet status indicators.
- **Primary Hero Cards (`rounded-xl` / `24px`):** Main balance cards and high-elevation modals feature smooth `24px` continuous squircle corners.
- **Secondary Bento Modules (`rounded-lg` / `20px`):** Analytical breakout blocks, spend categories, and ledger groupings use `20px` radii.
- **Inner Controls & Mini Cards (`rounded` / `16px`):** Input containers, nested chart areas, and list row selectors conform to `16px`.

## Components

### Buttons
- **Primary Action:** Rich blue gradient (`linear-gradient(135deg, #70A1FF 0%, #007AFF 100%)`), pure white typography, full pill shape (`9999px`), with an inner ambient glow (`box-shadow: 0 4px 16px rgba(0, 122, 255, 0.35)`). Active state applies a subtle scale compression (`scale(0.98)`).
- **Secondary Glass Action:** Translucent backdrop (`rgba(255, 255, 255, 0.65)`), 1px stroke (`rgba(30, 96, 226, 0.12)`), text colored in `#007AFF`.
- **Ghost / Tertiary:** Transparent background with `#007AFF` interactive state and `rgba(0, 122, 255, 0.06)` hover pill background.

### Cards & Modules
- **Hero Wallet Card:** Multi-stop diagonal gradient (`linear-gradient(135deg, #64B5F6 0%, #1E60E2 100%)`), displaying white specular typography, frosted semi-transparent pill badges, and ambient inner glow overlays.
- **Bento Metric Cards:** Crisp `#FFFFFF` or glass frosted panels with soft 1px border strokes (`rgba(255, 255, 255, 0.9)` top and `rgba(30, 96, 226, 0.08)` bottom) with `24px` or `20px` radii.

### Input Fields
- Enclosed pill and squircle fields (`16px` radius) with `rgba(255, 255, 255, 0.8)` background, frosted blur, and soft inset border (`rgba(30, 96, 226, 0.1)`). On focus: border shifts to solid `#007AFF` with a faint `0 0 0 4px rgba(0, 122, 255, 0.12)` ring.

### Chips & Filter Pills
- Pill-shaped (`9999px`) tags. Unselected: `background: rgba(255, 255, 255, 0.6)`, text `#1D232E`. Selected: `background: #007AFF`, text `#FFFFFF`, accompanied by soft primary box shadow.

### Lists & Transaction Feeds
- Contained within unified glass panels. Rows are separated by ultra-fine horizontal dividing rules (`rgba(30, 96, 226, 0.06)`). Each entry features a 44px rounded circular icon container (soft mint or soft coral tint depending on transaction direction) with bold tabular amount figures.