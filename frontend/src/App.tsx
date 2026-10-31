import { useEffect, useState } from 'react'
import { api, type FeedItem } from './api'
import { alertItems } from './alerts'
import { KEYS, useStored, type AlertState } from './store'
import Account from './views/Account'
import Alerts from './views/Alerts'
import Copilot from './views/Copilot'
import Filing from './views/Filing'
import Portfolio from './views/Portfolio'
import Research from './views/Research'
import Today from './views/Today'

type Tab = 'today' | 'alerts' | 'research' | 'copilot' | 'portfolio' | 'account'
const TABS: [Tab, string][] = [['today', 'Today'], ['alerts', 'Alerts'], ['research', 'Research'], ['copilot', 'Copilot'], ['portfolio', 'Portfolio']]

function parseHash(): { tab: Tab; sym: string | null } {
  const [, tab, sym] = window.location.hash.split('/')
  const ok: Tab[] = ['today', 'alerts', 'research', 'copilot', 'portfolio', 'account']
  const t = ok.includes(tab as Tab) ? (tab as Tab) : tab === 'settings' ? 'account' : 'today'
  return { tab: t, sym: t === 'research' && sym ? decodeURIComponent(sym).toUpperCase() : null }
}

export default function App() {
  const [{ tab, sym }, setRoute] = useState(parseHash)
  const [filing, setFiling] = useState<FeedItem | null>(null)
  const [fixture, setFixture] = useState(false)
  const [alertIds, setAlertIds] = useState<string[]>([])
  const [state] = useStored<AlertState>(KEYS.alertState, {})
  const [profile] = useStored<{ name?: string }>(KEYS.profile, {})

  useEffect(() => {
    const on = () => setRoute(parseHash())
    window.addEventListener('hashchange', on)
    api.status().then(s => setFixture(s.fixture_mode)).catch(() => {})
    api.alerts().then(a => setAlertIds(alertItems(a).map(x => x.id))).catch(() => {})
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => { window.scrollTo(0, 0) }, [tab, sym])

  const go = (t: Tab, s?: string | null) => { window.location.hash = `/${t}${s ? `/${encodeURIComponent(s)}` : ''}` }
  const research = (s: string) => { setFiling(null); go('research', s) }
  const unread = alertIds.filter(id => !(state || {})[id]?.read).length
  const initials = (profile?.name || '').split(/\s+/).filter(Boolean).map(w => w[0]).join('').slice(0, 2).toUpperCase()
  const now = new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' })

  return (
    <div className="app">
      {fixture && <div className="fixture-banner" role="note">Synthetic fixture data, not real filings. Offline development mode.</div>}
      <header className="top">
        <a href="#/today" className="wordmark" aria-label="FINN home"><span className="mark" aria-hidden />FINN</a>
        <nav className="tabs" aria-label="Main">
          {TABS.map(([t, l]) => (
            <a key={t} href={`#/${t}`} className={tab === t ? 'on' : ''} aria-current={tab === t ? 'page' : undefined}>
              <span className="tab-icon"><TabIcon t={t} />{t === 'alerts' && unread > 0 && <span className="badge" aria-label={`${unread} unread`}>{unread > 9 ? '9+' : unread}</span>}</span>
              {l}
            </a>
          ))}
        </nav>
        <div className="top-right">
          <span className="muted small top-date">{now}</span>
          <a href="#/account" className={`avatar${tab === 'account' ? ' on' : ''}`} aria-label="Account and settings">
            {initials || <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></svg>}
          </a>
        </div>
      </header>
      <main id="main" className={`main-${tab}`}>
        {tab === 'today' && <Today openFiling={setFiling} openCompany={research} />}
        {tab === 'alerts' && <Alerts openFiling={setFiling} />}
        {tab === 'research' && <Research symbol={sym} setSymbol={s => go('research', s)} />}
        {tab === 'copilot' && <Copilot />}
        {tab === 'portfolio' && <Portfolio research={research} />}
        {tab === 'account' && <Account />}
      </main>
      {filing && <Filing item={filing} onClose={() => setFiling(null)} research={research} />}
    </div>
  )
}

function TabIcon({ t }: { t: Tab }) {
  const p = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
  if (t === 'today') return <svg {...p}><path d="M5 5v14" strokeWidth="3" /><path d="M10 7h9M10 12h6M10 17h8" /></svg>
  if (t === 'alerts') return <svg {...p}><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 21h4" /></svg>
  if (t === 'research') return <svg {...p}><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.5-4.5" /></svg>
  if (t === 'copilot') return <svg {...p}><path d="M4 5h16v11H9l-5 4z" /><path d="M8.5 10.5h.01M12 10.5h.01M15.5 10.5h.01" strokeWidth="2.4" /></svg>
  return <svg {...p}><path d="M3 20h18" /><rect x="5" y="11" width="3" height="6" /><rect x="10.5" y="7" width="3" height="10" /><rect x="16" y="4" width="3" height="13" /></svg>
}
