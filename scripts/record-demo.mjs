import { chromium } from 'playwright'
import { mkdir, copyFile } from 'node:fs/promises'
import { join } from 'node:path'

const OUT = '/opt/cursor/artifacts'
const BASE = process.env.STUDIO_URL ?? 'http://127.0.0.1:5173'

async function main() {
  await mkdir(OUT, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 430, height: 900 },
    recordVideo: { dir: join(OUT, 'video-tmp'), size: { width: 430, height: 900 } },
  })
  const page = await context.newPage()

  // UMKM path
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  await page.getByTestId('start-studio').click()
  await page.locator('h2', { hasText: 'AI Assistant' }).waitFor()
  await page.waitForTimeout(400)
  await page.getByTestId('suggestion-chip').first().click()
  await page.locator('h2', { hasText: 'My Shop' }).waitFor({ timeout: 10_000 })
  await page.waitForTimeout(500)
  await page.getByTestId('add-to-cart').first().click()
  await page.getByText('Keranjang · 1').waitFor()
  await page.waitForTimeout(700)

  // Mahasiswa path
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForTimeout(400)
  await page.getByTestId('start-studio').click()
  await page.getByTestId('suggestion-chip').nth(1).click()
  await page.locator('h2', { hasText: 'Project Dashboard' }).waitFor({ timeout: 10_000 })
  await page.waitForTimeout(500)
  await page.getByTestId('complete-task').click()
  await page.waitForTimeout(600)
  await page.getByRole('button', { name: 'Add Modul' }).click()
  await page.waitForTimeout(1000)

  const video = page.video()
  await context.close()
  await browser.close()

  if (video) {
    const path = await video.path()
    const dest = join(OUT, 'studio-dual-persona.webm')
    await copyFile(path, dest)
    console.log(JSON.stringify({ ok: true, video: dest }))
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
