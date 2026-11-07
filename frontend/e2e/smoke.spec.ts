import { test, expect } from '@playwright/test'

/**
 * Minimal production smoke test: loads the real built `dist` output (served
 * via `vite preview`, started automatically by playwright.config.ts's
 * webServer), asserts the main heading and composer are visible, and asserts
 * zero console errors/warnings were logged during load -- the regression this
 * guards against is a blank white screen or a silent render crash after
 * introducing React.lazy/Suspense boundaries and the ErrorBoundary.
 */
test('loads the built app with no console errors and shows heading + composer', async ({ page }) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => {
    pageErrors.push(err.message)
  })

  await page.goto('/')

  // Main empty-state heading, shown before any conversation is loaded.
  await expect(page.getByText('How can I help you today?')).toBeVisible()

  // Composer input (message box) is present and interactive.
  const composer = page.getByLabel('Message input')
  await expect(composer).toBeVisible()
  await composer.fill('Hello, this is a smoke test')
  await expect(composer).toHaveValue('Hello, this is a smoke test')

  // Keyboard shortcut smoke check: Escape should not throw, Cmd/Ctrl+/ should
  // open the shortcuts help modal (lazy-loaded) without errors.
  await page.keyboard.press('Control+/')
  await expect(page.getByText(/keyboard shortcuts/i)).toBeVisible({ timeout: 5000 })
  await page.keyboard.press('Escape')
  await expect(page.getByText(/keyboard shortcuts/i)).not.toBeVisible()

  expect(consoleErrors, `console errors found: ${JSON.stringify(consoleErrors)}`).toHaveLength(0)
  expect(pageErrors, `uncaught page errors found: ${JSON.stringify(pageErrors)}`).toHaveLength(0)
})
