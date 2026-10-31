import { useEffect, useRef, type ReactNode } from 'react'
import type React from 'react'

/** In-page jump that doesn't touch location.hash (the hash is the router). */
export const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
import type { Claim, Evidence, Report, SnapshotLabel, Tier } from './api'

export function Spark({ data, up }: { data: number[]; up?: boolean }) {
  if (data.length < 2) return null
  const min = Math.min(...data), max = Math.max(...data)
  const w = 64, h = 20
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / (max - min || 1)) * h}`).join(' ')
  return (
    <svg className={`spark ${up ? 'pos' : 'neg'}`} width={w} height={h} viewBox={`0 -1 ${w} ${h + 2}`} aria-hidden>
      <polyline points={pts} fill="none" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

/** Left rail: weight encodes the priority score (0-100). The one decorative device in FINN, and it carries data. */
export function Rail({ score, tier }: { score: number; tier: Tier }) {
  return <span className={`rail rail-${tier}`} style={{ width: 2 + Math.round(score / 20) }} aria-hidden />
}

export function Sheet({ onClose, children, label }: { onClose: () => void; children: ReactNode; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', k); document.body.style.overflow = ''; prev?.focus() }
  }, [onClose])
  return (
    <div className="scrim" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} ref={ref} onClick={e => e.stopPropagation()}>
        <div className="sheet-bar"><button className="sheet-close" onClick={onClose}>Close</button></div>
        {children}
      </div>
    </div>
  )
}

export function Loading({ label }: { label: string }) {
  return <div className="loading" role="status"><span className="pulse" aria-hidden />{label}</div>
}

export function ErrorNote({ msg, retry }: { msg: string; retry?: () => void }) {
  return (
    <div className="error" role="alert">
      <p>{msg}</p>
      {retry && <button className="btn-ghost" onClick={retry}>Try again</button>}
    </div>
  )
}

/** A claim with its evidence chips. Tapping a chip reveals the cited passage or metric inline. */
export function ClaimLine({ c, report, onCite }: { c: Claim; report: Report; onCite: (id: string) => void }) {
  return (
    <li className={`claim kind-${c.kind}${c.verified === false ? ' unverified' : ''}`}>
      <span className="claim-text">{c.text}</span>
      {c.kind === 'management' && <span className="tag tag-mgmt">Management says</span>}
      {c.kind === 'interpretation' && c.origin === 'llm' && <span className="tag">Analysis</span>}
      {c.verified === false && <span className="tag tag-warn" title={(c.issues || []).join('; ')}>Unverified</span>}
      <span className="cites">
        {c.evidence.map(id => <CiteChip key={id} id={id} report={report} onCite={onCite} />)}
      </span>
    </li>
  )
}

export function CiteChip({ id, report, onCite }: { id: string; report: Report; onCite: (id: string) => void }) {
  const ev: Evidence | undefined = report.evidence[id]
  const m = id.startsWith('M:') ? report.metrics[id.slice(2)] : undefined
  const label = id.startsWith('M:') ? (m ? m.label.replace(/\s*\(.*\)$/, '') : 'figure') : ev ? `${ev.source} p.${ev.page}` : id
  return <button className="cite" onClick={() => onCite(id)} aria-label={`Show evidence ${label}`}>{label}</button>
}

export function SnapshotNote({ s }: { s?: SnapshotLabel | null }) {
  if (!s) return null
  const when = new Date(s.captured_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })
  return (
    <p className="snapshot-note" role="note">
      Captured {when} IST from {s.sources.join(', ') || 'live sources'}. This server is blocked by the exchanges, so it shows the latest real snapshot.
    </p>
  )
}

export function Skeleton({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`skel-group ${className}`} aria-hidden>
      {Array.from({ length: lines }, (_, i) => <span key={i} className="skel" style={{ width: `${92 - (i % 3) * 18}%` }} />)}
    </div>
  )
}

/** Horizontal stacked share bar + legend (allocation). Tooltips via <title>; values also listed as text. */
const PALETTE = ['#3a3fd1', '#7f84e6', '#147a57', '#9a6a08', '#b42318', '#5e687a', '#2f8fb3', '#a24fb0', '#c2a000', '#8a93a3']
export function ShareBar({ items, label }: { items: { name: string; pct: number }[]; label: string }) {
  return (
    <figure className="sharebar" aria-label={label}>
      <svg viewBox="0 0 100 6" preserveAspectRatio="none" role="img" aria-hidden>
        {items.reduce<{ x: number; els: React.ReactElement[] }>((acc, it, i) => {
          acc.els.push(<rect key={it.name} x={acc.x} y={0} width={Math.max(it.pct, 0.4)} height={6} fill={PALETTE[i % PALETTE.length]}><title>{`${it.name}: ${it.pct.toFixed(1)}%`}</title></rect>)
          acc.x += it.pct
          return acc
        }, { x: 0, els: [] }).els}
      </svg>
      <figcaption>
        <ul className="legend">
          {items.map((it, i) => <li key={it.name}><span className="swatch" style={{ background: PALETTE[i % PALETTE.length] }} />{it.name}<b>{it.pct.toFixed(1)}%</b></li>)}
        </ul>
      </figcaption>
    </figure>
  )
}

/** Simple labelled bar chart with optional second series as a line (e.g. revenue bars + margin line). */
export function BarLine({ data, barKey, lineKey, barLabel, lineLabel, fmtBar, fmtLine, height = 150 }: {
  data: Record<string, number | string | null>[]; barKey: string; lineKey?: string; barLabel: string; lineLabel?: string
  fmtBar: (v: number) => string; fmtLine?: (v: number) => string; height?: number
}) {
  const W = 320, H = height, pad = { l: 6, r: 6, t: 18, b: 22 }
  const bars = data.map(d => (typeof d[barKey] === 'number' ? (d[barKey] as number) : null))
  const lines = lineKey ? data.map(d => (typeof d[lineKey] === 'number' ? (d[lineKey] as number) : null)) : []
  const bmax = Math.max(...bars.map(v => Math.abs(v ?? 0)), 1)
  const anyNeg = bars.some(v => (v ?? 0) < 0)
  const zero = anyNeg ? pad.t + (H - pad.t - pad.b) / 2 : H - pad.b
  const span = anyNeg ? (H - pad.t - pad.b) / 2 : H - pad.t - pad.b
  const bw = (W - pad.l - pad.r) / data.length
  const lv = lines.filter((v): v is number => v != null)
  const lmin = Math.min(...lv), lmax = Math.max(...lv)
  const ly = (v: number) => pad.t + 4 + (1 - (v - lmin) / (lmax - lmin || 1)) * (H - pad.t - pad.b - 14)
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${barLabel}${lineLabel ? ` and ${lineLabel}` : ''} by period`}>
        <line x1={pad.l} x2={W - pad.r} y1={zero} y2={zero} className="axis" />
        {data.map((d, i) => {
          const v = bars[i]
          if (v == null) return null
          const h = Math.abs(v) / bmax * span
          const x = pad.l + i * bw + bw * 0.18
          return (
            <g key={i}>
              <rect x={x} width={bw * 0.64} y={v >= 0 ? zero - h : zero} height={Math.max(h, 1)} rx={2} className={v >= 0 ? 'bar' : 'bar neg'}>
                <title>{`${d.period}: ${barLabel} ${fmtBar(v)}${lineKey && lines[i] != null ? `, ${lineLabel} ${fmtLine!(lines[i]!)}` : ''}`}</title>
              </rect>
              <text x={x + bw * 0.32} y={H - 7} className="tick">{String(d.period).replace(/^Q(\d) FY/, 'Q$1 ')}</text>
            </g>
          )
        })}
        {lineKey && lv.length > 1 && (
          <polyline className="line" points={lines.map((v, i) => (v == null ? '' : `${pad.l + i * bw + bw / 2},${ly(v)}`)).filter(Boolean).join(' ')} />
        )}
        {lineKey && lines.map((v, i) => v == null ? null : <circle key={i} cx={pad.l + i * bw + bw / 2} cy={ly(v)} r={2.6} className="dot"><title>{`${data[i].period}: ${lineLabel} ${fmtLine!(v)}`}</title></circle>)}
      </svg>
      <figcaption className="muted small"><span className="key-bar" /> {barLabel}{lineKey && <> <span className="key-line" /> {lineLabel}</>}</figcaption>
    </figure>
  )
}
