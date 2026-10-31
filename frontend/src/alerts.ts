import type { Alerts, FeedItem } from './api'
import { catLabel } from './format'

export type AlertKind = 'market' | 'results' | 'events' | 'filings'
export interface AlertItem {
  id: string; kind: AlertKind; title: string; detail: string; why: string; time: string | null
  symbol: string; filing?: FeedItem; severity: 'high' | 'medium'
}

const EVENTS = new Set(['dividend', 'bonus_split', 'agm_egm', 'postal_ballot', 'credit_rating', 'earnings_call', 'investor_meetings'])
export const KIND_LABEL: Record<AlertKind, string> = { market: 'Price & volume', results: 'Results', events: 'Corporate events', filings: 'Material filings' }

/** Alerts are things that matched a rule; Today is everything ranked. Same filing, different question. */
export function alertItems(a: Alerts): AlertItem[] {
  const out: AlertItem[] = []
  for (const m of a.market_alerts) {
    out.push({
      id: `mkt:${m.symbol}:${m.as_of}:${m.type}`, kind: 'market', symbol: m.symbol, time: m.as_of ? `${m.as_of}T15:30:00+05:30` : null,
      title: `${m.company} ${m.type === 'price_move' ? (m.value >= 0 ? 'jumped' : 'fell') + ` ${Math.abs(m.value).toFixed(1)}%` : `traded ${m.value.toFixed(1)}× normal volume`}`,
      detail: m.text, why: m.type === 'price_move' ? `Your rule: daily move beyond ±${m.threshold}%` : `Your rule: volume ≥ ${m.threshold}× average`,
      severity: m.type === 'price_move' && Math.abs(m.value) >= 2 * m.threshold ? 'high' : 'medium',
    })
  }
  for (const f of a.filing_alerts) {
    const kind: AlertKind = f.category === 'results' ? 'results' : EVENTS.has(f.category) ? 'events' : 'filings'
    out.push({
      id: f.uid, kind, symbol: f.symbol, time: f.published, filing: f, title: `${f.company}: ${catLabel(f.category).toLowerCase()}`,
      detail: f.summary, why: `Matches your ${catLabel(f.category)} rule, ranked ${f.tier === 'high' ? 'needs you' : 'worth a glance'} (${f.priority}/100)`,
      severity: f.tier === 'high' ? 'high' : 'medium',
    })
  }
  return out.sort((x, y) => (x.severity === y.severity ? (y.time || '').localeCompare(x.time || '') : x.severity === 'high' ? -1 : 1))
}
