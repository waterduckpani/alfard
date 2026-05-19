---
name: alfard-design
description: Use this skill to generate well-branded interfaces and assets for Alfard — an agentic AI dashboard — for production or throwaway prototypes/mocks. Contains design tokens, fonts, an SVG monogram, and a working dashboard UI kit. The aesthetic is calm, warm, light-primary, soft-rounded, with a black accent rather than a brand color.
user-invocable: true
---

Read `README.md` first, then explore `colors_and_type.css`, the `preview/` cards, and `ui_kits/alfard/index.html`.

When making visual artifacts, link the fonts and stylesheet:

```html
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@500,600,700,900&f[]=erode@400,500&display=swap"/>
<link rel="stylesheet" href="colors_and_type.css"/>
```

Default is light. Activate dark via `<html data-theme="dark">` — all tokens reroute automatically. The dashboard in `ui_kits/alfard/index.html` is the canonical surface: top bar + sidebar + main + right inspector, with a light/dark toggle in the top right. Fork it.

For production code, the only file you usually need is `colors_and_type.css`. Token prefixes:
- `--paper-0..500` — warm off-white surface scale (lightest → darkest cream)
- `--ink-50..500` — warm near-black ink scale (lightest text → solid)
- `--accent` — primary action color; in light = ink, in dark = paper
- `--ok / warn / err / info-*` — muted earthy semantics: sage / amber / terracotta / slate-blue
- `--bg / surface / surface-2 / fg / fg-1..3 / border / divider` — role-based aliases
- `--font-display` Satoshi · `--font-body` Erode · `--font-mono` system mono
- `--t-display / h1..h4 / label / body-lg / body / small / micro / eyebrow / mono / mono-sm` — type roles
- `--s-1..10` — 4px-base spacing
- `--r-0..5 / r-pill` — soft radii (r-2 = 12px buttons, r-3 = 16px cards, r-pill only for status pills)
- `--shadow-1..3 / shadow-pop` — soft elevation
- `--ring / ring-strong / ring-err` — quiet ink-tinted focus halos

**Visual rules to honor:**
- Light primary, dark secondary. Both have parity.
- No brand color. The accent is ink — primary CTAs are black on light, white on dark.
- Color is reserved for status (sage/amber/terracotta/slate-blue), and only inside pills, badges, dots, and status icons.
- Rounded everywhere (8–22px). Pills stay tight at 999px. Sharp corners only on intentional split-screens.
- Satoshi 540+ for any "named" line (headings, buttons, labels). Erode regular for any "described" line (body, helper, descriptions). Mono for any "identified" line (ids, timestamps, code).
- No emoji. No gradients. No decorative imagery. No glow effects.
- Animation: live dot pulse (sage) and thinking dots (slate blue) only. 140ms hovers. Otherwise still.
- Welcoming density: 16px row padding, not 11px.

**Logo:** soft arrowed **A** with a metallic top-to-bottom gradient. Two variants ship: `alfard-mark-dark.svg` (darker fill, for light surfaces) and `alfard-mark-light.svg` (lighter fill, for ink surfaces). The mark is freeform — no circular container. Wordmark in Satoshi 700, tracking `-0.022em`. Files live next to `preview/brand-logo.html` and in `ui_kits/alfard/`.

**Voice:** calm, plain-spoken, attentive. The product is named Alfard and refers to itself in third person. Sentence case throughout. Status microlabels are lowercase. Never effusive. Never emoji'd.

**Iconography:** Lucide via CDN (`https://unpkg.com/lucide@0.453.0/dist/umd/lucide.min.js`), then `lucide.createIcons({ attrs: { 'stroke-width': 1.5, width: 16, height: 16 } });`. Icons inherit `currentColor` and are single-tone.

If invoked without guidance, ask the user what surface they want (a new agent screen, settings flow, onboarding, marketing page, slide deck) and 2–3 clarifying questions, then act as a senior designer producing HTML or production code.
