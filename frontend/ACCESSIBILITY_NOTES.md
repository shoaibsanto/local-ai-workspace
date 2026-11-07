# Accessibility & Responsive Notes

## Breakpoints

- Single breakpoint used: Tailwind's `md:` (`width >= 48rem` = 768px), confirmed present
  in the built CSS (`dist/assets/*.css` contains `@media (width>=48rem)`).
- Below 768px: Sidebar becomes an off-canvas drawer (hidden by default, opened via a
  hamburger button in a mobile-only top bar), chat/composer padding shrinks
  (`px-3`/`pb-3` vs `px-4`/`pb-4`), and the model-picker's provider name is hidden to
  save horizontal space.
- At/above 768px: Sidebar renders inline (`hidden md:flex`), mobile top bar is hidden
  (`md:hidden`).

## Dark mode implementation

- Tailwind v4 custom variant in `src/index.css`:
  `@custom-variant dark (&:where(.dark, .dark *));` — this makes `dark:` classes apply
  based on a `.dark` class on `<html>`, not just the OS media query.
- `src/lib/theme.ts` (`useTheme`) sets `document.documentElement.classList` and
  `localStorage['theme']`. Default on first load follows
  `prefers-color-scheme: dark`; once the user explicitly toggles, that choice persists
  and overrides future OS-preference changes.
- Every existing component (Sidebar, Composer, MessageBubble incl. code blocks via
  `react-syntax-highlighter`'s `oneDark`/`oneLight` themes switched at runtime,
  SettingsModal, McpModal, App) has explicit `dark:` variants for backgrounds, borders,
  and text — not just inverted colors (e.g. code block background is `#0a0a0a` in dark
  mode, not a straight invert of the light `#fafafa`).

## Manual contrast verification (WCAG AA, target ≥ 4.5:1 for normal text, ≥ 3:1 for large text/UI)

Checked with standard relative-luminance contrast formula against the actual hex
values used in the stylesheet:

| Pair | Light mode | Ratio | Dark mode | Ratio |
|---|---|---|---|---|
| Body text / background | `#1f1b16` on `#faf9f7` | ~15.8:1 | `#ece7dd` on `#17140f` | ~14.9:1 |
| Primary button text | `#ffffff` on `#171717` (neutral-900) | ~17.9:1 | `#171717` on `#ffffff` | ~17.9:1 |
| Secondary/muted text | `#737373` (neutral-500) on `#faf9f7` | ~4.6:1 | `#a3a3a3` (neutral-400) on `#17140f` | ~7.9:1 |
| Sidebar text | `#404040` (neutral-700) on `#fafafa` (neutral-50) | ~9.7:1 | `#d4d4d4` (neutral-300) on `#0a0a0a` (neutral-950) | ~14.6:1 |
| Error text | `#b91c1c` (red-700) on `#fef2f2` (red-50) | ~6.9:1 | `#fca5a5` (red-300) on `#450a0a`-ish (red-950/40 over neutral-900) | ~7.5:1 (approx, translucent bg) |
| Risk badges (amber/medium) | `#b45309` (amber-700) on `#fef3c7` (amber-100) | ~4.6:1 | `#fcd34d` (amber-300) on dark amber overlay | ~8:1 (approx) |

All pairs above meet or exceed 4.5:1 for body text; large/bold UI text (badges,
buttons) meets the 3:1 minimum with considerable margin. These were computed manually
from the Tailwind palette hex values actually used in the components, not assumed.

## What was manually verified vs. what still needs real-device/screen-reader testing

**Verified (code review + computed contrast + build output inspection):**
- Dark/light class toggling and localStorage persistence logic.
- Focus trap behavior logic (Tab/Shift+Tab cycling, Escape, focus restoration) by
  reading `useFocusTrap.ts` against the WAI-ARIA focus-trap pattern.
- All icon-only buttons have `aria-label`.
- All modals use `role="dialog"`, `aria-modal="true"`, `aria-labelledby` pointing at a
  heading id.
- Form inputs in Settings/MCP modals have associated `<label htmlFor>` elements
  (visually hidden via `sr-only` where a placeholder already conveys the same info
  visually, to avoid duplicate visible labels).
- `aria-live="polite"` region on the message log (`role="log"`) that announces only at
  message-completion granularity (not per streamed token) via a separate
  `liveAnnouncement` state updated once per finished message.
- Built CSS contains the expected `md:` (768px) media query breakpoints and dark-mode
  classes (grepped from `dist/assets/*.css`).
- `npx tsc --noEmit -p tsconfig.app.json` → 0 errors. `npm run build` → succeeds.

**NOT verified — needs real hardware/AT testing before shipping to production:**
- Actual mobile touch behavior (drawer swipe/backdrop tap) on a real phone/tablet —
  this was reasoned about from code and Tailwind's computed breakpoint only; no real
  mobile browser was available in this environment.
- Screen reader behavior (VoiceOver/NVDA/JAWS) reading the `aria-live` region, dialog
  focus announcements, and label associations — the ARIA attributes are correct per
  spec but were not run through an actual screen reader.
- Real color perception testing (e.g. with a colorblindness simulator) beyond the
  numeric contrast-ratio calculations above.
- Backend endpoints for tool-call approval (`POST
  /api/conversations/:id/tool_calls/:toolCallId/approve`) and MCP reauthorize (`POST
  /api/mcp/servers/:id/reauthorize`) are called by this frontend but may not exist yet
  — they're being built by concurrent backend workstreams. The frontend code is written
  against the documented contract and is ready to integrate once those endpoints land.

## Modal implementation choice

Kept custom modals (not Radix Dialog) via a shared `ModalShell` component
(`src/components/ModalShell.tsx`) + `useFocusTrap` hook, so the same styling system,
fade/scale animation, and keyboard-shortcut `Escape` handling in `App.tsx` apply
uniformly across Settings/MCP/Approval/CommandPalette/ShortcutsHelp without pulling in
Radix's portal/positioning primitives. Radix Dialog remains installed and unused;
either approach is viable — documenting the choice here since the task allowed either.
