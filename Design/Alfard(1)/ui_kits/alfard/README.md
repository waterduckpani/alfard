# Alfard UI Kit

A working dashboard mockup that demonstrates the design system in context.

## What's in here

- **`index.html`** — the **Runs** view. The most representative surface of the product: it shows the top bar, sidebar (with workspace nav + live-agents list), the main canvas with stat tiles + a runs table, and the right-hand inspector with run metadata + step trace + composer.

## Layout shell

```
┌────────────────────────────────────────────────────────────────┐
│ topbar (52px) — brand · crumbs · ⌘K search · bell · avatar      │
├──────────┬──────────────────────────────────────┬──────────────┤
│ sidebar  │ main canvas                          │ inspector    │
│ (240px)  │ (flex, scrolls)                      │ (340px)      │
│          │                                      │              │
│ nav      │ page-head · stat tiles · runs panel  │ run trace +  │
│ live     │                                      │ composer     │
│ agents   │                                      │              │
└──────────┴──────────────────────────────────────┴──────────────┘
```

Grid: `grid-template-columns: 240px 1fr 340px;` and `grid-template-rows: 52px 1fr;`. Top bar spans all columns.

## Patterns to copy

- **Topbar** — `.topbar` with `backdrop-filter: blur(8px)` over a semi-opaque `--ink-950`.
- **Nav item** — `.nav-item.active` has a left-edge `2px` signal-blue accent and a `rgba(77,124,254,0.08)` wash.
- **Live agent row** — `.agent .dot.live` is the canonical beacon pulse.
- **Stat tile** — `.stat` with mono `tabular-nums` value + an eyebrow label + a `+x.x` delta in ok/err color.
- **Pill** — `.pill.live / .ok / .warn / .err / .queued` with a dot. The `.live` dot animates; the others are static.
- **Run table row** — 11px vertical padding, mono columns right-aligned, hover wash is `rgba(77,124,254,0.03)`.
- **Inspector step trace** — `.insp-step.done / .live` with a 1px gutter line and 8px node. The `live` node pulses.
- **Composer** — `.composer` with a textarea, attach chips, model chip, and signal-blue send button.

## Extending the kit

Surfaces this kit doesn't cover yet but probably need to exist:

- **Agent detail** (single agent view: graph of recent runs, success/cost trends, tool calls, prompt history)
- **Workflow builder** (node-graph canvas for composing multi-step agents)
- **Approvals queue** (list of pending human-in-the-loop steps with side-by-side diffs)
- **Inbox** (Alfard messages: budget alerts, failures, approvals)
- **Settings** (team, models, secrets, billing)
- **Auth / onboarding**
- **Empty states**

If you build one, drop it next to `index.html` (e.g. `workflow-builder.html`) and reuse the same shell, type, and tokens from `colors_and_type.css`.

## Components used

| Component | Source preview card |
|---|---|
| Buttons | `preview/comp-buttons.html` |
| Inputs / select | `preview/comp-inputs.html` |
| Status pills | `preview/comp-status-pills.html` |
| Cards | `preview/comp-cards.html` |
| Composer | `preview/comp-composer.html` |
| Command palette | `preview/comp-cmd-palette.html` |
| Agent timeline | `preview/comp-timeline.html` |
| Icons | `preview/iconography.html` |
