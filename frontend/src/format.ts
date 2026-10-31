const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const inr1 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1, minimumFractionDigits: 1 })

export const cr = (v: number | null | undefined) => (v == null ? '—' : `₹${Math.abs(v) >= 100 ? inr.format(v) : inr1.format(v)} cr`)
export const num = (v: number | null | undefined, d = 1) => (v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }))
export const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`)
export const plainPct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v.toFixed(d)}%`)
export const sign = (v: number | null | undefined) => (v == null ? 'neutral' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'neutral')

export function metricValue(value: number | null, unit: string) {
  if (value == null) return '—'
  if (unit === '₹ cr') return cr(value)
  if (unit === '%') return plainPct(value)
  if (unit === 'pp') return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)} pp`
  if (unit === 'x') return `${value.toFixed(2)}×`
  if (unit === 'days') return `${Math.round(value)} days`
  return String(value)
}

export function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  const d = Math.round(s / 86400)
  return d === 1 ? 'yesterday' : `${d}d ago`
}

export const stamp = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }) + ' IST'

export const CATEGORY_LABEL: Record<string, string> = {
  results: 'Results', 'M&A': 'M&A', fund_raise: 'Fund raise', management_change: 'Management change', litigation: 'Litigation / regulatory',
  insider_trading: 'Insider trade', earnings_call: 'Earnings call', investor_meetings: 'Investor meeting', credit_rating: 'Credit rating',
  dividend: 'Dividend', bonus_split: 'Bonus / split', capex: 'Capex', press_release: 'Press release', postal_ballot: 'Postal ballot',
  agm_egm: 'AGM / EGM', pledging: 'Pledging', unclassified: 'Routine filing',
}
export const catLabel = (c: string) => CATEGORY_LABEL[c] ?? c

const inr0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const inr2 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
/** ₹1,45,796 (Indian grouping). */
export const rupees = (v: number | null | undefined, decimals = false) => (v == null ? '—' : `${v < 0 ? '−' : ''}₹${(decimals ? inr2 : inr0).format(Math.abs(v))}`)
export const signedRupees = (v: number | null | undefined) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}₹${inr0.format(Math.abs(v))}`)
/** ₹1.46 L / ₹2.31 Cr for headline figures. */
export function compactRupees(v: number | null | undefined) {
  if (v == null) return '—'
  const a = Math.abs(v), s = v < 0 ? '−' : ''
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)} L`
  return `${s}₹${inr0.format(a)}`
}
export const level = (v: number | null | undefined) => (v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 }))
export const shortDate = (iso: string | null | undefined) => (iso ? new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—')
