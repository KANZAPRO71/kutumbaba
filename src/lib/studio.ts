export type AppTemplate = 'toko' | 'proyek' | 'blank'

export type Product = {
  id: string
  name: string
  price: number
  tag: string
}

export type ProjectStats = {
  tasks: number
  completed: number
  pending: number
}

export type GeneratedApp = {
  id: string
  template: AppTemplate
  title: string
  statusLabel: string
  products: Product[]
  stats: ProjectStats
  notes: string[]
}

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant' | 'system'
  text: string
}

const TOKO_KEYWORDS = [
  'toko',
  'online',
  'shop',
  'produk',
  'umkm',
  'jual',
  'dagang',
  'ecommerce',
  'e-commerce',
]

const PROYEK_KEYWORDS = [
  'proyek',
  'project',
  'kuliah',
  'mahasiswa',
  'tugas',
  'manajemen',
  'dashboard',
  'tim',
  'team',
]

export function detectTemplate(prompt: string): AppTemplate {
  const p = prompt.toLowerCase()
  const tokoScore = TOKO_KEYWORDS.filter((k) => p.includes(k)).length
  const proyekScore = PROYEK_KEYWORDS.filter((k) => p.includes(k)).length
  if (tokoScore === 0 && proyekScore === 0) return 'blank'
  return tokoScore >= proyekScore ? 'toko' : 'proyek'
}

export function formatRupiah(value: number): string {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0,
  }).format(value)
}

export function createAppFromPrompt(prompt: string): GeneratedApp {
  const template = detectTemplate(prompt)
  const id = `app-${Date.now()}`

  if (template === 'toko') {
    return {
      id,
      template,
      title: 'My Shop',
      statusLabel: 'Membuat Toko Online...',
      products: [
        {
          id: 'p1',
          name: 'Casual Sneakers',
          price: 150_000,
          tag: 'Fashion',
        },
        {
          id: 'p2',
          name: 'Leather Bag',
          price: 250_000,
          tag: 'Aksesoris',
        },
      ],
      stats: { tasks: 0, completed: 0, pending: 0 },
      notes: [],
    }
  }

  if (template === 'proyek') {
    return {
      id,
      template,
      title: 'Project Dashboard',
      statusLabel: 'Membangun Aplikasi Proyek...',
      products: [],
      stats: { tasks: 12, completed: 8, pending: 4 },
      notes: ['Rencana sprint minggu ini', 'Review laporan midterm'],
    }
  }

  return {
    id,
    template: 'blank',
    title: 'Aplikasi Baru',
    statusLabel: 'Menyusun kerangka aplikasi...',
    products: [],
    stats: { tasks: 3, completed: 0, pending: 3 },
    notes: ['Jelaskan fitur yang kamu butuhkan di chat AI.'],
  }
}

export function assistantReply(prompt: string, app: GeneratedApp): string {
  if (app.template === 'toko') {
    return `Siap! Saya menyusun toko online berdasarkan: “${prompt.trim()}”. Preview “${app.title}” sudah siap — tambah produk atau jalankan build.`
  }
  if (app.template === 'proyek') {
    return `Berhasil! Dashboard manajemen proyek untuk kuliah sudah dibuat. Kamu bisa menambah modul, melihat progress, atau Hot Restart.`
  }
  return `Saya membuat kerangka aplikasi dasar. Coba sebutkan “toko online” atau “manajemen proyek” agar saya bisa menyesuaikan template.`
}
