import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'

const OUT = '/opt/cursor/artifacts/screenshots'
const BASE = process.env.STUDIO_URL ?? 'http://127.0.0.1:5173'

async function main() {
  await mkdir(OUT, { recursive: true })
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 430, height: 900 } })

  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.locator('h1', { hasText: 'Studio' }).waitFor()
  await page.screenshot({ path: `${OUT}/01-landing.png`, fullPage: true })

  await page.getByTestId('start-studio').click()
  await page.locator('h2', { hasText: 'AI Assistant' }).waitFor()
  await page.screenshot({ path: `${OUT}/02-workspace.png`, fullPage: true })

  await page.getByTestId('suggestion-chip').first().click()
  await page.locator('h2', { hasText: 'My Shop' }).waitFor({ timeout: 10_000 })
  await page.locator('p', { hasText: 'Build selesai' }).waitFor({ timeout: 10_000 })
  await page.screenshot({ path: `${OUT}/03-toko-preview.png`, fullPage: true })

  await page.getByTestId('add-to-cart').first().click()
  await page.getByText(/masuk keranjang/i).waitFor({ timeout: 5_000 })
  await page.getByText('Keranjang · 1').waitFor()
  await page.screenshot({ path: `${OUT}/04-add-to-cart.png`, fullPage: true })

  await page.getByRole('button', { name: 'Add Produk' }).click()
  await page.getByText('Produk Baru 3', { exact: true }).waitFor()
  await page.screenshot({ path: `${OUT}/05-add-produk.png`, fullPage: true })

  console.log(
    JSON.stringify(
      {
        ok: true,
        cart: await page.getByText(/Keranjang ·/).innerText(),
        products: await page.locator('[data-testid="add-to-cart"]').count(),
        screenshots: [
          `${OUT}/01-landing.png`,
          `${OUT}/02-workspace.png`,
          `${OUT}/03-toko-preview.png`,
          `${OUT}/04-add-to-cart.png`,
          `${OUT}/05-add-produk.png`,
        ],
      },
      null,
      2,
    ),
  )

  await browser.close()
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
