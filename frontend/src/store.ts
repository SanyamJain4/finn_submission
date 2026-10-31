// Per-browser state. Holdings and alert states stay on this device: the server only values them.
import { useEffect, useState } from 'react'
import type { CopilotContext, HoldingInput } from './api'

const mem: Record<string, string> = {}
function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v == null ? fallback : (JSON.parse(v) as T)
  } catch {
    return mem[key] ? (JSON.parse(mem[key]) as T) : fallback
  }
}
function write(key: string, value: unknown) {
  const s = JSON.stringify(value)
  try { localStorage.setItem(key, s) } catch { mem[key] = s }
  window.dispatchEvent(new CustomEvent('finn-store', { detail: key }))
}

export function useStored<T>(key: string, fallback: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => read(key, fallback))
  useEffect(() => {
    const on = (e: Event) => { if ((e as CustomEvent).detail === key) setV(read(key, fallback)) }
    window.addEventListener('finn-store', on)
    return () => window.removeEventListener('finn-store', on)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return [v, (nv: T) => write(key, nv)]
}

export const KEYS = { holdings: 'finn.holdings', alertState: 'finn.alerts', profile: 'finn.profile', chat: 'finn.chat' }
export type AlertState = Record<string, { read?: boolean; ack?: boolean }>
export const getHoldings = () => read<HoldingInput[]>(KEYS.holdings, [])
export const clearAll = () => Object.values(KEYS).forEach(k => write(k, null))

// Copilot hand-off: a page asks a question "about this", Copilot picks it up.
let pending: { ctx: CopilotContext; question?: string } | null = null
export function askCopilot(ctx: CopilotContext, question?: string) {
  pending = { ctx, question }
  window.location.hash = '/copilot'
}
export function takePending() { const p = pending; pending = null; return p }
