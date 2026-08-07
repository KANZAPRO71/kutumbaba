import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'

const OUT = '/opt/cursor/artifacts/screenshots'
const BASE = process.env.STUDIO_URL ?? 'http://127.0.0.1:5173'

async function runToko(page) {
  await page.getByTestId('suggestion-chip').first().click()
  await page.locator('h2', { hasText: 'My Shop' }).waitFor({ timeout: 10_000 })
  await page.locator('p', { hasText: 'Build selesai' }).waitFor({ timeout: 10_000 })
  await page.screenshot({ path: `${OUT}/03-toko-preview.png`, fullPage: true })

  await page.getByTestId('add-to-cart').first().click()
  await page.getByText('Keranjang · 1').waitFor()
  await page.screenshot({ path: `${OUT}/04-add-to-cart.png`, fullPage: true })

  await page.getByRole('button', { name: 'Add Produk' }).click()
  await page.getByText('Produk Baru 3', { exact: true }).waitFor()
  await page.screenshot({ path: `${OUT}/05-add-produk.png`, fullPage: true })

  return {
    cart: await page.getByText(/Keranjang ·/).innerText(),
    products: await page.locator('[data-testid="add-to-cart"]').count(),
  }
}

async function runProyek(page) {
  await page.getByTestId('suggestion-chip').nth(1).click()
  await page.locator('h2', { hasText: 'Project Dashboard' }).waitFor({ timeout: 10_000 })
  await page.locator('p', { hasText: 'Build selesai' }).waitFor({ timeout: 10_000 })
  await page.screenshot({ path: `${OUT}/06-proyek-preview.png`, fullPage: true })

  const beforePending = await page.getByText('Pending').locator('..').locator('p').first().innerText()
  await page.getByTestId('complete-task').click()
  await page.getByTestId('toast').waitFor()
  await page.screenshot({ path: `${OUT}/07-complete-task.png`, fullPage: true })

  await page.getByRole('button', { name: 'Add Modul' }).click()
  await page.getByText(/Modul baru/i).first().waitFor()
  await page.screenshot({ path: `${OUT}/08-add-modul.png`, fullPage: true })

  return {
    beforePending,
    notes: await page.locator('li').filter({ hasText: /Modul baru|Rencana|Review/ }).count(),
  }
}

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

  const toko = await runToko(page)

  // Fresh session for mahasiswa persona (matches right screen in concept)
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await page.getByTestId('start-studio').click()
  await page.locator('h2', { hasText: 'AI Assistant' }).waitFor()
  const proyek = await runProyek(page)

  console.log(
    JSON.stringify(
      {
        ok: true,
        toko,
        proyek,
        screenshots: [
          `${OUT}/01-landing.png`,
          `${OUT}/02-workspace.png`,
          `${OUT}/03-toko-preview.png`,
          `${OUT}/04-add-to-cart.png`,
          `${OUT}/05-add-produk.png`,
          `${OUT}/06-proyek-preview.png`,
          `${OUT}/07-complete-task.png`,
          `${OUT}/08-add-modul.png`,
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
