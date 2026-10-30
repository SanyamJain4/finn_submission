import { useEffect, useState } from 'react'
import { api, type FeedItem, type FilingDetail, type ResultsX } from '../api'
import { catLabel, cr, pct, plainPct, sign, stamp } from '../format'
import { ErrorNote, Loading, Sheet, SnapshotNote } from '../ui'

export default function Filing({ item, onClose, research }: { item: FeedItem; onClose: () => void; research: (sym: string) => void }) {
  const [d, setD] = useState<FilingDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = () => { setErr(null); api.filing(item.uid).then(setD).catch(e => setErr(e.message)) }
  useEffect(load, [item.uid])

  return (
    <Sheet onClose={onClose} label={`${item.company} filing`}>
      <header className="sheet-head">
        <p className="muted small">{item.symbol} · {item.sector}</p>
        <h2 className="h1">{item.company}</h2>
        <p className="sheet-subject">{item.subject}</p>
        <p className="muted small">
          {stamp(item.published)} · {item.exchange} · <span className={`cat cat-${item.category.replace('&', '')}`}>{catLabel(item.category)}</span>
        </p>
      </header>

      <div className="why-box">
        <h3 className="h3">Why it’s ranked here <span className={`tier-badge t-${item.tier}`}>{item.priority}/100</span></h3>
        <ul className="why">{item.why.map((w, k) => <li key={k}>{w}</li>)}</ul>
        <p className="muted small">Classified as {catLabel(item.category)} from {item.category_rule} (confidence {Math.round(item.category_confidence * 100)}%). Priority is about materiality, not a price prediction.</p>
      </div>

      {item.text && item.text !== item.subject && <p className="exch-text"><span className="muted small">Exchange text</span><br />{item.text}</p>}

      {!d && !err && <Loading label={item.url ? 'Opening the filing…' : 'Loading…'} />}
      {err && <ErrorNote msg={err} retry={load} />}

      {d && (
        <>
          <SnapshotNote s={d.snapshot} />
          {d.results && <Results r={d.results} />}
          {d.people && <People p={d.people} />}
          {d.llm_summary && (
            <div className="block">
              <h3 className="h3">Summary</h3>
              <p>{d.llm_summary.summary}</p>
              {!d.llm_summary.grounded && <p className="warn small">Contains numbers not found in the filing ({d.llm_summary.unsupported_numbers.join(', ')}). Check the original.</p>}
            </div>
          )}
          {d.key_lines.length > 0 && !d.results && (
            <div className="block">
              <h3 className="h3">From the filing</h3>
              <ul className="quotes">{d.key_lines.map((k, n) => <li key={n}><q>{k.text}</q> <span className="muted small">p.{k.page}</span></li>)}</ul>
            </div>
          )}
          {d.notes.map((n, k) => <p key={k} className="note">{n}</p>)}
        </>
      )}

      <div className="sheet-actions">
        {item.url ? <a className="btn" href={item.url} target="_blank" rel="noreferrer noopener">Open original filing</a> : <span className="muted small">No attachment on the exchange.</span>}
        <button className="btn-ghost" onClick={() => research(item.symbol)}>Research {item.symbol}</button>
      </div>
    </Sheet>
  )
}

function Results({ r }: { r: ResultsX }) {
  if (r.status === 'not_found' || !r.metrics.revenue) {
    return (
      <div className="block">
        <h3 className="h3">Headline numbers</h3>
        <p className="note">Couldn’t read a results table from this filing. {r.notes.join(' ')} Open the original for the figures.</p>
      </div>
    )
  }
  const per = r.periods
  const q = (iso?: string) => (iso ? new Date(iso).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' }) : '')
  return (
    <div className="block">
      <h3 className="h3">Headline numbers <span className="muted small">{r.basis ?? 'basis unknown'}, ₹ crore</span></h3>
      <div className="table-wrap">
        <table className="num-table">
          <thead>
            <tr><th scope="col"></th><th scope="col">This qtr{per.current && <small>{q(per.current)}</small>}</th><th scope="col">QoQ{per.prev_quarter && <small>vs {q(per.prev_quarter)}</small>}</th><th scope="col">YoY{per.year_ago && <small>vs {q(per.year_ago)}</small>}</th></tr>
          </thead>
          <tbody>
            {(['revenue', 'ebitda', 'pbt', 'pat'] as const).map(k => {
              const m = r.metrics[k]
              if (!m) return null
              return (
                <tr key={k}>
                  <th scope="row">{m.label}{m.derived && <sup title={m.formula}>*</sup>}{m.margin_current != null && <small>{plainPct(m.margin_current)} margin</small>}</th>
                  <td>{cr(m.current)}</td>
                  <td className={sign(m.qoq_pct)}>{m.qoq_note ?? pct(m.qoq_pct)}</td>
                  <td className={sign(m.yoy_pct)}>{m.yoy_note ?? pct(m.yoy_pct)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">* EBITDA derived: {r.metrics.ebitda?.formula}. Read from {r.unit_source ?? 'the filing'}, page {r.evidence[0]?.page}{per.confirmed ? '; column dates confirmed from the header.' : '.'}</p>
      {r.notes.map((n, k) => <p key={k} className="note">{n}</p>)}
      <details className="evidence">
        <summary>Rows as printed in the filing</summary>
        <ul>{r.evidence.map(e => <li key={e.metric}><span className="muted small">p.{e.page}</span> <code>{e.row}</code></li>)}</ul>
      </details>
    </div>
  )
}

function People({ p }: { p: NonNullable<FilingDetail['people']> }) {
  const incoming = p.structured?.filter(x => x.direction === 'incoming') ?? []
  const dir = p.directions || {}
  const inNames = p.names.filter(n => dir[n] === 'incoming')
  const outNames = p.names.filter(n => dir[n] === 'outgoing')
  const unclear = p.names.filter(n => !dir[n] || dir[n] === 'unclear')
  return (
    <div className="block">
      <h3 className="h3">{inNames.length || incoming.length ? 'Who’s coming in' : 'People named in the filing'}</h3>
      {incoming.length > 0 ? incoming.map(x => (
        <div key={x.name} className="person">
          <p className="person-name">{x.name}{x.role && <span className="muted"> · {x.role}</span>}</p>
          {x.background && <p>{x.background}</p>}
          {x.prior_roles.length > 0 && <ul className="plain">{x.prior_roles.map(r => <li key={r}>{r}</li>)}</ul>}
        </div>
      )) : (
        <>
          {inNames.length > 0 && <p className="person-name">{inNames.join(', ')}{p.roles[0] && <span className="muted">, {p.roles[0]}</span>}</p>}
          {unclear.length > 0 && <p>{unclear.join(', ')}</p>}
        </>
      )}
      {outNames.length > 0 && <p className="muted small">Leaving: {outNames.join(', ')}</p>}
      {p.effective && <p className="muted small">Effective {p.effective}</p>}
      {p.profile_passage && (
        <blockquote className="profile">
          {p.profile_passage}
          <footer className="muted small">{p.profile_source}</footer>
        </blockquote>
      )}
      {p.secondary && (
        <blockquote className="profile secondary">
          {p.secondary.summary}
          <footer className="muted small"><a href={p.secondary.url} target="_blank" rel="noreferrer noopener">{p.secondary.source}</a> · {p.secondary.caveat}</footer>
        </blockquote>
      )}
      {!p.profile_passage && !p.secondary && <p className="note">No verified background found. The filing has no profile section, and FINN doesn’t guess.</p>}
      {p.notes.map((n, k) => <p key={k} className="note">{n}</p>)}
    </div>
  )
}
