import { useEffect, useState } from 'react'
import { api, type AlertPrefs } from '../api'
import { catLabel } from '../format'
import { ErrorNote, Loading } from '../ui'

type Status = Awaited<ReturnType<typeof api.status>>
type Port = Awaited<ReturnType<typeof api.portfolio>>

export default function Settings() {
  const [p, setP] = useState<AlertPrefs | null>(null)
  const [st, setSt] = useState<Status | null>(null)
  const [port, setPort] = useState<Port | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [diag, setDiag] = useState<Awaited<ReturnType<typeof api.diagnostics>> | null>(null)
  const [diagBusy, setDiagBusy] = useState(false)
  const runDiag = () => { setDiagBusy(true); api.diagnostics().then(setDiag).catch(e => setErr(e.message)).finally(() => setDiagBusy(false)) }

  useEffect(() => {
    api.prefs().then(setP).catch(e => setErr(e.message))
    api.status().then(setSt).catch(() => {})
    api.portfolio().then(setPort).catch(() => {})
  }, [])

  const save = () => {
    if (!p) return
    setMsg(null); setErr(null)
    api.savePrefs(p).then(x => { setP(x); setMsg('Alert rules saved.') }).catch(e => setErr(e.message))
  }
  const toggle = (c: string) => p && setP({ ...p, categories: p.categories.includes(c) ? p.categories.filter(x => x !== c) : [...p.categories, c] })

  return (
    <section className="view" aria-labelledby="set-h">
      <h1 id="set-h" className="h1">Settings</h1>
      {!p && !err && <Loading label="Loading your rules…" />}
      {err && <ErrorNote msg={err} />}
      {p && st && (
        <form className="block settings" onSubmit={e => { e.preventDefault(); save() }}>
          <h2 className="h2">Alert me about</h2>
          <fieldset className="checks">
            <legend className="sr-only">Filing types</legend>
            {st.categories.filter(c => c !== 'unclassified').map(c => (
              <label key={c} className={`check${p.categories.includes(c) ? ' on' : ''}`}>
                <input type="checkbox" checked={p.categories.includes(c)} onChange={() => toggle(c)} />{catLabel(c)}
              </label>
            ))}
          </fieldset>
          <label className="field">Only if ranked at least
            <select value={p.min_tier} onChange={e => setP({ ...p, min_tier: e.target.value as AlertPrefs['min_tier'] })}>
              <option value="high">Needs you</option><option value="medium">Worth a glance</option><option value="low">Any</option>
            </select>
          </label>
          <h2 className="h2">Unusual end-of-day moves</h2>
          <label className="field">Daily price move beyond ±
            <span className="unit"><input type="number" min="0.5" max="50" step="0.5" value={p.price_move_pct} onChange={e => setP({ ...p, price_move_pct: Number(e.target.value) })} />%</span>
          </label>
          <label className="field">Volume above
            <span className="unit"><input type="number" min="1.1" max="50" step="0.1" value={p.volume_multiple} onChange={e => setP({ ...p, volume_multiple: Number(e.target.value) })} />× average</span>
          </label>
          <label className="field">Average over the last
            <span className="unit"><input type="number" min="5" max="120" step="1" value={p.volume_window} onChange={e => setP({ ...p, volume_window: Number(e.target.value) })} />sessions</span>
          </label>
          <div className="row-actions"><button className="btn" type="submit">Save alert rules</button>{msg && <span className="ok small" role="status">{msg}</span>}</div>
        </form>
      )}

      {st && (
        <div className="block">
          <h2 className="h2">Data and model status</h2>
          <dl className="status-list">
            <div><dt>Data mode</dt><dd>{st.fixture_mode ? 'Synthetic fixtures (offline development)' : 'Live: NSE / BSE, Yahoo Finance, Screener'}</dd></div>
            <div><dt>AI model</dt><dd>{st.llm.enabled ? `${st.llm.provider}: ${st.llm.fast_model} for extraction, ${st.llm.smart_model} for synthesis` : 'Not configured. Rules, numbers and alerts still work.'}</dd></div>
            {st.llm_usage.by_model.map(u => (
              <div key={u.model}><dt>{u.model}</dt><dd>{u.calls} calls, {u.cache_hits} from cache, {(u.input_tokens + u.output_tokens).toLocaleString('en-IN')} tokens{u.errors ? `, ${u.errors} errors` : ''}</dd></div>
            ))}
          </dl>
          <div className="row-actions"><button className="btn-ghost" onClick={runDiag} disabled={diagBusy}>{diagBusy ? 'Testing sources…' : 'Test data sources from this server'}</button></div>
          {diag && (
            <>
              <ul className="diag">
                {diag.probes.map(p => (
                  <li key={p.name} className={p.ok ? 'ok' : 'bad'}>
                    <span className="diag-name">{p.ok ? 'Reachable' : 'Blocked'}: {p.name}</span>
                    <span className="muted small">{p.detail} ({p.ms} ms)</span>
                  </li>
                ))}
              </ul>
              <p className="muted small">
                {diag.snapshot ? `Fallback snapshot: captured ${new Date(diag.snapshot.captured_at).toLocaleString('en-IN')} from ${diag.snapshot.sources.join(', ')}${diag.snapshot_reports.length ? `; offline research for ${diag.snapshot_reports.join(', ')}` : ''}.` : 'No fallback snapshot deployed. Run scripts/make_snapshot.py on a machine that can reach the exchanges.'}
              </p>
            </>
          )}
        </div>
      )}

      {port && (
        <div className="block">
          <h2 className="h2">Portfolio ({port.portfolio.length})</h2>
          <ul className="port">
            {port.portfolio.map(c => <li key={c.symbol}><b>{c.symbol}</b><span>{c.name}</span><span className="muted small">{c.sector}, {c.size.toLowerCase()} cap</span></li>)}
          </ul>
          <p className="muted small">Edit backend/data/portfolio.json to change holdings.</p>
        </div>
      )}
    </section>
  )
}
