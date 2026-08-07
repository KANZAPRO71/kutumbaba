import type { GeneratedApp } from '../lib/studio'

type Props = {
  app: GeneratedApp
  onCompleteTask: () => void
}

export function ProyekPreview({ app, onCompleteTask }: Props) {
  const total = Math.max(app.stats.tasks, 1)
  const pct = Math.round((app.stats.completed / total) * 100)

  return (
    <div className="animate-rise-in space-y-3">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-steel/80">Preview</p>
        <h2 className="font-display text-xl font-semibold text-white">{app.title}</h2>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          { label: 'Tasks', value: app.stats.tasks },
          { label: 'Completed', value: app.stats.completed },
          { label: 'Pending', value: app.stats.pending },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-2xl border border-white/8 bg-white/[0.04] px-3 py-3 text-center"
          >
            <p className="font-display text-xl font-semibold text-white">{stat.value}</p>
            <p className="text-[11px] text-steel">{stat.label}</p>
          </div>
        ))}
      </div>

      <div className="rounded-2xl border border-white/8 bg-gradient-to-b from-white/[0.07] to-transparent p-3">
        <div className="mb-2 flex items-center justify-between text-xs text-steel">
          <span>Progress</span>
          <span className="text-signal">{pct}%</span>
        </div>
        <svg viewBox="0 0 240 72" className="h-16 w-full" aria-hidden="true">
          <defs>
            <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#4ec4a8" />
              <stop offset="100%" stopColor="#6ec8ff" />
            </linearGradient>
          </defs>
          <path
            d="M8 58 C 40 54, 52 40, 78 36 S 120 48, 148 28 S 190 18, 232 12"
            fill="none"
            stroke="url(#lineGrad)"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx="232" cy="12" r="4" fill="#6ec8ff" />
        </svg>
      </div>

      <div className="flex flex-wrap gap-2">
        {['To Do List', 'Project Notes', 'Team Chart'].map((label) => (
          <button
            key={label}
            type="button"
            data-testid={label === 'To Do List' ? 'complete-task' : undefined}
            onClick={label === 'To Do List' ? onCompleteTask : undefined}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-mist transition hover:border-signal-2/40 hover:text-white"
          >
            {label}
          </button>
        ))}
      </div>

      {app.notes.length > 0 && (
        <ul className="space-y-1.5 text-sm text-steel">
          {app.notes.map((note) => (
            <li key={note} className="flex gap-2">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-signal" />
              <span>{note}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
