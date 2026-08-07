import { useEffect, useRef, useState } from 'react'
import { IconMic, IconSend } from './Icons'
import type { ChatMessage, GeneratedApp } from '../lib/studio'

type Props = {
  messages: ChatMessage[]
  building: boolean
  app: GeneratedApp | null
  onSend: (text: string) => void
  onApplyTemplate: (kind: 'toko' | 'proyek') => void
  onAddProduct: () => void
  onAddModule: () => void
  onRunBuild: () => void
  onHotRestart: () => void
}

const SUGGESTIONS = [
  'Buat toko online sederhana dengan daftar produk',
  'Bangun aplikasi manajemen proyek untuk kuliah',
]

export function AiAssistant({
  messages,
  building,
  app,
  onSend,
  onApplyTemplate,
  onAddProduct,
  onAddModule,
  onRunBuild,
  onHotRestart,
}: Props) {
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, building])

  function submit() {
    const text = draft.trim()
    if (!text || building) return
    onSend(text)
    setDraft('')
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-t-3xl border border-white/10 border-b-0 bg-ink-2/95 shadow-[0_-12px_40px_rgba(0,0,0,0.35)]">
      <div className="flex items-center justify-between border-b border-white/8 px-4 py-3">
        <div>
          <h2 className="font-display text-sm font-semibold text-white">AI Assistant</h2>
          <p className="text-[11px] text-steel">Prompt → aplikasi yang bisa dijalankan</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-signal/30 bg-signal/10 px-2.5 py-1 text-[11px] font-medium text-signal">
          <span className="h-1.5 w-1.5 animate-pulse-glow rounded-full bg-signal" />
          Online
        </span>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-4 py-3">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`max-w-[92%] animate-rise-in rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
              message.role === 'user'
                ? 'ml-auto bg-signal-2/20 text-white'
                : message.role === 'system'
                  ? 'border border-white/10 bg-white/[0.03] text-steel'
                  : 'bg-ink-3 text-mist'
            }`}
          >
            {message.text}
          </div>
        ))}
        {building && (
          <div className="animate-rise-in rounded-2xl bg-ink-3 px-3.5 py-2.5 text-sm text-steel">
            Studio sedang membangun aplikasi...
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="space-y-2 border-t border-white/8 px-3 py-3">
        {!app && (
          <div className="flex gap-2 overflow-x-auto pb-1">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                disabled={building}
                onClick={() => onSend(suggestion)}
                className="shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-left text-[11px] text-mist transition hover:border-signal-2/40 disabled:opacity-50"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <ActionChip
            label="Apply Template"
            onClick={() => onApplyTemplate(app?.template === 'proyek' ? 'proyek' : 'toko')}
            disabled={building}
          />
          {app?.template === 'proyek' ? (
            <ActionChip label="Add Modul" onClick={onAddModule} disabled={building || !app} />
          ) : (
            <ActionChip label="Add Produk" onClick={onAddProduct} disabled={building || !app} />
          )}
          {app?.template === 'proyek' ? (
            <ActionChip label="Hot Restart" onClick={onHotRestart} disabled={building || !app} />
          ) : (
            <ActionChip label="Run Build" onClick={onRunBuild} disabled={building || !app} />
          )}
        </div>

        <form
          className="flex items-center gap-2 rounded-2xl border border-white/10 bg-ink px-2 py-1.5"
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          <button
            type="button"
            className="grid h-10 w-10 place-items-center rounded-xl text-steel transition hover:bg-white/5 hover:text-white"
            aria-label="Input suara"
            title="Input suara (demo)"
          >
            <IconMic className="h-5 w-5" />
          </button>
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ketik pesan..."
            disabled={building}
            className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-steel/70 disabled:opacity-60"
            aria-label="Pesan untuk AI Assistant"
          />
          <button
            type="submit"
            disabled={building || !draft.trim()}
            className="grid h-10 w-10 place-items-center rounded-xl bg-signal-2 text-ink transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Kirim pesan"
          >
            <IconSend className="h-5 w-5" />
          </button>
        </form>
      </div>
    </section>
  )
}

function ActionChip({
  label,
  onClick,
  disabled,
}: {
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full border border-white/12 bg-white/[0.05] px-3 py-1.5 text-[11px] font-medium text-mist transition hover:border-signal/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
    >
      {label}
    </button>
  )
}
