import { useCallback, useEffect, useState } from 'react'
import { api, type Alerts as A, type FeedItem } from '../api'
import { ago, catLabel, stamp } from '../format'
import { ErrorNote, Loading, Rail } from '../ui'

export default function Alerts({ openFiling, goSettings }: { openFiling: (i: FeedItem) => void; goSettings: () => void }) {
  const [a, setA] = useState<A | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const check = useCallback(() => {
    setBusy(true); setErr(null)
    api.alerts().then(setA).catch(e => setErr(e.message)).finally(() => setBusy(false))
  }, [])
  useEffect(check, [check])

  return (
    <section className="view" aria-labelledby="alerts-h">
      <div className="view-head">
        <h1 id="alerts-h" className="h1">Alerts</h1>
        <button className="btn-ghost" onClick={check} disabled={busy}>{busy ? 'Checking…' : 'Check now'}</button>
      </div>
      {a && (
        <p className="muted small">
          Rules: {a.prefs.categories.map(catLabel).join(', ')} at “{a.prefs.min_tier === 'high' ? 'needs you' : a.prefs.min_tier === 'medium' ? 'worth a glance' : 'any'}” or above;
          price ±{a.prefs.price_move_pct}% or volume ≥{a.prefs.volume_multiple}× the {a.prefs.volume_window}-session average.{' '}
          <button className="link" onClick={goSettings}>Change rules</button>
        </p>
      )}
      {!a && !err && <Loading label="Checking your rules…" />}
      {err && <ErrorNote msg={err} retry={check} />}
      {a && (
        <>
          <div className="block">
            <h2 className="h2">Price and volume</h2>
            {a.market_alerts.length === 0 ? <p className="muted">No stock crossed your thresholds at the last close.</p> : (
              <ul className="alert-list">
                {a.market_alerts.map((m, k) => (
                  <li key={k} className={`alert ${m.type === 'price_move' ? (m.value >= 0 ? 'pos' : 'neg') : 'vol'}`}>
                    <span className="alert-sym">{m.company}</span>
                    <span>{m.text}</span>
                    <span className="muted small">Close of {m.as_of}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="block">
            <h2 className="h2">Filings that match</h2>
            {a.filing_alerts.length === 0 ? <p className="muted">Nothing in the last 24 hours matches your filing rules.</p> : (
              <ul className="feed">
                {a.filing_alerts.map(i => (
                  <li key={i.uid}>
                    <button className="row" onClick={() => openFiling(i)}>
                      <Rail score={i.priority} tier={i.tier} />
                      <span className="row-body">
                        <span className="row-top"><span className="row-co">{i.company}</span><time className="muted small">{ago(i.published)}</time></span>
                        <span className="row-sum">{i.summary}</span>
                        <span className="row-meta"><span className={`cat cat-${i.category.replace('&', '')}`}>{catLabel(i.category)}</span></span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="muted small pad">Checked {stamp(a.checked_at)}. {a.note}</p>
        </>
      )}
    </section>
  )
}
