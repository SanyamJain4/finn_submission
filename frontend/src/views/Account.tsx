import { useEffect, useState } from 'react'
import { api, type AlertPrefs } from '../api'
import { catLabel } from '../format'
import { KEYS, clearAll, useStored } from '../store'
import { ErrorNote, Skeleton } from '../ui'

type Status = Awaited<ReturnType<typeof api.status>>
type Port = Awaited<ReturnType<typeof api.portfolio>>
type Diag = Awaited<ReturnType<typeof api.diagnostics>>

const SECTIONS = [['acct', 'My account'], ['prefs', 'Investment preferences'], ['system', 'System status']] as const

export default function Account() {
  const [profile, setProfile] = useStored<{ name?: string; email?: string }>(KEYS.profile, {})
  const [p, setP] = useState<AlertPrefs | null>(null)
  const [st, setSt] = useState<Status | null>(null)
  const [port, setPort] = useState<Port | null>(null)
  const [diag, setDiag] = useState<Diag | null>(null)
  const [diagBusy, setDiagBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [name, setName] = useState(profile?.name || '')
  const [email, setEmail] = useState(profile?.email || '')

  useEffect(() => {
    api.prefs().then(setP).catch(e => setErr(e.message))
    api.status().then(setSt).catch(() => {})
    api.portfolio().then(setPort).catch(() => {})
  }, [])

  const savePrefs = () => { if (!p) return; setMsg(null); api.savePrefs(p).then(x => { setP(x); setMsg('Alert rules saved.') }).catch(e => setErr(e.message)) }
  const toggle = (c: string) => p && setP({ ...p, categories: p.categories.includes(c) ? p.categories.filter(x => x !== c) : [...p.categories, c] })
  const runDiag = () => { setDiagBusy(true); api.diagnostics().then(setDiag).catch(e => setErr(e.message)).finally(() => setDiagBusy(false)) }

  return (
    <section className="view account" aria-labelledby="acc-h">
      <h1 id="acc-h" className="h1">Account</h1>
      <nav className="section-nav" aria-label="Account sections">
        {SECTIONS.map(([id, l]) => <button key={id} type="button" onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })}>{l}</button>)}
      </nav>
      {err && <ErrorNote msg={err} />}

      <section id="acct" className="block card">
        <h2 className="h2">My account</h2>
        <form className="hold-form" onSubmit={e => { e.preventDefault(); setProfile({ name: name.trim(), email: email.trim() }); setMsg('Profile saved on this device.') }}>
          <div className="fld-row">
            <label className="fld">Display name<input value={name} onChange={e => setName(e.target.value)} placeholder="Your name" maxLength={60} /></label>
            <label className="fld">Email <span className="muted small">optional</span><input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" maxLength={120} /></label>
          </div>
          <div className="row-actions"><button className="btn" type="submit">Save profile</button></div>
        </form>
        <p className="muted small">This prototype has no sign-in. Your profile, holdings, alert read-states and Copilot history stay in this browser and are never stored on FINN’s server.</p>
        <button className="btn-ghost danger" onClick={() => { if (window.confirm('Remove your profile, holdings, alert states and Copilot history from this browser?')) { clearAll(); setName(''); setEmail(''); setMsg('Local data cleared.') } }}>Clear my data from this browser</button>
      </section>

      <section id="prefs" className="block card">
        <h2 className="h2">Investment preferences</h2>
        {!p || !st ? <Skeleton lines={6} /> : (
          <form className="settings" onSubmit={e => { e.preventDefault(); savePrefs() }}>
            <h3 className="h3">Alert me about these filings</h3>
            <fieldset className="checks">
              <legend className="sr-only">Filing types</legend>
              {st.categories.filter(c => c !== 'unclassified').map(c => (
                <label key={c} className={`check${p.categories.includes(c) ? ' on' : ''}`}><input type="checkbox" checked={p.categories.includes(c)} onChange={() => toggle(c)} />{catLabel(c)}</label>
              ))}
            </fieldset>
            <label className="field">Only if ranked at least
              <select value={p.min_tier} onChange={e => setP({ ...p, min_tier: e.target.value as AlertPrefs['min_tier'] })}><option value="high">Needs you</option><option value="medium">Worth a glance</option><option value="low">Any</option></select>
            </label>
            <h3 className="h3">Unusual end-of-day moves</h3>
            <label className="field">Daily price move beyond ±<span className="unit"><input type="number" min="0.5" max="50" step="0.5" value={p.price_move_pct} onChange={e => setP({ ...p, price_move_pct: Number(e.target.value) })} />%</span></label>
            <label className="field">Volume above<span className="unit"><input type="number" min="1.1" max="50" step="0.1" value={p.volume_multiple} onChange={e => setP({ ...p, volume_multiple: Number(e.target.value) })} />× average</span></label>
            <label className="field">Average over the last<span className="unit"><input type="number" min="5" max="120" step="1" value={p.volume_window} onChange={e => setP({ ...p, volume_window: Number(e.target.value) })} />sessions</span></label>
            <div className="row-actions"><button className="btn" type="submit">Save alert rules</button>{msg && <span className="ok small" role="status">{msg}</span>}</div>
          </form>
        )}
        {port && (
          <>
            <h3 className="h3 watch-h">Watchlist <span className="muted small">{port.portfolio.length} companies FINN monitors for filings and price moves</span></h3>
            <ul className="port">{port.portfolio.map(c => <li key={c.symbol}><b>{c.symbol}</b><span>{c.name}</span><span className="muted small">{c.sector}, {c.size.toLowerCase()} cap</span></li>)}</ul>
            <p className="muted small">Monitoring is separate from what you own (that’s My portfolio). The watchlist is set server-side in backend/data/portfolio.json.</p>
          </>
        )}
      </section>

      <section id="system" className="block card">
        <h2 className="h2">System status</h2>
        {!st ? <Skeleton lines={3} /> : (
          <dl className="status-list">
            <div><dt>Data mode</dt><dd>{st.fixture_mode ? 'Synthetic fixtures (offline development)' : 'Live: NSE/BSE filings, Yahoo Finance prices, Screener + company documents for research'}</dd></div>
            <div><dt>AI model</dt><dd>{st.llm.enabled ? `${st.llm.provider}: ${st.llm.fast_model} for extraction and briefings, ${st.llm.smart_model} for research and Copilot` : 'Not configured. Rules, numbers and alerts still work; briefing falls back to rules.'}</dd></div>
            {st.llm_usage.by_model.map(u => <div key={u.model}><dt>{u.model}</dt><dd>{u.calls} calls, {u.cache_hits} from cache, {(u.input_tokens + u.output_tokens).toLocaleString('en-IN')} tokens{u.errors ? `, ${u.errors} errors` : ''}</dd></div>)}
          </dl>
        )}
        <div className="row-actions"><button className="btn-ghost" onClick={runDiag} disabled={diagBusy}>{diagBusy ? 'Testing sources…' : 'Test data sources from this server'}</button></div>
        {diag && (
          <>
            <ul className="diag">{diag.probes.map(x => <li key={x.name} className={x.ok ? 'ok' : 'bad'}><span className="diag-name">{x.ok ? 'Reachable' : 'Not reachable'}: {x.name}</span><span className="muted small">{x.detail} ({x.ms} ms)</span></li>)}</ul>
            <p className="muted small">{diag.snapshot ? `Fallback snapshot: captured ${new Date(diag.snapshot.captured_at).toLocaleString('en-IN')} from ${diag.snapshot.sources.join(', ')}${diag.snapshot_reports.length ? `; offline research for ${diag.snapshot_reports.join(', ')}` : ''}.` : 'No fallback snapshot deployed.'} Checked {new Date(diag.checked_at).toLocaleTimeString('en-IN')}.</p>
          </>
        )}
      </section>
    </section>
  )
}
