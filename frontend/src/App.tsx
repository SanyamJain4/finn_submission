import { useEffect, useState } from 'react'
import { api, type FeedItem } from './api'
import Alerts from './views/Alerts'
import Filing from './views/Filing'
import Research from './views/Research'
import Settings from './views/Settings'
import Today from './views/Today'

type Tab = 'today' | 'alerts' | 'research' | 'settings'

function parseHash(): { tab: Tab; sym: string | null } {
  const [, tab, sym] = window.location.hash.split('/')
  const t = (['today', 'alerts', 'research', 'settings'] as Tab[]).includes(tab as Tab) ? (tab as Tab) : 'today'
  return { tab: t, sym: t === 'research' && sym ? decodeURIComponent(sym).toUpperCase() : null }
}

export default function App() {
  const [{ tab, sym }, setRoute] = useState(parseHash)
  const [filing, setFiling] = useState<FeedItem | null>(null)
  const [fixture, setFixture] = useState(false)

  useEffect(() => {
    const on = () => setRoute(parseHash())
    window.addEventListener('hashchange', on)
    api.status().then(s => setFixture(s.fixture_mode)).catch(() => {})
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => { window.scrollTo(0, 0) }, [tab, sym])

  const go = (t: Tab, s?: string | null) => { window.location.hash = `/${t}${s ? `/${encodeURIComponent(s)}` : ''}` }
  const research = (s: string) => { setFiling(null); go('research', s) }
  const now = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' })

  return (
    <div className="app">
      {fixture && <div className="fixture-banner" role="note">Synthetic fixture data, not real filings. Offline development mode.</div>}
      <header className="top">
        <a href="#/today" className="wordmark" aria-label="FINN home"><span className="mark" aria-hidden />FINN</a>
        <span className="muted small">{now}</span>
      </header>
      <main id="main">
        {tab === 'today' && <Today openFiling={setFiling} openCompany={research} />}
        {tab === 'alerts' && <Alerts openFiling={setFiling} goSettings={() => go('settings')} />}
        {tab === 'research' && <Research symbol={sym} setSymbol={s => go('research', s)} />}
        {tab === 'settings' && <Settings />}
      </main>
      <nav className="tabs" aria-label="Main">
        {([['today', 'Today'], ['alerts', 'Alerts'], ['research', 'Research'], ['settings', 'Settings']] as [Tab, string][]).map(([t, l]) => (
          <a key={t} href={`#/${t}`} className={tab === t ? 'on' : ''} aria-current={tab === t ? 'page' : undefined}>
            <TabIcon t={t} />{l}
          </a>
        ))}
      </nav>
      {filing && <Filing item={filing} onClose={() => setFiling(null)} research={research} />}
    </div>
  )
}

function TabIcon({ t }: { t: Tab }) {
  const p = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, 'aria-hidden': true }
  if (t === 'today') return <svg {...p}><path d="M5 5v14" strokeWidth="3" /><path d="M10 7h9M10 12h6M10 17h8" /></svg>
  if (t === 'alerts') return <svg {...p}><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 21h4" /></svg>
  if (t === 'research') return <svg {...p}><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.5-4.5" /></svg>
  return <svg {...p}><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></svg>
}
