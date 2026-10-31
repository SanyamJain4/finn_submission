import { useEffect, useRef, useState } from 'react'
import { api, type CopilotAnswer, type CopilotContext, type CopilotSource, type HoldingInput } from '../api'
import { KEYS, takePending, useStored } from '../store'
import { Sheet } from '../ui'

interface Turn { q: string; ctx: CopilotContext | null; a?: CopilotAnswer; err?: string; at: string }

const STARTERS = [
  'What needs my attention today?',
  'How is my portfolio doing?',
  'Summarise Dixon’s latest results',
  'Compare Reliance and TCS on growth and margins',
]

export default function Copilot() {
  const [chat, setChat] = useStored<Turn[]>(KEYS.chat, [])
  const [holdings] = useStored<HoldingInput[]>(KEYS.holdings, [])
  const [ctx, setCtx] = useState<CopilotContext | null>(null)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [src, setSrc] = useState<CopilotSource | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const turns = chat || []

  useEffect(() => {
    const p = takePending()
    if (p) {
      setCtx(p.ctx)
      if (p.question) ask(p.question, p.ctx)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [turns.length, busy])

  function ask(text: string, context: CopilotContext | null = ctx) {
    const question = text.trim()
    if (!question || busy) return
    setQ(''); setBusy(true)
    const base = [...(chat || [])]
    const turn: Turn = { q: question, ctx: context, at: new Date().toISOString() }
    setChat([...base, turn])
    const history = base.slice(-3).flatMap(t => [{ role: 'user', text: t.q }, { role: 'assistant', text: (t.a?.blocks || []).map(b => b.text).join(' ') }])
    api.copilot({ question, symbol: context?.symbol, uid: context?.uid, page: context?.page, holdings: holdings || [], history })
      .then(a => setChat([...base, { ...turn, a }]))
      .catch(e => setChat([...base, { ...turn, err: e.message }]))
      .finally(() => setBusy(false))
  }

  return (
    <section className="view copilot" aria-labelledby="cp-h">
      <div className="view-head">
        <h1 id="cp-h" className="h1">Copilot</h1>
        {turns.length > 0 && <button className="btn-ghost" onClick={() => { setChat([]); setCtx(null) }}>New conversation</button>}
      </div>
      <p className="muted small lede-small">Answers come only from data FINN has fetched: prices, exchange filings, research reports and your holdings. Every claim is cited, and anything FINN can’t support is flagged.</p>

      {turns.length === 0 && (
        <div className="starters">
          {STARTERS.map(s => <button key={s} className="starter" onClick={() => ask(s)}>{s}</button>)}
        </div>
      )}

      <ol className="thread" aria-live="polite">
        {turns.map((t, i) => (
          <li key={i} className="turn">
            <p className="q">{t.ctx?.label && <span className="ctx-tag">{t.ctx.label}</span>}{t.q}</p>
            {t.err && <p className="error small">{t.err}</p>}
            {t.a && <AnswerView a={t.a} onSource={setSrc} onFollow={f => ask(f)} />}
            {!t.a && !t.err && busy && i === turns.length - 1 && <p className="thinking"><span className="pulse" aria-hidden />Reading FINN’s data…</p>}
          </li>
        ))}
      </ol>
      <div ref={end} />

      <form className="ask-bar" onSubmit={e => { e.preventDefault(); ask(q) }}>
        {ctx && (
          <span className="ctx-chip">About: {ctx.label || ctx.symbol || 'this page'} <button type="button" aria-label="Clear context" onClick={() => setCtx(null)}>×</button></span>
        )}
        <div className="ask-row">
          <label htmlFor="cq" className="sr-only">Ask Copilot</label>
          <textarea id="cq" rows={1} value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about a stock, a filing or your holdings"
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(q) } }} maxLength={600} />
          <button className="btn" type="submit" disabled={!q.trim() || busy}>Ask</button>
        </div>
      </form>
      {src && <SourceSheet s={src} onClose={() => setSrc(null)} />}
    </section>
  )
}

function AnswerView({ a, onSource, onFollow }: { a: CopilotAnswer; onSource: (s: CopilotSource) => void; onFollow: (q: string) => void }) {
  const num = (id: string) => a.sources.findIndex(s => s.id === id) + 1
  return (
    <div className="answer">
      {a.note && <p className="note">{a.note}</p>}
      {a.blocks.map((b, i) => (
        <p key={i} className={`ans-block${b.verified ? '' : ' unverified'}`}>
          {b.text}{' '}
          {b.cites.map(c => <button key={c} className="cite" onClick={() => onSource(a.sources.find(s => s.id === c)!)}>{num(c)}</button>)}
          {!b.verified && <span className="tag tag-warn" title={(b.issues || []).join('; ')}>Unverified</span>}
        </p>
      ))}
      {a.missing.length > 0 && <p className="muted small">Not in FINN’s data: {a.missing.join('; ')}.</p>}
      {a.actions.length > 0 && (
        <p className="small">{a.actions.map(x => <a key={x.symbol} className="btn-ghost" href={`#/research/${x.symbol}`}>Run research on {x.symbol} for deeper answers</a>)}</p>
      )}
      {a.follow_ups.length > 0 && <div className="follow">{a.follow_ups.map(f => <button key={f} className="chip" onClick={() => onFollow(f)}>{f}</button>)}</div>}
      {a.sources.length > 0 && (
        <details className="evidence">
          <summary>{a.sources.length} source{a.sources.length > 1 ? 's' : ''} considered</summary>
          <ol className="src-list">{a.sources.map(s => <li key={s.id}><button className="link" onClick={() => onSource(s)}>{s.title}</button></li>)}</ol>
        </details>
      )}
    </div>
  )
}

function SourceSheet({ s, onClose }: { s: CopilotSource; onClose: () => void }) {
  const internal = s.url?.startsWith('#')
  return (
    <Sheet onClose={onClose} label="Source">
      <h2 className="h2">{s.title}</h2>
      <blockquote className="passage">{s.text}</blockquote>
      {s.url && (internal ? <a className="btn" href={s.url} onClick={onClose}>Open in FINN</a> : <a className="btn" href={s.url} target="_blank" rel="noreferrer noopener">Open original filing</a>)}
    </Sheet>
  )
}
