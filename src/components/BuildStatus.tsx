import { IconGear } from './Icons'
import type { GeneratedApp } from '../lib/studio'

type Props = {
  app: GeneratedApp | null
  building: boolean
  progress: number
}

export function BuildStatus({ app, building, progress }: Props) {
  const label = building
    ? (app?.statusLabel ?? 'Memproses permintaan...')
    : app
      ? 'Aplikasi siap di-preview'
      : 'Siap membangun aplikasi'

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-ink-3/80 px-4 py-3">
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            'radial-gradient(circle at 15% 20%, rgba(110,200,255,0.25), transparent 45%), radial-gradient(circle at 85% 10%, rgba(78,196,168,0.18), transparent 40%)',
        }}
      />
      <div className="relative flex items-center gap-3">
        <div className="relative flex h-12 w-16 items-center justify-center">
          <IconGear
            className={`absolute left-0 top-1 h-6 w-6 text-signal-2/80 ${building ? 'animate-spin-slow' : ''}`}
          />
          <IconGear
            className={`absolute right-1 top-0 h-5 w-5 text-signal/70 ${building ? 'animate-spin-slow [animation-direction:reverse]' : ''}`}
          />
          <IconGear
            className={`absolute bottom-0 left-5 h-5 w-5 text-mist/50 ${building ? 'animate-spin-slow' : ''}`}
          />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-display text-sm font-semibold text-white">{label}</p>
          <p className="text-xs text-steel">
            {building ? 'Sedang diproses...' : app ? 'Build selesai' : 'Tulis prompt di AI Assistant'}
          </p>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full rounded-full bg-gradient-to-r from-signal to-signal-2 transition-[width] duration-500 ${
                building && progress < 15 ? 'animate-progress w-1/3' : ''
              }`}
              style={{
                width: building || app ? `${Math.max(progress, building ? 12 : 100)}%` : '0%',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
