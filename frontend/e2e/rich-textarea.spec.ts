import { expect, test } from '@playwright/test'

test('RichTextarea does not submit while IME composition is active', async ({ page }) => {
  await page.goto('/dev/rich-textarea')

  const editor = page.locator('.ProseMirror').first()
  await expect(editor).toBeVisible()
  await expect(page.getByText(/submits 0/)).toBeVisible()

  await editor.evaluate((node) => {
    ;(node as HTMLElement).focus()
  })
  await editor.evaluate((node) => {
    node.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: 'n' }))
    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    })
    Object.defineProperty(event, 'isComposing', { value: true })
    node.dispatchEvent(event)
    node.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '你' }))
  })

  await expect(page.getByText(/submits 0/)).toBeVisible()

  await editor.press('Enter')
  await expect(page.getByText(/submits 1/)).toBeVisible()
})
