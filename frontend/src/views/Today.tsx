import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type Briefing, type Feed, type FeedItem, type IndexQuote, type Tier, type Valuation } from '../api'
import { ago, catLabel, compactRupees, level, pct, shortDate, sign, signedRupees } from '../format'
import { KEYS, useStored } from '../store'
import type { HoldingInput } from '../api'
import { ErrorNote, Rail, Skeleton, SnapshotNote, Spark, jump } from '../ui'

const WINDOWS = [
  { key: '24', label: '24 hours', hours: 24 },
  { key: '72', label: '3 days', hours: 72 },
  { key: '168', label: '7 days', hours: 168 },
]
const TIER_NAME: Record<Tier, string> = { high: 'Needs you', medium: 'Worth a glance', low: 'Routine' }

export default function Today({ openFiling, openCompany }: { openFiling: (i: FeedItem) => void; openCompany: (sym: string) => void }) {
  const [holdings] = useStored<HoldingInput[]>(KEYS.holdings, [])
  const [idx, setIdx] = useState<{ indices: IndexQuote[]; provider: string | null } | null>(null)
  const [val, setVal] = useState<Valuation | null>(null)
  const [brief, setBrief] = useState<Briefing | null>(null)
  const [briefErr, setBriefErr] = useState<string | null>(null)

  useEffect(() => { api.indices().then(setIdx).catch(() => setIdx({ indices: [], provider: null })) }, [])
  useEffect(() => {
    if ((holdings || []).length) api.valueHoldings(holdings).then(setVal).catch(() => setVal(null))
    else setVal(null)
    setBrief(null); setBriefErr(null)
    api.briefing((holdings || []).map(h => h.symbol)).then(setBrief).catch(e => setBriefErr(e.message))
  }, [holdings])

  return (
    <section className="view today" aria-labelledby="today-h">
      <h1 id="today-h" className="sr-only">Today</h1>
      <Indices data={idx} />
      <div className="today-grid">
        <div className="today-main">
          <BriefingCard b={brief} err={briefErr} openFiling={openFiling} />
          <Filings openFiling={openFiling} openCompany={openCompany} />
        </div>
        <aside className="today-side">
          <PortfolioSnap v={val} has={(holdings || []).length > 0} />
        </aside>
      </div>
    </section>
  )
}

function Indices({ data }: { data: { indices: IndexQuote[]; provider: string | null } | null }) {
  if (!data) return <div className="indices">{[0, 1, 2, 3].map(i => <div key={i} className="index-card"><Skeleton lines={3} /></div>)}</div>
  const shown = data.indices.filter(i => i.value != null)
  if (!shown.length) return <p className="muted small index-empty">Index data isn’t reachable from this server right now.</p>
  const asOf = shown[0]
  return (
    <div className="indices-wrap">
      <ul className="indices" aria-label="Indian market indices">
        {shown.map(i => (
          <li key={i.key} className="index-card">
            <span className="index-name">{i.name}</span>
            <span className="index-level">{level(i.value)}</span>
            <span className={`index-chg ${sign(i.change_pct)}`}>{i.change != null && `${i.change > 0 ? '+' : i.change < 0 ? '−' : ''}${level(Math.abs(i.change))}`} ({pct(i.change_pct, 2)})</span>
            <Spark data={i.spark} up={(i.change_pct ?? 0) >= 0} />
          </li>
        ))}
      </ul>
      <p className="muted small data-stamp">
        {asOf.kind === 'delayed' ? 'Intraday, delayed' : `End-of-day close, ${shortDate(asOf.as_of)}`}. Source: {data.provider === 'yfinance' || data.provider?.startsWith('yfinance') ? 'Yahoo Finance' : data.provider}.
      </p>
    </div>
  )
}

function PortfolioSnap({ v, has }: { v: Valuation | null; has: boolean }) {
  if (!has) {
    return (
      <div className="card snap-card empty">
        <h2 className="h3">Your portfolio</h2>
        <p className="muted small">Add what you own to see today’s P&L here and get a briefing that puts your holdings first.</p>
        <a className="btn-ghost" href="#/portfolio">Add holdings</a>
      </div>
    )
  }
  if (!v) return <div className="card snap-card"><Skeleton lines={4} /></div>
  const t = v.totals
  return (
    <a className="card snap-card" href="#/portfolio">
      <h2 className="h3">Your portfolio <span className="muted small">{t.count} holdings</span></h2>
      <p className="snap-value">{compactRupees(t.value)}</p>
      <p className={`snap-line ${sign(t.day_change)}`}>Today {signedRupees(t.day_change)} ({pct(t.day_change_pct, 2)})</p>
      <p className={`snap-line ${sign(t.pnl)}`}>Unrealised {signedRupees(t.pnl)} ({pct(t.pnl_pct, 1)})</p>
      {t.unpriced.length > 0 && <p className="warn small">No price for {t.unpriced.join(', ')}</p>}
      <p className="muted small">Prices at close {shortDate(t.as_of)}</p>
    </a>
  )
}

function BriefingCard({ b, err, openFiling }: { b: Briefing | null; err: string | null; openFiling: (i: FeedItem) => void }) {
  const [feedIndex, setFeedIndex] = useState<Record<string, FeedItem>>({})
  useEffect(() => { api.feed({ hours: 168 }).then(f => setFeedIndex(Object.fromEntries(f.items.map(i => [`F:${i.uid}`, i])))).catch(() => {}) }, [])
  if (err) return <div className="card brief-card"><p className="muted small">Briefing unavailable: {err}</p></div>
  if (!b) return <div className="card brief-card"><Skeleton lines={4} /></div>
  const factText = (id: string) => b.facts.find(f => f.id === id)?.text
  return (
    <div className="card brief-card" aria-labelledby="brief-h">
      <p className="brief-kicker muted small">{b.origin === 'llm' ? 'AI briefing, every line checked against its source' : 'Briefing from today’s ranked data'} · {new Date(b.generated_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</p>
      <h2 id="brief-h" className="brief-head">{b.headline}</h2>
      {b.lines.length === 0 ? <p className="muted">Nothing notable yet in this window.</p> : (
        <ul className="brief-lines">
          {b.lines.map((l, i) => (
            <li key={i}>
              {l.text}{' '}
              {l.cites.map(c => feedIndex[c]
                ? <button key={c} className="cite" onClick={() => openFiling(feedIndex[c])}>filing</button>
                : <span key={c} className="cite static" title={factText(c)}>{c.startsWith('I:') ? 'index' : c.startsWith('M:') ? 'price' : 'source'}</span>)}
            </li>
          ))}
        </ul>
      )}
      <SnapshotNote s={b.snapshot} />
    </div>
  )
}

function Filings({ openFiling, openCompany }: { openFiling: (i: FeedItem) => void; openCompany: (sym: string) => void }) {
  const [win, setWin] = useState('24')
  const [range, setRange] = useState<{ start: string; end: string }>({ start: '', end: '' })
  const [feed, setFeed] = useState<Feed | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [company, setCompany] = useState('')
  const [category, setCategory] = useState('')
  const [showRoutine, setShowRoutine] = useState(false)

  const load = useCallback(() => {
    setLoading(true); setErr(null)
    const q = win === 'custom' ? (range.start ? { start: range.start, end: range.end || undefined } : null) : { hours: Number(win) }
    if (!q) { setLoading(false); return }
    api.feed(q).then(setFeed).catch(e => setErr(e.message)).finally(() => setLoading(false))
  }, [win, range])
  useEffect(load, [load])

  const items = useMemo(() => (feed?.items || []).filter(i => (!company || i.symbol === company) && (!category || i.category === category)), [feed, company, category])
  const byTier = (t: Tier) => items.filter(i => i.tier === t)
  const counts = { high: byTier('high').length, medium: byTier('medium').length, low: byTier('low').length }
  const moves = feed ? Object.entries(feed.market.by_symbol).filter(([, m]) => m.signals.length) : []
  const failed = feed?.sources.filter(s => s.status === 'error' || s.status === 'partial') || []
  const onSnapshot = !!feed?.snapshot
  const filtered = company || category

  return (
    <div className="filings" aria-labelledby="filings-h">
      <div className="section-head">
        <h2 id="filings-h" className="h2">Watchlist filings</h2>
        <div className="window-row" role="group" aria-label="Time window">
          {WINDOWS.map(w => <button key={w.key} className={`chip${win === w.key ? ' on' : ''}`} aria-pressed={win === w.key} onClick={() => setWin(w.key)}>{w.label}</button>)}
          <button className={`chip${win === 'custom' ? ' on' : ''}`} aria-pressed={win === 'custom'} onClick={() => setWin('custom')}>Dates</button>
        </div>
      </div>
      {win === 'custom' && (
        <div className="date-row">
          <label>From <input type="date" value={range.start} max={range.end || undefined} onChange={e => setRange(r => ({ ...r, start: e.target.value }))} /></label>
          <label>To <input type="date" value={range.end} min={range.start || undefined} onChange={e => setRange(r => ({ ...r, end: e.target.value }))} /></label>
        </div>
      )}
      {loading && !feed && <div className="pad"><Skeleton lines={6} /></div>}
      {err && <ErrorNote msg={err} retry={load} />}
      {win === 'custom' && !range.start && <p className="muted pad">Pick a start date to load filings for that period.</p>}

      {feed && (
        <>
          <p className={`brief${loading ? ' dim' : ''}`} aria-live="polite">
            {feed.counts.total === 0 && !onSnapshot && failed.length === feed.sources.length && failed.length > 0 ? (
              <>Couldn’t reach the exchanges, so FINN can’t tell what changed.</>
            ) : feed.counts.total === 0 ? (
              <>Quiet window. Nothing filed by your watchlist companies.</>
            ) : (
              <>
                <button className="n-high" onClick={() => jump('tier-high')}>{counts.high} {counts.high === 1 ? 'filing needs' : 'filings need'} you.</button>{' '}
                <button className="n-med" onClick={() => jump('tier-medium')}>{counts.medium} worth a glance.</button>{' '}
                <button className="n-low" onClick={() => { setShowRoutine(true); setTimeout(() => jump('tier-low'), 50) }}>{counts.low} routine, folded away.</button>
              </>
            )}
          </p>
          <SnapshotNote s={feed.snapshot} />
          {failed.length > 0 && !onSnapshot && <p className="source-warn" role="status">{failed.map(s => `${s.name}: ${s.detail}`).join('. ')}. Some filings may be missing.</p>}

          <div className="filters">
            <label className="sel"><span className="sr-only">Company</span>
              <select value={company} onChange={e => setCompany(e.target.value)}>
                <option value="">All companies</option>
                {[...new Set(feed.items.map(i => i.symbol))].sort().map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="sel"><span className="sr-only">Category</span>
              <select value={category} onChange={e => setCategory(e.target.value)}>
                <option value="">All types</option>
                {Object.keys(feed.counts.category).sort().map(c => <option key={c} value={c}>{catLabel(c)} ({feed.counts.category[c]})</option>)}
              </select>
            </label>
            {filtered && <button className="btn-ghost" onClick={() => { setCompany(''); setCategory('') }}>Clear</button>}
          </div>

          {moves.length > 0 && !filtered && (
            <div className="block moves-block">
              <h3 className="h3">Moved at last close <span className="muted small">end-of-day</span></h3>
              <ul className="moves">
                {moves.map(([sym, m]) => (
                  <li key={sym}>
                    <button className="move" onClick={() => openCompany(sym)}>
                      <span className="move-sym">{sym}</span>
                      <Spark data={m.spark} up={(m.day_change_pct ?? 0) >= 0} />
                      <span className={`move-chg ${(m.day_change_pct ?? 0) >= 0 ? 'pos' : 'neg'}`}>{pct(m.day_change_pct)}</span>
                      <span className="move-why">{m.signals.map(s => s.type === 'volume_spike' ? `${s.value.toFixed(1)}× volume` : 'price move').join(', ')}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(['high', 'medium'] as Tier[]).map(t => byTier(t).length > 0 && (
            <div className="block" key={t} id={`tier-${t}`}>
              <h3 className="h3">{TIER_NAME[t]}</h3>
              <ul className="feed">{byTier(t).map(i => <Row key={i.uid} i={i} onOpen={openFiling} />)}</ul>
            </div>
          ))}
          {byTier('low').length > 0 && (
            <div className="block" id="tier-low">
              <button className="fold" aria-expanded={showRoutine} onClick={() => setShowRoutine(s => !s)}>{showRoutine ? 'Hide' : 'Show'} {byTier('low').length} routine filings</button>
              {showRoutine && <ul className="feed routine">{byTier('low').map(i => <Row key={i.uid} i={i} onOpen={openFiling} compact />)}</ul>}
            </div>
          )}
          {items.length === 0 && feed.counts.total > 0 && <p className="muted pad">No filings match these filters.</p>}
        </>
      )}
    </div>
  )
}

export function Row({ i, onOpen, compact }: { i: FeedItem; onOpen: (i: FeedItem) => void; compact?: boolean }) {
  return (
    <li>
      <button className={`row${compact ? ' compact' : ''}`} onClick={() => onOpen(i)}>
        <Rail score={i.priority} tier={i.tier} />
        <span className="row-body">
          <span className="row-top">
            <span className="row-co">{i.company}</span>
            <time className="muted small" dateTime={i.published}>{ago(i.published)}</time>
          </span>
          {!compact && <span className="row-sum">{i.summary}</span>}
          <span className="row-meta">
            <span className={`cat cat-${i.category.replace('&', '')}`}>{catLabel(i.category)}</span>
            {!compact && i.why[1] && <span className="muted small row-why">{i.why[1].replace(/^[+-]?\d+:\s*/, '')}</span>}
            {compact && <span className="muted small">{i.subject}</span>}
          </span>
        </span>
      </button>
    </li>
  )
}
