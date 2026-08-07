import { chromium } from 'playwright'
import { mkdir, copyFile } from 'node:fs/promises'
import { join } from 'node:path'

const OUT = '/opt/cursor/artifacts'
const SHOTS = join(OUT, 'screenshots')
const BASE = process.env.STUDIO_URL ?? 'http://127.0.0.1:5173'

async function main() {
  await mkdir(SHOTS, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 430, height: 900 },
    recordVideo: { dir: join(OUT, 'video-tmp'), size: { width: 430, height: 900 } },
  })
  const page = await context.newPage()

  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.getByTestId('start-studio').click()
  await page.locator('h2', { hasText: 'AI Assistant' }).waitFor()
  await page.waitForTimeout(600)

  await page.getByTestId('suggestion-chip').first().click()
  await page.locator('h2', { hasText: 'My Shop' }).waitFor({ timeout: 10_000 })
  await page.locator('p', { hasText: 'Build selesai' }).waitFor({ timeout: 10_000 })
  await page.waitForTimeout(700)

  await page.getByTestId('add-to-cart').first().click()
  await page.getByText('Keranjang · 1').waitFor()
  await page.waitForTimeout(900)

  await page.getByRole('button', { name: 'Add Produk' }).click()
  await page.getByText('Produk Baru 3', { exact: true }).waitFor()
  await page.waitForTimeout(1200)

  const video = page.video()
  await context.close()
  await browser.close()

  if (video) {
    const path = await video.path()
    const dest = join(OUT, 'studio-hello-world.webm')
    await copyFile(path, dest)
    console.log(JSON.stringify({ ok: true, video: dest }))
  }
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
