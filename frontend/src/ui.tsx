import { useEffect, useRef, type ReactNode } from 'react'

/** In-page jump that doesn't touch location.hash (the hash is the router). */
export const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
import type { Claim, Evidence, Report, Tier } from './api'

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
