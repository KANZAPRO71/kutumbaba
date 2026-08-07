import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AiAssistant } from './components/AiAssistant'
import { BuildStatus } from './components/BuildStatus'
import {
  IconChart,
  IconCloud,
  IconHome,
  IconRecent,
  IconSettings,
  IconShop,
  IconWallet,
} from './components/Icons'
import { ProyekPreview } from './components/ProyekPreview'
import { TokoPreview } from './components/TokoPreview'
import {
  assistantReply,
  createAppFromPrompt,
  type ChatMessage,
  type GeneratedApp,
  type Product,
} from './lib/studio'

type NavKey = 'home' | 'shop' | 'recent'

const WELCOME: ChatMessage = {
  id: 'welcome',
  role: 'system',
  text: 'Selamat datang di Studio. Ceritakan aplikasi yang ingin kamu buat — misalnya toko online UMKM atau dashboard proyek kuliah.',
}

function uid(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export default function App() {
  const [started, setStarted] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME])
  const [app, setApp] = useState<GeneratedApp | null>(null)
  const [building, setBuilding] = useState(false)
  const [progress, setProgress] = useState(0)
  const [cartCount, setCartCount] = useState(0)
  const [nav, setNav] = useState<NavKey>('home')
  const [toast, setToast] = useState<string | null>(null)
  const buildTimer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (buildTimer.current) window.clearInterval(buildTimer.current)
    }
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 2200)
    return () => window.clearTimeout(timer)
  }, [toast])

  function showToast(text: string) {
    setToast(text)
  }

  function runBuild(prompt: string, nextApp: GeneratedApp) {
    setBuilding(true)
    setProgress(8)
    setApp(nextApp)

    if (buildTimer.current) window.clearInterval(buildTimer.current)
    buildTimer.current = window.setInterval(() => {
      setProgress((value) => {
        if (value >= 100) {
          if (buildTimer.current) window.clearInterval(buildTimer.current)
          return 100
        }
        return Math.min(100, value + 14 + Math.floor(Math.random() * 10))
      })
    }, 180)

    window.setTimeout(() => {
      if (buildTimer.current) window.clearInterval(buildTimer.current)
      setProgress(100)
      setBuilding(false)
      setMessages((prev) => [
        ...prev,
        {
          id: uid('assistant'),
          role: 'assistant',
          text: assistantReply(prompt, nextApp),
        },
      ])
      showToast('Build selesai')
    }, 1400)
  }

  function handleSend(text: string) {
    const trimmed = text.trim()
    if (!trimmed || building) return

    setMessages((prev) => [...prev, { id: uid('user'), role: 'user', text: trimmed }])
    const nextApp = createAppFromPrompt(trimmed)
    runBuild(trimmed, nextApp)
  }

  function handleApplyTemplate(kind: 'toko' | 'proyek') {
    const prompt =
      kind === 'toko'
        ? 'Buat toko online sederhana dengan daftar produk'
        : 'Bangun aplikasi manajemen proyek untuk kuliah'
    handleSend(prompt)
  }

  function handleAddProduct() {
    if (!app || app.template !== 'toko') {
      showToast('Buat toko online dulu')
      return
    }
    const product: Product = {
      id: uid('product'),
      name: `Produk Baru ${app.products.length + 1}`,
      price: 99_000 + app.products.length * 25_000,
      tag: 'Baru',
    }
    setApp({ ...app, products: [...app.products, product] })
    setMessages((prev) => [
      ...prev,
      {
        id: uid('assistant'),
        role: 'assistant',
        text: `Produk “${product.name}” ditambahkan ke ${app.title}.`,
      },
    ])
    showToast('Produk ditambahkan')
  }

  function handleAddModule() {
    if (!app || app.template !== 'proyek') {
      showToast('Buat aplikasi proyek dulu')
      return
    }
    const note = `Modul baru ${app.notes.length + 1}`
    setApp({
      ...app,
      notes: [...app.notes, note],
      stats: {
        ...app.stats,
        tasks: app.stats.tasks + 1,
        pending: app.stats.pending + 1,
      },
    })
    setMessages((prev) => [
      ...prev,
      {
        id: uid('assistant'),
        role: 'assistant',
        text: `Modul “${note}” ditambahkan ke dashboard.`,
      },
    ])
    showToast('Modul ditambahkan')
  }

  function handleRunBuild() {
    if (!app) return
    runBuild('Jalankan ulang build aplikasi saat ini', { ...app, id: uid('app') })
  }

  function handleHotRestart() {
    if (!app) return
    setProgress(0)
    runBuild('Hot restart aplikasi proyek', {
      ...app,
      id: uid('app'),
      statusLabel: 'Hot restart aplikasi...',
    })
  }

  function handleAddToCart(product: Product) {
    setCartCount((count) => count + 1)
    showToast(`${product.name} masuk keranjang`)
  }

  function handleCompleteTask() {
    if (!app || app.stats.pending <= 0) return
    setApp({
      ...app,
      stats: {
        ...app.stats,
        completed: app.stats.completed + 1,
        pending: app.stats.pending - 1,
      },
    })
    showToast('1 tugas diselesaikan')
  }

  if (!started) {
    return (
      <div className="relative flex min-h-full items-center justify-center overflow-hidden px-5 py-10">
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse at 50% 0%, rgba(110,200,255,0.22), transparent 55%), radial-gradient(ellipse at 80% 80%, rgba(78,196,168,0.12), transparent 45%), linear-gradient(180deg, #07101f 0%, #0a1830 55%, #07101f 100%)',
          }}
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.15]"
          style={{
            backgroundImage:
              'linear-gradient(rgba(197,214,234,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(197,214,234,0.08) 1px, transparent 1px)',
            backgroundSize: '48px 48px',
            maskImage: 'radial-gradient(circle at center, black, transparent 75%)',
          }}
        />

        <main className="relative z-10 w-full max-w-md animate-rise-in text-center">
          <p className="mb-4 text-[11px] uppercase tracking-[0.28em] text-signal-2/90">
            Kutumbaba
          </p>
          <h1 className="font-display text-5xl font-bold tracking-tight text-white sm:text-6xl">
            Studio
          </h1>
          <p className="mx-auto mt-4 max-w-sm text-base leading-relaxed text-steel">
            Bangun aplikasi mobile dengan AI — dari toko online UMKM sampai dashboard proyek kuliah.
          </p>
          <button
            type="button"
            data-testid="start-studio"
            onClick={() => setStarted(true)}
            className="mt-8 inline-flex items-center justify-center rounded-2xl bg-gradient-to-r from-signal to-signal-2 px-7 py-3.5 text-sm font-semibold text-ink shadow-[0_12px_40px_rgba(110,200,255,0.25)] transition hover:brightness-110"
          >
            Mulai di Studio
          </button>
        </main>
      </div>
    )
  }

  return (
    <div className="relative mx-auto flex h-full min-h-full max-w-md flex-col bg-ink text-mist shadow-[0_0_80px_rgba(0,0,0,0.45)]">
      <header className="flex items-center justify-between px-4 pb-2 pt-4">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-signal-2 to-signal font-display text-sm font-bold text-ink">
            S
          </div>
          <div>
            <h1 className="font-display text-lg font-semibold leading-none text-white">Studio</h1>
            <p className="text-[11px] text-steel">AI App Builder</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <HeaderIcon label="Dompet">
            <IconWallet className="h-5 w-5" />
          </HeaderIcon>
          <HeaderIcon label="Pengaturan">
            <IconSettings className="h-5 w-5" />
          </HeaderIcon>
          <HeaderIcon label="Cloud">
            <IconCloud className="h-5 w-5" />
          </HeaderIcon>
        </div>
      </header>

      <div className="space-y-3 px-4 pb-3">
        <BuildStatus app={app} building={building} progress={progress} />

        <div className="min-h-[210px] rounded-2xl border border-white/10 bg-gradient-to-b from-ink-3 to-ink-2 p-4">
          {!app && !building && (
            <div className="flex h-full min-h-[180px] flex-col items-center justify-center text-center">
              <p className="font-display text-lg font-semibold text-white">Belum ada preview</p>
              <p className="mt-1 max-w-[240px] text-sm text-steel">
                Kirim prompt ke AI Assistant untuk menghasilkan toko online atau dashboard proyek.
              </p>
            </div>
          )}
          {app?.template === 'toko' && (
            <TokoPreview app={app} cartCount={cartCount} onAddToCart={handleAddToCart} />
          )}
          {app?.template === 'proyek' && (
            <ProyekPreview app={app} onCompleteTask={handleCompleteTask} />
          )}
          {app?.template === 'blank' && (
            <div className="animate-rise-in space-y-2">
              <h2 className="font-display text-xl font-semibold text-white">{app.title}</h2>
              <p className="text-sm text-steel">Kerangka kosong siap dikustomisasi.</p>
              <ul className="space-y-1.5 text-sm text-steel">
                {app.notes.map((note) => (
                  <li key={note}>• {note}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <AiAssistant
        messages={messages}
        building={building}
        app={app}
        onSend={handleSend}
        onApplyTemplate={handleApplyTemplate}
        onAddProduct={handleAddProduct}
        onAddModule={handleAddModule}
        onRunBuild={handleRunBuild}
        onHotRestart={handleHotRestart}
      />

      <nav className="flex items-center justify-around border-t border-white/10 bg-ink-2 px-2 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
        <NavButton
          active={nav === 'home'}
          label="Home"
          onClick={() => setNav('home')}
          icon={<IconHome className="h-5 w-5" />}
        />
        <NavButton
          active={nav === 'shop'}
          label={app?.template === 'proyek' ? 'Graph' : 'Shop'}
          onClick={() => setNav('shop')}
          icon={
            app?.template === 'proyek' ? (
              <IconChart className="h-5 w-5" />
            ) : (
              <IconShop className="h-5 w-5" />
            )
          }
        />
        <NavButton
          active={nav === 'recent'}
          label="Recent"
          onClick={() => setNav('recent')}
          icon={<IconRecent className="h-5 w-5" />}
        />
      </nav>

      {toast && (
        <div
          data-testid="toast"
          className="pointer-events-none absolute left-1/2 top-16 z-50 -translate-x-1/2 animate-rise-in rounded-full border border-signal/30 bg-ink-3/95 px-4 py-2 text-xs font-medium text-white shadow-lg"
        >
          {toast}
        </div>
      )}
    </div>
  )
}

function HeaderIcon({ children, label }: { children: ReactNode; label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      className="grid h-9 w-9 place-items-center rounded-xl text-steel transition hover:bg-white/5 hover:text-white"
    >
      {children}
    </button>
  )
}

function NavButton({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean
  label: string
  icon: ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex min-w-[4.5rem] flex-col items-center gap-0.5 rounded-xl px-3 py-1.5 text-[11px] transition ${
        active ? 'text-signal-2' : 'text-steel hover:text-mist'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
