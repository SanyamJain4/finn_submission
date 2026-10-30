export type Tier = 'high' | 'medium' | 'low'

export interface FeedItem {
  uid: string; exchange: string; symbol: string; company: string; sector?: string
  subject: string; text: string; published: string; url: string | null; exchange_category: string
  category: string; category_confidence: number; category_rule: string
  priority: number; tier: Tier; why: string[]; summary: string; enrichment: string | null
}
export interface Signal { type: 'price_move' | 'volume_spike'; value: number; threshold: number; text: string }
export interface MarketRow {
  status: string; as_of?: string; close?: number; day_change_pct?: number | null; signals: Signal[]
  volume_multiple?: number; volume_status?: string; spark: number[]; provider_status?: string; stale_note?: string
}
export interface SourceStatus { name: string; status: string; detail: string }
export interface Feed {
  window: { start: string; end: string }; items: FeedItem[]
  counts: { tier: Record<Tier, number>; category: Record<string, number>; total: number }
  sources: SourceStatus[]; market: { provider: string | null; by_symbol: Record<string, MarketRow>; error?: string }
  fixture: boolean
}
export interface Comparison {
  label: string; current: number | null; prev_quarter: number | null; year_ago: number | null
  qoq_pct: number | null; yoy_pct: number | null; qoq_note: string | null; yoy_note: string | null
  margin_current?: number | null; margin_year_ago?: number | null; derived?: boolean; formula?: string
}
export interface ResultsX {
  status: string; basis: string | null; unit_source: string | null
  periods: { current?: string; prev_quarter?: string; year_ago?: string; confirmed?: boolean }
  metrics: Record<string, Comparison>; evidence: { metric: string; page: number; row: string }[]; notes: string[]
}
export interface PeopleX {
  status: string; names: string[]; directions: Record<string, string>; roles: string[]; effective: string | null; profile_passage: string | null
  profile_source: string | null; notes: string[]
  structured: { name: string; role?: string; direction: string; background?: string; prior_roles: string[]; education: string[] }[] | null
  secondary: { source: string; url: string; summary: string; caveat: string } | null
}
export interface FilingDetail {
  item: FeedItem; document: { status: string; detail: string; pages: number } | null
  results: ResultsX | null; people: PeopleX | null; key_lines: { page: number; text: string }[]
  llm_summary: { summary: string; key_facts: string[]; grounded: boolean; unsupported_numbers: string[] } | null
  notes: string[]
}
export interface AlertPrefs {
  categories: string[]; min_tier: Tier; price_move_pct: number; volume_multiple: number; volume_window: number
}
export interface Alerts {
  prefs: AlertPrefs; filing_alerts: FeedItem[]; checked_at: string; note: string; market_provider: string | null
  market_alerts: (Signal & { symbol: string; company: string; as_of?: string })[]
}
export interface Claim { text: string; evidence: string[]; kind: string; verified?: boolean; issues?: string[]; origin?: string }
export interface Metric { id: string; label: string; value: number | null; unit: string; period: string | null; source: string; note?: string | null }
export interface GuidanceRow {
  quote: string; speaker?: string | null; metric: string; scope: string; comparator: string
  target_low: number | null; target_high: number | null; period: string | null
  actual: number | null; actual_period: string | null; verdict: string; reason: string; call_date?: string; source: string; page: number
}
export interface Source { id: string; kind: string; title: string; url: string; date?: string | null; status: string; detail?: string; pages?: number; publisher?: string }
export interface Evidence { id: string; source: string; page: number; text: string }
export interface Report {
  symbol: string; name: string; basis: string; in_portfolio: boolean; generated_at: string; elapsed_s: number
  sources: Source[]; evidence: Record<string, Evidence>; metrics: Record<string, Metric>; is_bank: boolean
  tables: {
    trajectory: { period: string; revenue: number | null; op_profit: number | null; pat: number | null; opm: number | null; revenue_growth: number | null; pat_growth: number | null }[]
    quarters: { period: string; revenue: number | null; pat: number | null; opm: number | null; revenue_yoy: number | null; pat_yoy: number | null }[]
    balance_sheet: { period: string; equity: number | null; borrowings: number | null; de: number | null }[]
    working_capital: { metric: string; values: { period: string; value: number | null }[] }[]
    cash: { period: string; cfo: number | null; pat: number | null; conversion: number | null; capex: number | null; fcf: number | null }[]
  }
  sections: {
    headline: string | null
    business: { status: string; what_it_does?: Claim; segments?: { name: string; share_of_revenue_pct: number | null; evidence: string[] }[]; other_points?: Claim[]; not_found?: string[]; passages?: string[]; detail?: string }
    trajectory: { claims: Claim[] }; balance_sheet: { claims: Claim[] }; cash_quality: { claims: Claim[] }
    narrative?: { claims: Claim[] }
    guidance: { status: string; rows: GuidanceRow[]; tally: Record<string, number>; candidates: { evidence: string; call_date: string; text: string }[]; method: string }
    bull_bear: { bull: Claim[]; bear: Claim[]; origin: string }
    open_questions?: string[]
  }
  verification: { llm_claims: number; verified: number; unverified: number; method: string }
  limitations: string[]; llm: { enabled: boolean; provider: string | null; calls_used: number; calls_budget: number }
  fixture: boolean
}
export interface Job { job_id: string | null; symbol: string; name?: string; status: 'running' | 'done' | 'error'; stage: string; stages_done: string[]; stages: string[]; error: string | null; report: Report | null; cached?: boolean }

export class ApiError extends Error {
  status: number
  constructor(status: number, msg: string) { super(msg); this.status = status }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } })
  } catch {
    throw new ApiError(0, 'FINN’s server is unreachable. Check your connection and try again.')
  }
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const d = body?.detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join('; ') : body?.source ? `${body.source} is not responding` : `Request failed (${r.status})`
    throw new ApiError(r.status, msg)
  }
  return body as T
}

export const api = {
  status: () => req<{ fixture_mode: boolean; llm: { enabled: boolean; provider: string | null; fast_model: string | null; smart_model: string | null }; llm_usage: { by_model: { model: string; calls: number; cache_hits: number; input_tokens: number; output_tokens: number; errors: number }[] }; categories: string[]; portfolio_size: number }>('/api/status'),
  portfolio: () => req<{ portfolio: { symbol: string; name: string; sector: string; size: string }[]; research_demos: { symbol: string; name: string; why: string }[] }>('/api/portfolio'),
  feed: (q: { hours?: number; start?: string; end?: string }) => {
    const p = new URLSearchParams()
    if (q.start) { p.set('start', q.start); if (q.end) p.set('end', q.end) } else p.set('hours', String(q.hours ?? 24))
    return req<Feed>(`/api/feed?${p}`)
  },
  filing: (uid: string) => req<FilingDetail>(`/api/announcements/${encodeURIComponent(uid)}`),
  alerts: () => req<Alerts>('/api/alerts'),
  prefs: () => req<AlertPrefs>('/api/prefs/alerts'),
  savePrefs: (p: AlertPrefs) => req<AlertPrefs>('/api/prefs/alerts', { method: 'PUT', body: JSON.stringify(p) }),
  search: (q: string) => req<{ results: { symbol: string; name: string; in_portfolio: boolean }[]; remote_error: string | null }>(`/api/search?q=${encodeURIComponent(q)}`),
  research: (query: string, force = false) => req<Job>('/api/research', { method: 'POST', body: JSON.stringify({ query, force }) }),
  job: (id: string) => req<Job>(`/api/research/jobs/${id}`),
}
