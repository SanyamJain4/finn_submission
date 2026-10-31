import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type Alerts as A, type FeedItem } from '../api'
import { KIND_LABEL, alertItems, type AlertItem, type AlertKind } from '../alerts'
import { ago, catLabel, stamp } from '../format'
import { KEYS, askCopilot, useStored, type AlertState } from '../store'
import { ErrorNote, Skeleton } from '../ui'

export default function Alerts({ openFiling }: { openFiling: (i: FeedItem) => void }) {
  const [a, setA] = useState<A | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [kind, setKind] = useState<AlertKind | 'all'>('all')
  const [showAck, setShowAck] = useState(false)
  const [state, setState] = useStored<AlertState>(KEYS.alertState, {})
  const st = state || {}

  const check = useCallback(() => {
    setBusy(true); setErr(null)
    api.alerts().then(setA).catch(e => setErr(e.message)).finally(() => setBusy(false))
  }, [])
  useEffect(check, [check])

  const items = useMemo(() => (a ? alertItems(a) : []), [a])
  const visible = items.filter(i => kind === 'all' || i.kind === kind)
  const open = visible.filter(i => !st[i.id]?.ack)
  const acked = visible.filter(i => st[i.id]?.ack)
  const unread = items.filter(i => !st[i.id]?.read).length
  const set = (id: string, patch: { read?: boolean; ack?: boolean }) => setState({ ...st, [id]: { ...st[id], ...patch } })
  const markAll = () => setState({ ...st, ...Object.fromEntries(items.map(i => [i.id, { ...st[i.id], read: true }])) })
  const counts = (k: AlertKind) => items.filter(i => i.kind === k && !st[i.id]?.ack).length

  const openItem = (i: AlertItem) => {
    set(i.id, { read: true })
    if (i.filing) openFiling(i.filing)
  }

  return (
    <section className="view" aria-labelledby="alerts-h">
      <div className="view-head">
        <h1 id="alerts-h" className="h1">Alerts</h1>
        <div className="head-actions">
          {unread > 0 && <button className="btn-ghost" onClick={markAll}>Mark all read</button>}
          <button className="btn-ghost" onClick={check} disabled={busy}>{busy ? 'Checking…' : 'Check now'}</button>
        </div>
      </div>
      <p className="muted small lede-small">Only things that matched your rules. Today shows everything ranked; this is what needs a decision.</p>

      <div className="window-row" role="group" aria-label="Alert type">
        <button className={`chip${kind === 'all' ? ' on' : ''}`} aria-pressed={kind === 'all'} onClick={() => setKind('all')}>All</button>
        {(Object.keys(KIND_LABEL) as AlertKind[]).map(k => (
          <button key={k} className={`chip${kind === k ? ' on' : ''}`} aria-pressed={kind === k} onClick={() => setKind(k)}>{KIND_LABEL[k]}{counts(k) > 0 && <span className="chip-n">{counts(k)}</span>}</button>
        ))}
      </div>

      {!a && !err && <div className="pad"><Skeleton lines={5} /></div>}
      {err && <ErrorNote msg={err} retry={check} />}
      {a && (
        <>
          {open.length === 0 ? (
            <div className="empty-state">
              <p className="h3">You’re clear.</p>
              <p className="muted small">{items.length ? 'Everything here has been acknowledged.' : 'Nothing matched your rules at the last check.'} FINN checks filings for the last 24 hours and the last end-of-day prices.</p>
            </div>
          ) : (
            <ul className="alert-list">
              {open.map(i => <AlertRow key={i.id} i={i} read={!!st[i.id]?.read} onOpen={() => openItem(i)} onAck={() => set(i.id, { ack: true, read: true })} />)}
            </ul>
          )}
          {acked.length > 0 && (
            <div className="block">
              <button className="fold" aria-expanded={showAck} onClick={() => setShowAck(s => !s)}>{showAck ? 'Hide' : 'Show'} {acked.length} acknowledged</button>
              {showAck && <ul className="alert-list acked">{acked.map(i => <AlertRow key={i.id} i={i} read onOpen={() => openItem(i)} onAck={() => set(i.id, { ack: false })} acked />)}</ul>}
            </div>
          )}
          <div className="card rules-card">
            <h2 className="h3">Your rules</h2>
            <p className="small">Filings: {a.prefs.categories.map(catLabel).join(', ')}, ranked “{a.prefs.min_tier === 'high' ? 'needs you' : a.prefs.min_tier === 'medium' ? 'worth a glance' : 'any'}” or higher.</p>
            <p className="small">Prices: daily move beyond ±{a.prefs.price_move_pct}%, or volume ≥ {a.prefs.volume_multiple}× its {a.prefs.volume_window}-session average.</p>
            <p className="muted small">Last checked {stamp(a.checked_at)}. {a.note}</p>
            <a className="btn-ghost" href="#/account">Edit rules</a>
          </div>
        </>
      )}
    </section>
  )
}

function AlertRow({ i, read, onOpen, onAck, acked }: { i: AlertItem; read: boolean; onOpen: () => void; onAck: () => void; acked?: boolean }) {
  return (
    <li className={`alert-item k-${i.kind} s-${i.severity}${read ? '' : ' unread'}`}>
      <button className="alert-main" onClick={onOpen} disabled={!i.filing && read}>
        <span className="alert-top">
          {!read && <span className="dot-unread" aria-label="Unread" />}
          <span className="alert-kind">{KIND_LABEL[i.kind]}</span>
          <span className="muted small">{i.time ? ago(i.time) : ''}</span>
        </span>
        <span className="alert-title">{i.title}</span>
        <span className="alert-detail">{i.detail}</span>
        <span className="muted small">{i.why}</span>
      </button>
      <div className="alert-actions">
        {!read && !i.filing && <button className="link" onClick={onOpen}>Mark read</button>}
        <button className="link" onClick={onAck}>{acked ? 'Restore' : 'Acknowledge'}</button>
        <button className="link" onClick={() => askCopilot({ symbol: i.symbol, uid: i.filing?.uid, label: i.title }, i.kind === 'market' ? `Are there recent filings from ${i.symbol} that relate to this move?` : 'What does this filing say, and what should I look at next?')}>Ask Copilot</button>
      </div>
    </li>
  )
}
