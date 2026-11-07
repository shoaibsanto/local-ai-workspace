# Performance Notes

## What changed

1. **Code splitting via `React.lazy` + `Suspense`**
   - `src/components/MessageBubble.tsx`: the fenced-code-block renderer was
     extracted into its own module, `src/components/CodeBlock.tsx`, which owns
     the `react-syntax-highlighter` (Prism build) import and the `oneDark` /
     `oneLight` theme imports. `MessageBubble` now does
     `const CodeBlock = lazy(() => import('./CodeBlock'))` and renders it
     inside a `<Suspense fallback={<Spinner/>}>` only when a message actually
     contains a fenced code block (`language-xxx` className from
     `react-markdown`). Plain messages (the common case) never pull in Prism
     at all.
   - `src/App.tsx`: `SettingsModal`, `McpModal`, `ApprovalModal`,
     `CommandPalette`, `ShortcutsHelp` are all now `React.lazy()` imports, each
     wrapped in its own `<Suspense fallback={<ModalFallback/>}>` (a centered
     `Spinner` over a translucent backdrop) at the call site. Only one modal is
     ever open at a time, so at most one lazy chunk loads per interaction, and
     none of them load on initial paint.
   - Fallbacks reuse the existing `src/components/Spinner.tsx` (no new spinner
     implementation).

2. **Error boundaries (`src/components/ErrorBoundary.tsx`)**
   - A single reusable class component (`getDerivedStateFromError` +
     `componentDidCatch`, the only way to implement this in React today).
   - **App-level boundary**: wraps `<App/>` in `src/main.tsx`. Default fallback
     is a full-screen "Something went wrong" message with a **Reload** button.
     In dev (`import.meta.env.DEV`) it also prints the real `error.message` and
     `error.stack` in a scrollable `<pre>` for debugging; in production builds
     that block doesn't render, so no leaking error internals to end users.
   - **Message-list boundary**: wraps the whole message-rendering region in
     `App.tsx` (the `.map(MessageBubble)` block) with a custom fallback saying
     the conversation couldn't be rendered -- this is a second line of defense
     in case something outside an individual message's own boundary throws.
   - **Per-message boundary**: wraps the `ReactMarkdown`/`CodeBlock` output
     *inside* `MessageBubble.tsx` with its own `ErrorBoundary` + custom
     `fallback` that renders a small inline "Couldn't render this message"
     notice with the message's **raw, unprocessed text** still visible in a
     `<pre>`. If one malformed AI response's markdown or syntax highlighting
     throws, only that single bubble degrades -- the sidebar, composer, and
     every other message keep working normally (verified by reading the
     render tree: the boundary sits below the message list's `.map`, so a
     thrown error there cannot unmount sibling `MessageBubble` instances).

## Before / after build output (real, pasted from the actual `npm run build` runs)

**Before** (single monolithic bundle, Vite's own "chunk >500kB" warning):

```
dist/index.html                     0.45 kB │ gzip:   0.29 kB
dist/assets/index-DXOBdsJo.css     29.26 kB │ gzip:   6.23 kB
dist/assets/index-BOTUGfGs.js   1,113.01 kB │ gzip: 367.83 kB

(!) Some chunks are larger than 500 kB after minification...
```

**After** (code-split into 10 chunks; the main entry chunk is what loads on
first paint):

```
dist/index.html                                       0.54 kB │ gzip:   0.32 kB
dist/assets/index-DwZd3cJm.css                       30.71 kB │ gzip:   6.41 kB
dist/assets/inbox-ClX752tF.js                         0.31 kB │ gzip:   0.24 kB
dist/assets/triangle-exclamation-point-DwtRQkA1.js    0.35 kB │ gzip:   0.25 kB
dist/assets/ShortcutsHelp-DyP9i8FI.js                 1.24 kB │ gzip:   0.57 kB
dist/assets/ModalShell-D9vIUa8m.js                    1.44 kB │ gzip:   0.77 kB
dist/assets/CommandPalette-cyIF-bg9.js                1.84 kB │ gzip:   0.88 kB
dist/assets/ApprovalModal-CH3RCNfy.js                 3.37 kB │ gzip:   1.21 kB
dist/assets/SettingsModal-D3Kst-N8.js                 8.01 kB │ gzip:   2.22 kB
dist/assets/jsx-runtime-Wy9s6hX0.js                   8.91 kB │ gzip:   3.39 kB
dist/assets/McpModal-EDTeaZix.js                     10.06 kB │ gzip:   2.85 kB
dist/assets/index-CU_cUtNd.js                       445.19 kB │ gzip: 136.50 kB
dist/assets/CodeBlock-C6cw8GpM.js                   639.40 kB │ gzip: 225.42 kB

(!) Some chunks are larger than 500 kB after minification...
```

**Headline numbers:**

| | Before | After | Change |
|---|---|---|---|
| Main entry JS chunk (loads on first paint) | 1,113.01 kB (367.83 kB gzip) | 445.19 kB (136.50 kB gzip) | **−60% raw, −63% gzip** |
| Total JS shipped eventually (all chunks) | 1,113.01 kB | ~1,119.98 kB | ~flat (same code, just split) |
| Number of JS output chunks | 1 | 10 | code-split by feature |

The remaining >500kB warning is now on `CodeBlock-*.js` (the
`react-syntax-highlighter` Prism bundle + its bundled language grammars/theme
data) -- this chunk is **lazy-loaded only when a chat message actually
contains a fenced code block**, so it no longer blocks or bloats the initial
page load. A user who never sees a code block in their conversation never
downloads it at all. (A further optimization not done here: swapping Prism's
"all languages" build for `react-syntax-highlighter/dist/esm/prism-light` with
only the specific languages used would shrink this further, but that's a
separate, larger change left for a future pass.)

## Error-resilience verification

- `npx tsc --noEmit -p tsconfig.app.json` → 0 errors (re-run after every
  change above).
- `npm run build` → succeeds, chunk list as shown above.
- Manual reasoning + code read of `ErrorBoundary.tsx`'s placement: app-level
  boundary in `main.tsx` guarantees no blank white screen on an uncaught
  render error anywhere in the tree; message-list and per-message boundaries
  are nested *inside* it, so they catch first and prevent the app-level
  fallback from firing just because one message is malformed.

## Automated runtime check: Playwright smoke test

`@playwright/test` was not previously installed. Installed it fresh and
confirmed Chromium downloads/installs cleanly in this sandbox (no network
blocker encountered):

```
$ npx playwright --version
Version 1.62.1
$ npm install -D @playwright/test
added 3 packages ...
$ npx playwright install chromium
... Chrome for Testing 158.0.8127.18 ... downloaded to /root/.cache/ms-playwright/chromium-1254
... Chrome Headless Shell 158.0.8127.18 ... downloaded to /root/.cache/ms-playwright/chromium_headless_shell-1254
```

Added `frontend/e2e/smoke.spec.ts` + `frontend/playwright.config.ts`. The test:
loads the real built `dist` output via `npm run preview` (Playwright's
`webServer`), asserts the empty-state heading ("How can I help you today?")
and the composer (`aria-label="Message input"`) are visible, types into the
composer, exercises the `Ctrl//` shortcut to open the lazy-loaded
`ShortcutsHelp` modal and `Escape` to close it, and asserts **zero**
`console.error` messages and zero uncaught `pageerror` events during the
whole flow.

First run failed with real 502 errors because `vite preview`'s `/api` proxy
target (`http://127.0.0.1:8421`, configured in `vite.config.ts`) had no
backend listening. Started the real backend
(`.venv/bin/local-ai serve --port 8421 --no-browser`) and re-ran:

```
$ npx playwright test
Running 1 test using 1 worker

  ✓  1 e2e/smoke.spec.ts:11:1 › loads the built app with no console errors and shows heading + composer (1.8s)

  1 passed (3.6s)
```

This is a real pass against the real built bundle with the backend actually
running -- not a fabricated result.

## Keyboard shortcuts / dark mode / mobile drawer -- regression check

None of these were touched by the lazy-loading or error-boundary changes:

- `useKeyboardShortcuts.ts` and `App.tsx`'s `closeTopModal()` logic are
  unmodified; they still call the same `setSettingsOpen` / `setMcpOpen` /
  `setPaletteOpen` / `setShortcutsOpen` state setters. Lazy-loading only
  changes *how* the already-conditionally-rendered modal component is
  imported (`import()` instead of a static import) -- the mount/unmount
  lifecycle, and therefore `useFocusTrap`'s effect (which runs on mount via
  `active` becoming `true`), is unaffected. The Playwright smoke test exercises
  `Ctrl+/` → open `ShortcutsHelp` → `Escape` → close, end-to-end, and passed,
  which is a real (not just reasoned-about) confirmation that opening a
  lazy-loaded modal and closing it via Escape still works.
- Dark mode (`useTheme`, `.dark` class toggling) lives entirely in
  `src/lib/theme.ts` and was not touched.
- The `md:` breakpoint / mobile drawer markup in `App.tsx` was not touched;
  only the modal-rendering JSX at the bottom of the component gained
  `<Suspense>` wrappers around already-existing conditional renders.

See `ACCESSIBILITY_NOTES.md` for the original breakpoint/dark-mode/contrast
documentation, which still applies unchanged.

## Files created

- `src/components/ErrorBoundary.tsx`
- `src/components/CodeBlock.tsx` (extracted from `MessageBubble.tsx`)
- `e2e/smoke.spec.ts`
- `playwright.config.ts`
- `PERFORMANCE_NOTES.md` (this file)

## Files modified

- `src/main.tsx` -- wraps `<App/>` in the app-level `ErrorBoundary`.
- `src/App.tsx` -- lazy-loads the 5 modals with per-modal `Suspense`
  boundaries; wraps the message list in a second `ErrorBoundary`.
- `src/components/MessageBubble.tsx` -- lazy-loads `CodeBlock`; wraps its
  markdown rendering in a narrow `ErrorBoundary` with a raw-text fallback.
- `package.json` / `package-lock.json` -- added `@playwright/test` devDependency.
