import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  assistantReply,
  createAppFromPrompt,
  detectTemplate,
  formatRupiah,
} from './studio.ts'

describe('detectTemplate', () => {
  it('detects toko online prompts', () => {
    assert.equal(
      detectTemplate('Buat toko online sederhana dengan daftar produk'),
      'toko',
    )
  })

  it('detects project management prompts', () => {
    assert.equal(
      detectTemplate('Bangun aplikasi manajemen proyek untuk kuliah'),
      'proyek',
    )
  })

  it('falls back to blank', () => {
    assert.equal(detectTemplate('halo studio'), 'blank')
  })
})

describe('createAppFromPrompt', () => {
  it('seeds UMKM shop products', () => {
    const app = createAppFromPrompt('Buat toko online UMKM')
    assert.equal(app.template, 'toko')
    assert.equal(app.title, 'My Shop')
    assert.ok(app.products.length >= 2)
  })

  it('seeds mahasiswa project dashboard', () => {
    const app = createAppFromPrompt('Dashboard proyek kuliah mahasiswa')
    assert.equal(app.template, 'proyek')
    assert.equal(app.title, 'Project Dashboard')
    assert.ok(app.stats.tasks > 0)
  })
})

describe('helpers', () => {
  it('formats rupiah', () => {
    assert.match(formatRupiah(150000), /150.?000/)
  })

  it('returns assistant copy for toko builds', () => {
    const app = createAppFromPrompt('toko online')
    assert.match(assistantReply('buat toko', app), /toko online/i)
  })
})
