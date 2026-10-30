import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type Feed, type FeedItem, type Tier } from '../api'
import { ago, catLabel, pct } from '../format'
import { ErrorNote, Loading, Rail, Spark, jump } from '../ui'

const WINDOWS = [
  { key: '24', label: '24 hours', hours: 24 },
  { key: '72', label: '3 days', hours: 72 },
  { key: '168', label: '7 days', hours: 168 },
]
const TIER_NAME: Record<Tier, string> = { high: 'Needs you', medium: 'Worth a glance', low: 'Routine' }

export default function Today({ openFiling, openCompany }: { openFiling: (i: FeedItem) => void; openCompany: (sym: string) => void }) {
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
  const filtered = company || category

  return (
    <section className="view" aria-labelledby="today-h">
      <h1 id="today-h" className="sr-only">Today</h1>
      <div className="window-row" role="group" aria-label="Time window">
        {WINDOWS.map(w => (
          <button key={w.key} className={`chip${win === w.key ? ' on' : ''}`} aria-pressed={win === w.key} onClick={() => setWin(w.key)}>{w.label}</button>
        ))}
        <button className={`chip${win === 'custom' ? ' on' : ''}`} aria-pressed={win === 'custom'} onClick={() => setWin('custom')}>Dates</button>
      </div>
      {win === 'custom' && (
        <div className="date-row">
          <label>From <input type="date" value={range.start} max={range.end || undefined} onChange={e => setRange(r => ({ ...r, start: e.target.value }))} /></label>
          <label>To <input type="date" value={range.end} min={range.start || undefined} onChange={e => setRange(r => ({ ...r, end: e.target.value }))} /></label>
        </div>
      )}

      {loading && !feed && <Loading label="Reading today’s filings…" />}
      {err && <ErrorNote msg={err} retry={load} />}
      {win === 'custom' && !range.start && <p className="muted pad">Pick a start date to load filings for that period.</p>}

      {feed && (
        <>
          <p className={`brief${loading ? ' dim' : ''}`} aria-live="polite">
            {feed.counts.total === 0 && failed.length === feed.sources.length && failed.length > 0 ? (
              <>Couldn’t reach the exchanges, so FINN can’t tell what changed.</>
            ) : feed.counts.total === 0 ? (
              <>Quiet window. Nothing filed by your portfolio companies.</>
            ) : (
              <>
                <button className="n-high" onClick={() => jump('tier-high')}>{counts.high} {counts.high === 1 ? 'filing needs' : 'filings need'} you.</button>{' '}
                <button className="n-med" onClick={() => jump('tier-medium')}>{counts.medium} worth a glance.</button>{' '}
                <button className="n-low" onClick={() => { setShowRoutine(true); setTimeout(() => jump('tier-low'), 50) }}>{counts.low} routine, folded away.</button>
              </>
            )}
          </p>

          {failed.length > 0 && (
            <p className="source-warn" role="status">
              {failed.map(s => `${s.name}: ${s.detail}`).join(' · ')}. Some filings may be missing.
            </p>
          )}

          <div className="filters">
            <label className="sel">
              <span className="sr-only">Company</span>
              <select value={company} onChange={e => setCompany(e.target.value)}>
                <option value="">All companies</option>
                {[...new Set(feed.items.map(i => i.symbol))].sort().map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="sel">
              <span className="sr-only">Category</span>
              <select value={category} onChange={e => setCategory(e.target.value)}>
                <option value="">All types</option>
                {Object.keys(feed.counts.category).sort().map(c => <option key={c} value={c}>{catLabel(c)} ({feed.counts.category[c]})</option>)}
              </select>
            </label>
            {filtered && <button className="btn-ghost" onClick={() => { setCompany(''); setCategory('') }}>Clear</button>}
          </div>

          {moves.length > 0 && !filtered && (
            <div className="block">
              <h2 className="h2">Moved at last close <span className="muted small">end-of-day, {feed.market.provider}</span></h2>
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
              <h2 className="h2">{TIER_NAME[t]}</h2>
              <ul className="feed">{byTier(t).map(i => <Row key={i.uid} i={i} onOpen={openFiling} />)}</ul>
            </div>
          ))}

          {byTier('low').length > 0 && (
            <div className="block" id="tier-low">
              <button className="fold" aria-expanded={showRoutine} onClick={() => setShowRoutine(s => !s)}>
                {showRoutine ? 'Hide' : 'Show'} {byTier('low').length} routine filings
              </button>
              {showRoutine && <ul className="feed routine">{byTier('low').map(i => <Row key={i.uid} i={i} onOpen={openFiling} compact />)}</ul>}
            </div>
          )}

          {items.length === 0 && feed.counts.total > 0 && <p className="muted pad">No filings match these filters.</p>}
        </>
      )}
    </section>
  )
}

function Row({ i, onOpen, compact }: { i: FeedItem; onOpen: (i: FeedItem) => void; compact?: boolean }) {
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
