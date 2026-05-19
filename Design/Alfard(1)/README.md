# Alfard — Design System

> **Alfard** is an agentic AI dashboard. Operators come here to launch agents, supervise live runs, approve actions, and inspect what their AI workforce actually did. The product is dense in information but **calm, warm, and welcoming** — light by default.

This is the brand + design system. It defines the visual language, type, color, components, and a working UI kit you can fork to mock new screens.

The brand name "Alfard" is a contraction of **Alphard** — the lone bright star in Hydra, "the solitary one." The mark echoes that: a single soft-arrowed A with a metallic gradient, pointed forward but at rest.

---

## Index

| File | What it is |
| --- | --- |
| `colors_and_type.css` | All design tokens — paper/ink scales, semantics, type, spacing, radii, shadows, focus rings, motion. Light is default; dark activates via `[data-theme="dark"]`. |
| `preview/` | Static cards that populate the Design System tab |
| `ui_kits/alfard/index.html` | Full dashboard mock — light primary, dark toggle, soft rounded, Satoshi + Erode |
| `SKILL.md` | Skill manifest for using this system in other Claude Code projects |
| `README.md` | This file |

Fonts are loaded from **Fontshare** (Satoshi + Erode). The logo ships as two SVG files: `alfard-mark-dark.svg` (for light surfaces) and `alfard-mark-light.svg` (for dark surfaces) — found in both `preview/` and `ui_kits/alfard/`.

---

## Content fundamentals

**Voice.** Calm, plain-spoken, attentive. Alfard talks like a thoughtful colleague: never panicked, never effusive. Avoids AI buzzwords — no *intelligent*, *smart*, *magical*, *supercharged*, *blazing-fast*, *unleash*, *unlock*. Says what the thing does in concrete terms.

**Casing.** Sentence case for everything. Status pills are lowercase (`running`, `failed`, `needs approval`) — they sit beside text, not over it. Eyebrows are uppercase and tracked.

**Pronoun.** **You** when addressing the operator. The product refers to itself as **Alfard** in third person, not "I" or "we." Example: *"Alfard noticed 3 retries on this run."* It is named, it is helpful, but it is not a person.

**Numbers.** Always tabular. Always mono (Geist Mono fallback chain → JetBrains Mono → SF Mono). Currency two decimals, durations as `0:42` / `1:24:08`, percentages with `%` (no abbreviation like `12.8k` in tables; write `12,808`).

**No emoji.** Status is communicated by a colored dot inside a pill, plus a Lucide icon. The product never goes 🚀.

**Example copy:**
- *"Good morning, Sarah. Alfard is watching 14 agents this morning. Two need your eyes — everything else is running quietly."*
- *"researcher · streaming · 4,221 tok · $0.018"*
- *"3 runs failed in the last hour, all on `web.search`. Retry queue is paused."*
- *"You haven't touched this agent in 14 days. Archive?"*

**Never:**
- *"🎉 Your agents are crushing it today!"*
- *"Hey there! Looks like something went wrong 😕"*
- *"Supercharge your workflow with AI-powered agents."*

---

## Visual foundations

**Mode.** Light by default. Warm off-white background (`--paper-50` · `#FBFAF7`) — never stark white, never grey. Activated dark mode via `[data-theme="dark"]` on `<html>`; all tokens reroute automatically.

**Color philosophy.** Color is reserved for status. The dashboard reads in just two scales:
- **Paper** (warm off-whites, 6 steps) for all surfaces.
- **Ink** (warm near-blacks, 6 steps) for all text and the **accent**.
The "brand color" is **ink** — primary CTAs, focus rings, active nav, the dark half of the mark. There is no saturated brand blue or purple. The brand is the contrast.

Semantics are muted earth tones, used **only** in pills, badges, and status icons — never as full surfaces:
- **Sage green** (`#6B8E5A`) — positive, complete, live
- **Muted amber** (`#C89B4A`) — waiting, needs approval
- **Terracotta** (`#B85C5C`) — negative, failed
- **Slate blue** (`#6F8AA8`) — thinking, info (the only blue in the system)

Each semantic has a soft background, a text foreground, and a 1px border tone. Saturated swatches are never larger than a 12px pill or a 6px dot.

**Type.**
- **Satoshi** (Fontshare) for everything display — headings, buttons, labels, eyebrows, tabular numerals. Weight **540+** by default (bold) so the type does the visual work color usually does.
- **Erode** (Fontshare, warm serif) for body, descriptions, helper copy. This is what makes the product feel *welcoming* and *natural* instead of clinical SaaS.
- **System mono** stack for any id, timestamp, run id, file path, code.

Pairing rule: Satoshi for any line that *names a thing*, Erode for any line that *describes a thing*. Mono for any line that *identifies* a thing.

**Spacing.** 4px base. Welcoming density — rows in the runs table are 16px vertical, not 11px. The product should feel like a well-lit study, not a server console.

**Radii.** Soft. Rounded throughout.
- `--r-1` (8px) for chips inside table cells
- `--r-2` (12px) for buttons and inputs
- `--r-3` (16px) for cards, panels, run table container
- `--r-4` (22px) for large sheets and modals
- `--r-pill` (999px) only for status pills — they read as labels, not buttons
- `--r-0` (0px) never used decoratively

**Borders.** Hairline (1px), low-contrast. Most dividers are `--paper-300` so they read as gentle separation, not "outline." Strong borders only on focused inputs.

**Shadows.** Four-step elevation (`--shadow-1` → `--shadow-pop`). Soft and low-contrast — dark mode shadows are heavier but never harsh. Each card sits on a `shadow-1` resting elevation by default.

**Focus rings.** Ink-tinted (`rgba(20,19,15,0.12)` for default, `0.22` for strong, terracotta-tinted for invalid). No colored glow. The product is intentionally low-saturation, so a quiet 3px halo is enough.

**Backgrounds.** Flat warm cream. No gradients anywhere. No mesh, no glow, no decorative wash. The space between things does the work.

**Animation.** Restrained.
- `--dur-1` (140ms) for interactive state changes
- `--dur-3` (360ms) for panels sliding in
- The only continuously-animated elements are the **live dot pulse** on running agents (sage green) and the **thinking dots** on the composer (slate blue). Everything else is still.

**Hover.** Lift one surface step (`--bg` → `--surface` or `--surface` → `--paper-100`), no scale, no shadow change. Text color may shift one step toward ink-400.

**Press / active.** No scale. Background goes one step darker than hover.

**Transparency / blur.** Not used decoratively. The top bar is opaque and just sits on the page background. Modal scrims when needed.

**Imagery.** None by default. If imagery is ever needed for marketing or empty states, it should be **natural, warm, hand-drawn or photographic with warm light** — not schematic line-art, not stock photography. Think Kinfolk magazine, not technical diagram.

**Layout rules.**
- Top bar 60px, fixed. Brand always top-left, ⌘K search always center-right, theme toggle + bell + help + avatar top-right.
- Sidebar 256px on desktop, collapsible to 60px (icon-only).
- Right inspector 360px, slides in when an entity is selected.
- Main canvas is the only area that scrolls.
- CSS grid for the shell, flex for everything inside.

---

## Logo

The mark is a soft, arrowed capital A drawn as a single freeform shape with a diagonal metallic gradient. It is **not** placed inside a circular container — it stands on its own.

Two variants ship:

- **`alfard-mark-dark.svg`** — gradient runs dark → light. Use on **light** surfaces (paper backgrounds, marketing, default UI).
- **`alfard-mark-light.svg`** — gradient runs light → dark. Use on **dark** surfaces (ink backgrounds, dark-mode chrome).

The wordmark **Alfard** is set in Satoshi 700, tracking `-0.022em`. Mark and wordmark sit at the same x-height — never make the mark larger than the cap height of the wordmark.

The tagline *"A calmer way to run your agents."* is set in Erode regular, always under the wordmark, never above or beside.

See `preview/brand-logo.html` for the canonical lockups in both modes.

---

## Iconography

**Library:** [Lucide](https://lucide.dev) via CDN, stroke **1.5px**, default size **16px**, single-tone.

Icons inherit color from `currentColor`. They never get filled with brand color — there is no brand color. The one exception is status icons, which get a muted background tint matching their semantic pill (sage / amber / terracotta).

Common usage: `bot` (agent) · `workflow` · `activity` (runs) · `inbox` · `list-checks` (approvals) · `database` (memory) · `plug` (tools) · `key-round` (secrets) · `bar-chart-3` (telemetry) · `play` / `square` / `rotate-cw` (run controls) · `terminal` (raw logs).

No emoji. Status is dot + pill + Lucide icon.

---

## How to use this system

### In a static HTML mock
```html
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@500,600,700,900&f[]=erode@400,500&display=swap"/>
<link rel="stylesheet" href="colors_and_type.css"/>
<body>
  <button class="btn btn-primary">Run agent</button>
</body>
```

### Theming
Light is default. Activate dark:
```html
<html data-theme="dark">
```
All tokens reroute automatically. The dashboard's theme toggle stores the choice in `localStorage`.

### In a new product surface
Fork `ui_kits/alfard/index.html`. The grid shell, top bar, sidebar (workspace + infra + live agents), stat tiles, runs panel, table, pill, and inspector are the canonical implementations. Don't reinvent them.

---

## Caveats & known gaps

- **Fonts.** Satoshi and Erode load from Fontshare. If you need offline support, download the variable WOFF2s into `fonts/` and replace the `<link>` with local `@font-face`.
- **Logo ships as SVG.** Two variants in `preview/` and `ui_kits/alfard/`: `alfard-mark-dark.svg` (light surfaces) and `alfard-mark-light.svg` (dark surfaces).
- **No marketing surfaces or empty states** in the kit yet. Likely next: agent detail, workflow builder, approvals queue, settings, onboarding.
- **No imagery system.** The brand intentionally avoids stock photo + schematic illustration — if marketing wants imagery, we'll need a treatment direction.
- **Theme toggle** in the dashboard is on the top bar. If you want system-preference detection, wire it via `matchMedia('(prefers-color-scheme: dark)')` in the toggle script.
