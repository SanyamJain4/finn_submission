import { useEffect, useState } from 'react'
import { api, type HoldingInput, type HoldingRow, type Valuation } from '../api'
import { compactRupees, pct, rupees, shortDate, sign, signedRupees } from '../format'
import { KEYS, askCopilot, useStored } from '../store'
import { ErrorNote, Sheet, ShareBar, Skeleton } from '../ui'

export default function Portfolio({ research }: { research: (s: string) => void }) {
  const [stored, setHoldings] = useStored<HoldingInput[]>(KEYS.holdings, [])
  const holdings = stored || []
  const [v, setV] = useState<Valuation | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [edit, setEdit] = useState<{ idx: number | null; h: Partial<HoldingInput> } | null>(null)
  const [exampleNote, setExampleNote] = useState<string | null>(null)

  const load = () => {
    setErr(null)
    if (!holdings.length) { setV(null); return }
    api.valueHoldings(holdings).then(setV).catch(e => setErr(e.message))
  }
  useEffect(load, [stored]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadExample = () => api.exampleHoldings().then(r => { setHoldings(r.holdings.map(({ symbol, qty, avg_price }) => ({ symbol, qty, avg_price }))); setExampleNote(r.note) }).catch(e => setErr(e.message))
  const save = (h: HoldingInput, idx: number | null) => {
    const next = idx == null ? [...holdings] : holdings.filter(x => x.symbol !== h.symbol)
    next.push(h)
    setHoldings(next); setEdit(null)
  }
  // Rows are merged per symbol by the server; edit the merged position (replaces any duplicate entries).
  const openEdit = (sym: string) => {
    const rows = holdings.filter(x => x.symbol === sym)
    const qty = rows.reduce((n, x) => n + x.qty, 0)
    const avg = rows.reduce((n, x) => n + x.qty * x.avg_price, 0) / (qty || 1)
    setEdit({ idx: holdings.findIndex(x => x.symbol === sym), h: { ...rows[0], qty, avg_price: Math.round(avg * 100) / 100 } })
  }
  const remove = (sym: string) => { setHoldings(holdings.filter(h => h.symbol !== sym)); setEdit(null) }

  return (
    <section className="view" aria-labelledby="pf-h">
      <div className="view-head">
        <h1 id="pf-h" className="h1">My portfolio</h1>
        <div className="head-actions">
          {holdings.length > 0 && <button className="btn-ghost" onClick={() => askCopilot({ page: 'portfolio', label: 'My portfolio' }, 'How is my portfolio doing, and what in my holdings needs attention?')}>Ask Copilot</button>}
          <button className="btn" onClick={() => setEdit({ idx: null, h: {} })}>Add holding</button>
        </div>
      </div>
      <p className="muted small lede-small">What you actually own. Stored only in this browser; FINN values it with the latest closing prices. Your watchlist is separate, under Account.</p>

      {err && <ErrorNote msg={err} retry={load} />}
      {!holdings.length && (
        <div className="empty-state">
          <p className="h3">No holdings yet.</p>
          <p className="muted small">Add each stock with the quantity and your average buy price. FINN works out value, today’s change, unrealised P&L and allocation.</p>
          <div className="row-actions"><button className="btn" onClick={() => setEdit({ idx: null, h: {} })}>Add your first holding</button><button className="btn-ghost" onClick={loadExample}>Load an example portfolio</button></div>
        </div>
      )}
      {holdings.length > 0 && !v && !err && <Skeleton lines={8} />}
      {v && (
        <>
          {exampleNote && <p className="snapshot-note">{exampleNote}</p>}
          <dl className="pf-totals">
            <div className="pf-hero"><dt>Current value</dt><dd>{compactRupees(v.totals.value)}</dd><span className="muted small">{rupees(v.totals.value)}</span></div>
            <div><dt>Invested</dt><dd>{compactRupees(v.totals.invested_priced)}</dd></div>
            <div><dt>Unrealised P&L</dt><dd className={sign(v.totals.pnl)}>{signedRupees(v.totals.pnl)}</dd><span className={`small ${sign(v.totals.pnl_pct)}`}>{pct(v.totals.pnl_pct, 2)}</span></div>
            <div><dt>Today</dt><dd className={sign(v.totals.day_change)}>{signedRupees(v.totals.day_change)}</dd><span className={`small ${sign(v.totals.day_change_pct)}`}>{pct(v.totals.day_change_pct, 2)}</span></div>
          </dl>
          <p className="muted small data-stamp">End-of-day prices, close of {shortDate(v.totals.as_of)}{v.provider ? ` (${v.provider === 'yfinance' ? 'Yahoo Finance' : v.provider})` : ''}. {v.note}</p>
          {v.totals.unpriced.length > 0 && <p className="note">No price available for {v.totals.unpriced.join(', ')}; excluded from value, P&L and allocation (cost still counted in “Invested” total of {rupees(v.totals.invested)}).</p>}

          <div className="pf-grid">
            <div className="card">
              <h2 className="h3">By sector</h2>
              <ShareBar items={v.allocation.sector} label="Allocation by sector" />
            </div>
            <div className="card">
              <h2 className="h3">By market cap</h2>
              <ShareBar items={v.allocation.cap} label="Allocation by market cap" />
              {(v.best || v.worst) && (
                <div className="bw">
                  {v.best && <BW label="Best" row={v.holdings.find(h => h.symbol === v.best)!} />}
                  {v.worst && v.worst !== v.best && <BW label="Worst" row={v.holdings.find(h => h.symbol === v.worst)!} />}
                </div>
              )}
            </div>
          </div>

          <h2 className="h2 pf-list-h">Holdings</h2>
          <div className="table-wrap">
            <table className="holdings-table">
              <thead><tr><th scope="col">Stock</th><th scope="col">Qty × avg</th><th scope="col">Price</th><th scope="col">Value</th><th scope="col">P&L</th><th scope="col" className="hide-sm">Weight</th></tr></thead>
              <tbody>
                {v.holdings.map(h => (
                  <tr key={h.symbol} onClick={() => openEdit(h.symbol)} tabIndex={0} onKeyDown={e => e.key === 'Enter' && openEdit(h.symbol)}>
                    <th scope="row"><b>{h.symbol}</b><small>{h.sector}, {h.cap === 'Unclassified' ? 'cap n/a' : `${h.cap.toLowerCase()} cap`}</small></th>
                    <td>{h.qty.toLocaleString('en-IN')}<small>@ {rupees(h.avg_price, true)}</small></td>
                    <td>{h.price == null ? '—' : rupees(h.price, true)}<small className={sign(h.day_change_pct)}>{pct(h.day_change_pct, 2)}</small></td>
                    <td>{rupees(h.value)}<small className="muted">cost {rupees(h.invested)}</small></td>
                    <td className={sign(h.pnl)}>{signedRupees(h.pnl)}<small>{pct(h.pnl_pct, 1)}</small></td>
                    <td className="hide-sm">{h.weight == null ? '—' : `${h.weight.toFixed(1)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">Tap a holding to edit it, research it, or remove it.</p>
        </>
      )}
      {edit && <EditSheet init={edit.h} idx={edit.idx} rows={v?.holdings || []} onSave={save} onRemove={remove} onClose={() => setEdit(null)} research={research} />}
    </section>
  )
}

function BW({ label, row }: { label: string; row: HoldingRow }) {
  return <p className="bw-item"><span className="muted small">{label}</span> <b>{row.symbol}</b> <span className={sign(row.pnl_pct)}>{pct(row.pnl_pct, 1)}</span></p>
}

function EditSheet({ init, idx, rows, onSave, onRemove, onClose, research }: {
  init: Partial<HoldingInput>; idx: number | null; rows: HoldingRow[]; onSave: (h: HoldingInput, idx: number | null) => void
  onRemove: (s: string) => void; onClose: () => void; research: (s: string) => void
}) {
  const [sym, setSym] = useState(init.symbol || '')
  const [qty, setQty] = useState(init.qty ? String(init.qty) : '')
  const [avg, setAvg] = useState(init.avg_price ? String(init.avg_price) : '')
  const [sector, setSector] = useState(init.sector || '')
  const [cap, setCap] = useState(init.cap || '')
  const [hits, setHits] = useState<{ symbol: string; name: string; in_portfolio: boolean }[]>([])
  const [err, setErr] = useState<string | null>(null)
  const row = rows.find(r => r.symbol === init.symbol)

  useEffect(() => {
    if (sym.length < 2 || sym === init.symbol) { setHits([]); return }
    const t = setTimeout(() => api.search(sym).then(r => setHits(r.results.slice(0, 5))).catch(() => setHits([])), 250)
    return () => clearTimeout(t)
  }, [sym, init.symbol])

  const submit = () => {
    const s = sym.trim().toUpperCase().replace(/\.(NS|BO)$/, '')
    const q = Number(qty), a = Number(avg)
    if (!/^[A-Z0-9][A-Z0-9&-]{0,19}$/.test(s)) return setErr('Enter a valid NSE symbol, e.g. TCS.')
    if (!(q > 0)) return setErr('Quantity must be more than zero.')
    if (!(a > 0)) return setErr('Average price must be more than zero.')
    onSave({ symbol: s, qty: q, avg_price: a, sector: sector.trim() || null, cap: cap || null }, idx)
  }

  return (
    <Sheet onClose={onClose} label={idx == null ? 'Add holding' : `Edit ${init.symbol}`}>
      <h2 className="h1">{idx == null ? 'Add a holding' : init.symbol}</h2>
      {row && row.price != null && <p className="muted small">{row.name}. Last close {rupees(row.price, true)}, value {rupees(row.value)}, unrealised <span className={sign(row.pnl)}>{signedRupees(row.pnl)} ({pct(row.pnl_pct, 1)})</span>.</p>}
      <form className="hold-form" onSubmit={e => { e.preventDefault(); submit() }}>
        <label className="fld">NSE symbol
          <input value={sym} onChange={e => { setSym(e.target.value.toUpperCase()); setErr(null) }} placeholder="e.g. TCS" autoComplete="off" autoFocus={idx == null} disabled={idx != null} />
        </label>
        {hits.length > 0 && <ul className="suggest-inline">{hits.map(h => <li key={h.symbol}><button type="button" onClick={() => { setSym(h.symbol); setHits([]) }}><b>{h.symbol}</b> {h.name}{h.in_portfolio && <span className="tag">Watchlist</span>}</button></li>)}</ul>}
        <div className="fld-row">
          <label className="fld">Quantity<input inputMode="decimal" value={qty} onChange={e => setQty(e.target.value)} placeholder="10" /></label>
          <label className="fld">Average price (₹)<input inputMode="decimal" value={avg} onChange={e => setAvg(e.target.value)} placeholder="1250.50" /></label>
        </div>
        <div className="fld-row">
          <label className="fld">Sector <span className="muted small">optional</span><input value={sector} onChange={e => setSector(e.target.value)} placeholder="Auto for watchlist stocks" /></label>
          <label className="fld">Market cap <span className="muted small">optional</span>
            <select value={cap} onChange={e => setCap(e.target.value)}><option value="">Auto / not set</option><option>Large</option><option>Mid</option><option>Small</option></select>
          </label>
        </div>
        {err && <p className="neg small" role="alert">{err}</p>}
        <div className="sheet-actions">
          <button className="btn" type="submit">{idx == null ? 'Add holding' : 'Save changes'}</button>
          {idx != null && init.symbol && <>
            <button type="button" className="btn-ghost" onClick={() => research(init.symbol!)}>Research {init.symbol}</button>
            <button type="button" className="btn-ghost" onClick={() => askCopilot({ symbol: init.symbol, page: 'portfolio', label: `${init.symbol} holding` }, `How is my ${init.symbol} holding doing and what has the company filed recently?`)}>Ask Copilot</button>
            <button type="button" className="btn-ghost danger" onClick={() => onRemove(init.symbol!)}>Remove</button>
          </>}
        </div>
      </form>
    </Sheet>
  )
}
