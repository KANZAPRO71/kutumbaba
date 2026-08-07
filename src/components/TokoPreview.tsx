import { formatRupiah, type GeneratedApp, type Product } from '../lib/studio'

type Props = {
  app: GeneratedApp
  cartCount: number
  onAddToCart: (product: Product) => void
}

export function TokoPreview({ app, cartCount, onAddToCart }: Props) {
  return (
    <div className="animate-rise-in space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-steel/80">Preview</p>
          <h2 className="font-display text-xl font-semibold text-white">{app.title}</h2>
        </div>
        <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-mist">
          Keranjang · {cartCount}
        </div>
      </div>

      <ul className="space-y-2.5">
        {app.products.map((product, index) => (
          <li
            key={product.id}
            className="flex items-center gap-3 rounded-2xl border border-white/8 bg-gradient-to-r from-white/[0.07] to-white/[0.02] p-3"
            style={{ animationDelay: `${index * 80}ms` }}
          >
            <div
              className="grid h-14 w-14 shrink-0 place-items-center rounded-xl text-lg font-semibold text-ink"
              style={{
                background:
                  index % 2 === 0
                    ? 'linear-gradient(145deg, #7fd0ff, #3a8fd4)'
                    : 'linear-gradient(145deg, #7ddeb8, #2f9e7a)',
              }}
            >
              {product.name.slice(0, 1)}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-white">{product.name}</p>
              <p className="text-xs text-steel">{product.tag}</p>
              <p className="mt-0.5 text-sm font-semibold text-signal-2">
                {formatRupiah(product.price)}
              </p>
            </div>
            <button
              type="button"
              data-testid="add-to-cart"
              onClick={() => onAddToCart(product)}
              className="shrink-0 rounded-xl bg-signal-2/90 px-3 py-2 text-xs font-semibold text-ink transition hover:bg-signal-2"
            >
              Add to Cart
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
