import { useEffect, useRef, useState } from 'react'
import { api, type GuidanceRow, type Job, type Report } from '../api'
import { cr, metricValue, pct, plainPct, sign } from '../format'
import { askCopilot } from '../store'
import { BarLine, ClaimLine, ErrorNote, Sheet, SnapshotNote, jump } from '../ui'

const STAGE_LABEL: Record<string, string> = {
  resolve: 'Finding the company', financials: 'Reading reported financials', documents: 'Fetching annual report and call transcripts',
  business: 'Reading what the business does', guidance: 'Pulling management’s guidance', synthesis: 'Weighing the evidence', verify: 'Checking every claim against its source',
}
const VERDICT: Record<string, string> = { met: 'Delivered', exceeded: 'Beat', missed: 'Missed', pending: 'Not yet reported', cannot_evaluate: 'Can’t compare', qualitative: 'No hard number' }

export default function Research({ symbol, setSymbol }: { symbol: string | null; setSymbol: (s: string | null) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<{ symbol: string; name: string; in_portfolio: boolean }[]>([])
  const [demos, setDemos] = useState<{ symbol: string; name: string; why: string }[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => { api.portfolio().then(p => setDemos(p.research_demos)).catch(() => {}) }, [])
  useEffect(() => {
    window.clearTimeout(timer.current)
    if (q.trim().length < 2) { setHits([]); return }
    timer.current = window.setTimeout(() => api.search(q.trim()).then(r => setHits(r.results)).catch(() => setHits([])), 250)
  }, [q])

  useEffect(() => {
    if (!symbol) { setJob(null); return }
    let alive = true
    setErr(null); setJob(null)
    const poll = (j: Job) => {
      if (!alive) return
      setJob(j)
      if (j.status === 'running' && j.job_id) window.setTimeout(() => api.job(j.job_id!).then(poll).catch(e => alive && setErr(e.message)), 1200)
    }
    api.research(symbol).then(poll).catch(e => alive && setErr(e.message))
    return () => { alive = false }
  }, [symbol])

  const rerun = () => { if (!symbol) return; setJob(null); api.research(symbol, true).then(function poll(j: Job) { setJob(j); if (j.status === 'running' && j.job_id) window.setTimeout(() => api.job(j.job_id!).then(poll), 1200) }).catch(e => setErr(e.message)) }

  return (
    <section className="view" aria-labelledby="research-h">
      <h1 id="research-h" className={symbol ? 'sr-only' : 'h1'}>Research a company</h1>
      <form className="search" role="search" onSubmit={e => { e.preventDefault(); const t = hits[0]?.symbol || q.trim().toUpperCase(); if (t) { setSymbol(t); setQ(''); setHits([]) } }}>
        <label htmlFor="rq" className="sr-only">NSE ticker or company name</label>
        <input id="rq" value={q} onChange={e => setQ(e.target.value)} placeholder="Ticker or company, e.g. TRENT" autoComplete="off" />
        <button className="btn" type="submit" disabled={!q.trim()}>Research</button>
        {hits.length > 0 && (
          <ul className="suggest" role="listbox">
            {hits.map(h => (
              <li key={h.symbol}><button type="button" onClick={() => { setSymbol(h.symbol); setQ(''); setHits([]) }}>
                <b>{h.symbol}</b> {h.name}{h.in_portfolio && <span className="tag">In portfolio</span>}
              </button></li>
            ))}
          </ul>
        )}
      </form>

      {!symbol && (
        <div className="block">
          <p className="lede">Ask about any NSE-listed company. FINN reads its annual report and last four earnings calls, and checks what management promised against what it reported.</p>
          <h2 className="h2">Try one outside your portfolio</h2>
          <ul className="demo-list">
            {demos.map(d => <li key={d.symbol}><button onClick={() => setSymbol(d.symbol)}><b>{d.name}</b><span className="muted small">{d.why}</span></button></li>)}
          </ul>
        </div>
      )}

      {err && <ErrorNote msg={err} retry={() => setSymbol(symbol)} />}
      {job?.status === 'running' && <Progress job={job} />}
      {job?.status === 'error' && <ErrorNote msg={job.error || 'Research failed'} retry={rerun} />}
      {job?.status === 'done' && job.report && <ReportView r={job.report} rerun={rerun} />}
    </section>
  )
}

function Progress({ job }: { job: Job }) {
  return (
    <div className="progress" role="status" aria-live="polite">
      <p className="h2">Researching {job.name || job.symbol}</p>
      <ol className="stages">
        {job.stages.map(s => (
          <li key={s} className={job.stages_done.includes(s) ? 'done' : job.stage === s ? 'now' : ''}>{STAGE_LABEL[s]}</li>
        ))}
      </ol>
      <p className="muted small">First run takes a minute or two while documents download. Repeat views are instant.</p>
    </div>
  )
}

const SECTIONS = [['snapshot', 'Snapshot'], ['promises', 'Promised vs delivered'], ['trajectory', 'Trajectory'], ['balance', 'Balance sheet'], ['cash', 'Cash'], ['case', 'Bull / bear'], ['sources', 'Sources']] as const

function ReportView({ r, rerun }: { r: Report; rerun: () => void }) {
  const [cite, setCite] = useState<string | null>(null)
  const M = r.metrics
  const s = r.sections
  const keyMetrics = ['revenue_fy', 'opm_fy', 'pat_fy', 'rev_cagr_3y', 'rev_yoy_q', 'roce', 'de', 'cfo_pat_cum'].filter(k => M[k] && M[k].value != null)
  const g = s.guidance

  return (
    <article className="report">
      <header className="report-head">
        <p className="muted small">{r.symbol}, {r.basis} figures{r.in_portfolio ? ', in your portfolio' : ''}</p>
        <h2 className="h1">{r.name}</h2>
        {s.headline && <p className="headline">{s.headline}</p>}
        <SnapshotNote s={r.snapshot} />
        <button className="btn-ghost" onClick={() => askCopilot({ symbol: r.symbol, label: r.name }, `What are the most important things to know about ${r.name} from this research?`)}>Ask Copilot about {r.symbol}</button>
      </header>

      <nav className="section-nav" aria-label="Report sections">
        {SECTIONS.map(([id, label]) => <button key={id} type="button" onClick={() => jump(`r-${id}`)}>{label}</button>)}
      </nav>

      {r.limitations.length > 0 && (
        <details className="limits">
          <summary>{r.limitations.length} limitation{r.limitations.length > 1 ? 's' : ''} in this report</summary>
          <ul>{r.limitations.map((l, k) => <li key={k}>{l}</li>)}</ul>
        </details>
      )}

      <section id="r-snapshot" className="block">
        <h3 className="h2">Snapshot</h3>
        {s.business.status === 'ok' && s.business.what_it_does ? (
          <>
            <ul className="claims"><ClaimLine c={s.business.what_it_does} report={r} onCite={setCite} /></ul>
            {s.business.segments && s.business.segments.length > 0 && (
              <ul className="segments">
                {s.business.segments.map(sg => (
                  <li key={sg.name}>
                    <span>{sg.name}</span>
                    {sg.share_of_revenue_pct != null && <span className="seg-bar" style={{ width: `${Math.min(100, sg.share_of_revenue_pct)}%` }} aria-hidden />}
                    <span className="num">{sg.share_of_revenue_pct != null ? plainPct(sg.share_of_revenue_pct, 0) : ''}</span>
                  </li>
                ))}
              </ul>
            )}
            <ul className="claims">{s.business.other_points?.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}</ul>
          </>
        ) : (
          <p className="note">
            {s.business.status === 'llm_disabled' ? 'Business description needs an AI model (not configured). Relevant annual-report passages: ' : `Business description unavailable${s.business.detail ? ` (${s.business.detail})` : ''}. `}
            {s.business.passages?.map(id => <button key={id} className="cite" onClick={() => setCite(id)}>{r.evidence[id] ? `${r.evidence[id].source} p.${r.evidence[id].page}` : id}</button>)}
          </p>
        )}
        <dl className="kpis">
          {keyMetrics.map(k => (
            <div key={k} className="kpi"><dt>{M[k].label}</dt><dd className={M[k].unit === '%' && /growth|CAGR|YoY/.test(M[k].label) ? sign(M[k].value) : ''}>{metricValue(M[k].value, M[k].unit)}</dd><span className="muted small">{M[k].period}</span></div>
          ))}
        </dl>
      </section>

      <section id="r-promises" className="block">
        <h3 className="h2">Promised vs delivered</h3>
        <p className="muted small">{g.method}</p>
        {g.rows.length > 0 && (
          <>
            <Scorecard tally={g.tally} />
            <ul className="promises">{g.rows.map((row, k) => <Promise key={k} row={row} r={r} onCite={setCite} />)}</ul>
          </>
        )}
        {g.status === 'candidates_only' && (
          <>
            <p className="note">Without an AI model FINN can’t normalise guidance into checkable targets. These sentences look like guidance; they are not evaluated.</p>
            <ul className="quotes">{g.candidates.map((c, k) => <li key={k}><q>{c.text}</q> <span className="muted small">{c.call_date} call</span> <button className="cite" onClick={() => setCite(c.evidence)}>source</button></li>)}</ul>
          </>
        )}
        {g.status === 'none' && <p className="note">No guidance found in the available transcripts.</p>}
        {s.narrative?.claims.length ? <ul className="claims">{s.narrative.claims.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}</ul> : null}
      </section>

      <section id="r-trajectory" className="block">
        <h3 className="h2">Trajectory</h3>
        <ul className="claims">{s.trajectory.claims.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}</ul>
        {r.tables.trajectory.length > 1 && (
          <BarLine data={r.tables.trajectory.slice(-6) as unknown as Record<string, number | string | null>[]} barKey="revenue" lineKey="opm" barLabel="Revenue (₹ cr)" lineLabel={r.is_bank ? 'Financing margin' : 'Operating margin'}
            fmtBar={v => cr(v)} fmtLine={v => plainPct(v)} />
        )}
        <details className="evidence"><summary>Year-by-year table</summary><TrajectoryTable r={r} /></details>
        {r.tables.quarters.length > 0 && (
          <>
            <h4 className="h3 chart-h">Quarterly revenue growth, year on year</h4>
            <BarLine data={r.tables.quarters.slice(-6) as unknown as Record<string, number | string | null>[]} barKey="revenue_yoy" lineKey="opm" barLabel="Revenue YoY" lineLabel="Margin" fmtBar={v => pct(v)} fmtLine={v => plainPct(v)} height={130} />
            <QuarterTable r={r} />
          </>
        )}
      </section>

      <section id="r-balance" className="block">
        <h3 className="h2">Balance sheet</h3>
        <ul className="claims">{s.balance_sheet.claims.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}</ul>
        {r.tables.balance_sheet.length > 0 && (
          <div className="table-wrap"><table className="num-table wide">
            <thead><tr><th></th>{r.tables.balance_sheet.map(b => <th key={b.period}>{b.period}</th>)}</tr></thead>
            <tbody>
              <tr><th scope="row">Equity</th>{r.tables.balance_sheet.map(b => <td key={b.period}>{cr(b.equity)}</td>)}</tr>
              <tr><th scope="row">Borrowings</th>{r.tables.balance_sheet.map(b => <td key={b.period}>{cr(b.borrowings)}</td>)}</tr>
              {!r.is_bank && <tr><th scope="row">Debt / equity</th>{r.tables.balance_sheet.map(b => <td key={b.period}>{b.de == null ? '—' : `${b.de.toFixed(2)}×`}</td>)}</tr>}
              {r.tables.working_capital.map(w => (
                <tr key={w.metric}><th scope="row">{w.metric}</th>{r.tables.balance_sheet.map(b => { const v = w.values.find(x => x.period === b.period); return <td key={b.period}>{v?.value == null ? '—' : w.metric === 'ROCE' ? `${v.value}%` : Math.round(v.value)}</td> })}</tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>

      <section id="r-cash" className="block">
        <h3 className="h2">Do profits turn into cash?</h3>
        <ul className="claims">{s.cash_quality.claims.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}</ul>
        {r.tables.cash.length > 1 && (
          <BarLine data={r.tables.cash as unknown as Record<string, number | string | null>[]} barKey="cfo" lineKey="pat" barLabel="Operating cash (₹ cr)" lineLabel="PAT (₹ cr)" fmtBar={v => cr(v)} fmtLine={v => cr(v)} height={130} />
        )}
        {r.tables.cash.length > 0 && (
          <div className="table-wrap"><table className="num-table wide">
            <thead><tr><th></th>{r.tables.cash.map(c => <th key={c.period}>{c.period}</th>)}</tr></thead>
            <tbody>
              <tr><th scope="row">Operating cash</th>{r.tables.cash.map(c => <td key={c.period}>{cr(c.cfo)}</td>)}</tr>
              <tr><th scope="row">PAT</th>{r.tables.cash.map(c => <td key={c.period}>{cr(c.pat)}</td>)}</tr>
              <tr><th scope="row">Cash / profit</th>{r.tables.cash.map(c => <td key={c.period} className={c.conversion == null ? '' : c.conversion < 0.7 ? 'neg' : c.conversion >= 0.9 ? 'pos' : ''}>{c.conversion == null ? '—' : `${c.conversion.toFixed(2)}×`}</td>)}</tr>
              <tr><th scope="row">Capex</th>{r.tables.cash.map(c => <td key={c.period}>{cr(c.capex)}</td>)}</tr>
              <tr><th scope="row">Free cash flow</th>{r.tables.cash.map(c => <td key={c.period} className={sign(c.fcf)}>{cr(c.fcf)}</td>)}</tr>
            </tbody>
          </table></div>
        )}
      </section>

      <section id="r-case" className="block">
        <h3 className="h2">Bull and bear</h3>
        <div className="case">
          <div><h4 className="h3 pos">For</h4><ul className="claims">{s.bull_bear.bull.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}{!s.bull_bear.bull.length && <li className="muted">Nothing in the evidence clearly supports a bull point.</li>}</ul></div>
          <div><h4 className="h3 neg">Against</h4><ul className="claims">{s.bull_bear.bear.map((c, k) => <ClaimLine key={k} c={c} report={r} onCite={setCite} />)}{!s.bull_bear.bear.length && <li className="muted">No rule-based risk flags triggered. That is not the same as no risk.</li>}</ul></div>
        </div>
        {s.open_questions && s.open_questions.length > 0 && (
          <><h4 className="h3">Ask management next</h4><ul className="plain">{s.open_questions.map((q, k) => <li key={k}>{q}</li>)}</ul></>
        )}
        <p className="muted small">Not a recommendation. {s.bull_bear.origin === 'rules' ? 'Points come from fixed rules on the reported numbers.' : 'Every point must cite its source; unverified ones are marked.'}</p>
      </section>

      <section id="r-sources" className="block">
        <h3 className="h2">Sources</h3>
        <ul className="sources">
          {r.sources.map(src => (
            <li key={src.id}>
              <span className="src-id">{src.id}</span>
              <span>
                <a href={src.url} target="_blank" rel="noreferrer noopener">{src.title}</a>
                {src.publisher && <span className="muted small"> {src.publisher}</span>}
                <span className={`muted small src-${src.status}`}> {src.status === 'ok' ? (src.pages ? `${src.pages} pages read` : 'retrieved') : `not read: ${src.detail}`}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="muted small">
          {r.verification.llm_claims > 0 ? `${r.verification.verified} of ${r.verification.llm_claims} AI-written claims verified against their citations. ` : ''}
          {r.llm.enabled ? `${r.llm.calls_used} of ${r.llm.calls_budget} model calls used.` : 'No AI model configured.'} Generated {new Date(r.generated_at).toLocaleString('en-IN')} in {r.elapsed_s}s.{' '}
          <button className="link" onClick={rerun}>Refresh</button>
        </p>
      </section>

      {cite && <CiteSheet id={cite} r={r} onClose={() => setCite(null)} />}
    </article>
  )
}

function Scorecard({ tally }: { tally: Record<string, number> }) {
  const order = ['missed', 'met', 'exceeded', 'pending', 'cannot_evaluate', 'qualitative'] as const
  const total = order.reduce((n, k) => n + (tally[k] || 0), 0)
  const judged = (tally.met || 0) + (tally.exceeded || 0) + (tally.missed || 0)
  return (
    <div className="scorecard">
      <p className="score-big">{judged ? <><b>{(tally.met || 0) + (tally.exceeded || 0)}</b> of {judged} measurable promises kept</> : 'No measurable promise could be checked yet'}</p>
      <div className="score-bar" role="img" aria-label={order.filter(k => tally[k]).map(k => `${tally[k]} ${VERDICT[k]}`).join(', ')}>
        {order.filter(k => tally[k]).map(k => <span key={k} className={`seg v-${k}`} style={{ flexGrow: tally[k] }} title={`${tally[k]} ${VERDICT[k]}`} />)}
      </div>
      <ul className="legend">{order.filter(k => tally[k]).map(k => <li key={k}><span className={`swatch v-${k}`} />{VERDICT[k]}<b>{tally[k]}</b></li>)}</ul>
      <p className="muted small">{total} statements from the last four calls.</p>
    </div>
  )
}

function Promise({ row, r, onCite }: { row: GuidanceRow; r: Report; onCite: (id: string) => void }) {
  const evId = Object.values(r.evidence).find(e => e.source === row.source && e.page === row.page && e.text.replace(/\s+/g, ' ').includes(row.quote.slice(0, 30)))?.id
  const target = row.target_low == null ? '' : row.target_low === row.target_high || row.target_high == null ? `${row.comparator === 'at_least' ? '≥ ' : row.comparator === 'at_most' ? '≤ ' : '~'}${row.target_low}%` : `${row.target_low}–${row.target_high}%`
  return (
    <li className={`promise v-${row.verdict}`}>
      <div className="promise-head">
        <span className="verdict">{VERDICT[row.verdict]}</span>
        <span className="muted small">{row.call_date} call, about {row.period || 'unspecified period'}</span>
      </div>
      <q>{row.quote}</q>
      <div className="promise-foot">
        {target && <span>Said <b>{target}</b></span>}
        {row.actual != null && <span>Reported <b>{row.actual.toFixed(1)}%</b> ({row.actual_period})</span>}
        <span className="muted small">{row.reason}</span>
        {evId && <button className="cite" onClick={() => onCite(evId)}>{row.source} p.{row.page}</button>}
      </div>
    </li>
  )
}

function TrajectoryTable({ r }: { r: Report }) {
  const t = r.tables.trajectory.slice(-6)
  if (!t.length) return null
  return (
    <div className="table-wrap"><table className="num-table wide">
      <thead><tr><th></th>{t.map(y => <th key={y.period}>{y.period}</th>)}</tr></thead>
      <tbody>
        <tr><th scope="row">Revenue</th>{t.map(y => <td key={y.period}>{cr(y.revenue)}</td>)}</tr>
        <tr><th scope="row">Growth</th>{t.map(y => <td key={y.period} className={sign(y.revenue_growth)}>{pct(y.revenue_growth)}</td>)}</tr>
        <tr><th scope="row">{r.is_bank ? 'Financing margin' : 'Operating margin'}</th>{t.map(y => <td key={y.period}>{plainPct(y.opm)}</td>)}</tr>
        <tr><th scope="row">PAT</th>{t.map(y => <td key={y.period}>{cr(y.pat)}</td>)}</tr>
      </tbody>
    </table></div>
  )
}

function QuarterTable({ r }: { r: Report }) {
  const q = r.tables.quarters.slice(-5)
  return (
    <details className="evidence">
      <summary>Last {q.length} quarters</summary>
      <div className="table-wrap"><table className="num-table wide">
        <thead><tr><th></th>{q.map(x => <th key={x.period}>{x.period}</th>)}</tr></thead>
        <tbody>
          <tr><th scope="row">Revenue</th>{q.map(x => <td key={x.period}>{cr(x.revenue)}</td>)}</tr>
          <tr><th scope="row">YoY</th>{q.map(x => <td key={x.period} className={sign(x.revenue_yoy)}>{pct(x.revenue_yoy)}</td>)}</tr>
          <tr><th scope="row">Margin</th>{q.map(x => <td key={x.period}>{plainPct(x.opm)}</td>)}</tr>
          <tr><th scope="row">PAT YoY</th>{q.map(x => <td key={x.period} className={sign(x.pat_yoy)}>{pct(x.pat_yoy)}</td>)}</tr>
        </tbody>
      </table></div>
    </details>
  )
}

function CiteSheet({ id, r, onClose }: { id: string; r: Report; onClose: () => void }) {
  if (id.startsWith('M:')) {
    const m = r.metrics[id.slice(2)]
    const src = r.sources.find(s => s.id === m?.source)
    return (
      <Sheet onClose={onClose} label="Evidence">
        <h3 className="h2">{m ? m.label : id}</h3>
        {m ? <p className="big-num">{metricValue(m.value, m.unit)}</p> : <p className="note">This figure isn’t in the report’s metric set.</p>}
        <p className="muted small">Computed by FINN from {src ? <a href={src.url} target="_blank" rel="noreferrer noopener">{src.title}</a> : 'reported financials'} ({m?.period}). {m?.note}</p>
      </Sheet>
    )
  }
  const e = r.evidence[id]
  const src = e && r.sources.find(s => s.id === e.source)
  return (
    <Sheet onClose={onClose} label="Evidence">
      <h3 className="h2">{src?.title ?? id}{e && <span className="muted small"> page {e.page}</span>}</h3>
      {e ? <blockquote className="passage">{e.text}</blockquote> : <p className="note">This citation doesn’t match any retrieved passage, so the claim is marked unverified.</p>}
      {src && <a className="btn" href={src.url} target="_blank" rel="noreferrer noopener">Open document</a>}
    </Sheet>
  )
}
