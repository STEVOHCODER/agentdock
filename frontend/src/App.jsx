import React, { useEffect, useMemo, useState } from 'react'
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, Bell, BookOpen, Boxes, Check, CheckCircle2,
  ChevronRight, CircleDollarSign, ClipboardList, Clock, Code2, Copy, Cpu, CreditCard as CreditCardIcon, Database, Download,
  ExternalLink, FileText, Filter, FolderOpen, Github, Globe, Infinity as InfinityIcon, KeyRound,
  LayoutDashboard, Layers, Library, Lock, LogOut, Menu, Package, Plus, RefreshCw, Rocket, Search,
  Settings, Shield, ShieldCheck, Sparkles, Star, Terminal, Trash2, TrendingUp, Upload, UserPlus,
  Users, X, Zap,
} from 'lucide-react'
import { api, copy, dateLabel, dateTimeLabel, del, get, money, navigate, parseHash, patch, post, relativeLabel } from './api.js'

/* ------------------------------------------------------------------ */
/* Shared helpers                                                      */
/* ------------------------------------------------------------------ */

function useLoad(fetcher, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let alive = true
    setState({ loading: true, data: null, error: null })
    fetcher()
      .then((data) => { if (alive) setState({ loading: false, data, error: null }) })
      .catch((error) => { if (alive) setState({ loading: false, data: null, error }) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}

const API_KEY_SCOPES = [
  'skills:read', 'library:read', 'library:write', 'account:read',
  'teams:read', 'teams:write', 'marketplace:read', 'marketplace:write',
  'billing:read', 'execution:run',
]

const EVENT_LABELS = {
  search_executed: 'Search executed',
  search_failed: 'Search failed',
  discovery_executed: 'Discovery run',
  discovery_failed: 'Discovery failed',
  'skill.retrieved': 'Skill retrieved',
  retrieve_failed: 'Retrieval failed',
  mcp_executed: 'MCP tool executed',
  mcp_failed: 'MCP tool failed',
}

function eventLabel(event) {
  return EVENT_LABELS[event] || event
}

function eventDetail(item) {
  const detail = item.details?.query || item.details?.tool
  if (detail) return detail
  if (item.event?.includes('search')) return 'Search'
  if (item.event?.includes('mcp')) return 'AgentDock gateway'
  if (item.event?.includes('discovery')) return 'AgentDock discovery'
  if (item.event?.includes('retrieved')) return 'Skill retrieved'
  return item.skill_id || 'gateway event'
}

function tokenizeArgs(value) {
  const result = []
  let current = ''
  let quote = null
  for (const char of value || '') {
    if (quote) {
      if (char === quote) quote = null
      else current += char
    } else if (char === '"' || char === "'") {
      quote = char
    } else if (/\s/.test(char)) {
      if (current) { result.push(current); current = '' }
    } else {
      current += char
    }
  }
  if (current) result.push(current)
  return result
}

function Pill({ children, tone }) {
  return <span className={`badge ${tone ? `badge-${tone}` : ''}`}>{children}</span>
}

function Loading({ label = 'Loading' }) {
  return <div className="spinner-wrap"><div className="spinner" aria-label={label} /></div>
}

function EmptyState({ icon: Icon = Package, title, body, action, onAction }) {
  return (
    <div className="empty">
      <Icon size={30} />
      <h3>{title}</h3>
      <p>{body}</p>
      {action && <button className="btn btn-primary btn-sm" onClick={onAction}>{action}</button>}
    </div>
  )
}

function SkillTags({ skill }) {
  return (
    <div className="tags" style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
      {skill.category && <span className="tag">{skill.category}</span>}
      {(skill.technologies || []).slice(0, 3).map((tag) => <span className="tag" key={tag}>{tag}</span>)}
      {skill.premium && <Pill tone="violet">Premium</Pill>}
      {skill.security_status === 'clear' && <Pill tone="green">Scanned</Pill>}
    </div>
  )
}

function SkillCard({ skill, onSelect, onSave, saved }) {
  const stars = skill.stars || 0
  return (
    <article className="skill-card" onClick={() => onSelect?.(skill)}>
      <div className="skill-top">
        <span className="skill-name">{skill.name}</span>
        {stars > 0 && <Pill tone="amber">{stars}★</Pill>}
        {skill.rating > 0 && <span className="chip" title={`${skill.rating} from ${skill.review_count} reviews`}><Star size={11} fill="currentColor" /> {skill.rating.toFixed(1)}</span>}
      </div>
      <p className="skill-desc">{skill.description}</p>
      <SkillTags skill={skill} />
      <div className="skill-foot">
        <span>{skill.creator || 'Community'}</span>
        <span>·</span><span>{skill.license}</span>
        {onSave && (
          <button
            className="btn btn-ghost btn-sm"
            style={{ marginLeft: 'auto' }}
            onClick={(event) => { event.stopPropagation(); onSave(skill) }}
          >
            {saved ? 'Saved' : 'Save'}
          </button>
        )}
        {!onSave && <span className={`price ${skill.price_cents ? 'premium' : ''}`}>{skill.price_cents ? money(skill.price_cents, skill.currency) : 'Free'}</span>}
      </div>
    </article>
  )
}

function Stars({ value }) {
  return <span style={{ color: '#fbbf24', letterSpacing: 1 }}>{'★'.repeat(Math.round(value || 0))}{'☆'.repeat(5 - Math.round(value || 0))}</span>
}

function Field({ label, children }) {
  return <label className="field"><span className="label">{label}</span>{children}</label>
}

function Toggle({ options, value, onChange }) {
  return (
    <div className="tabs">
      {options.map((option) => (
        <button key={option.value} className={`tab ${value === option.value ? 'active' : ''}`} onClick={() => onChange(option.value)}>
          {option.label}
        </button>
      ))}
    </div>
  )
}

function Modal({ title, subtitle, onClose, children, wide }) {
  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className={`modal-card ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
          <button className="modal-close" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* App orchestrator                                                    */
/* ------------------------------------------------------------------ */

export default function App() {
  const [user, setUser] = useState(null)
  const [booted, setBooted] = useState(false)
  const [route, setRoute] = useState(() => parseHash())
  const [plans, setPlans] = useState([])
  const [toasts, setToasts] = useState([])
  const [selectedSkill, setSelectedSkill] = useState(null)
  const [selectedListing, setSelectedListing] = useState(null)
  const [adminTab, setAdminTab] = useState('overview')
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => {
    const onHash = () => { setRoute(parseHash()); setMobileOpen(false); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    get('/api/v1/auth/me').then((data) => setUser(data.user)).catch(() => setUser(null)).finally(() => setBooted(true))
  }, [])

  useEffect(() => {
    get('/api/v1/plans').then((data) => setPlans(data.items || [])).catch(() => setPlans([]))
  }, [])

  const notify = (kind, title, body) => {
    const id = Math.random().toString(36).slice(2)
    setToasts((items) => [...items, { id, kind, title, body }])
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 5200)
  }

  const signOut = async () => {
    await post('/api/v1/auth/logout', {})
    setUser(null)
    navigate('/')
    notify('success', 'Signed out', 'Your session has ended.')
  }

  if (!booted) {
    return <div className="spinner-wrap" style={{ minHeight: '100vh' }}><div className="spinner" /></div>
  }

  const publicPaths = ['/', '/marketplace', '/pricing', '/docs', '/developers', '/rights']
  const authPaths = ['/login', '/register', '/forgot-password', '/reset-password', '/verify-email']
  const isAuth = authPaths.includes(route.path)
  const isPublic = publicPaths.includes(route.path)
  const isApp = !isAuth && !isPublic && !!user
  const isAdmin = user && (user.role === 'admin' || user.role === 'super_admin')

  if (!isAuth && !isPublic && !user) {
    return (
      <>
        <AuthPage mode="login" route={route} setUser={setUser} notify={notify} plans={plans} />
        <ToastStack toasts={toasts} />
      </>
    )
  }

  return (
    <>
      {isAuth ? (
        <AuthPage mode={route.path.replace('/', '') || 'login'} route={route} setUser={setUser} notify={notify} plans={plans} />
      ) : isPublic ? (
        <PublicShell
          user={user}
          route={route}
          plans={plans}
          onSelectSkill={setSelectedSkill}
          onSelectListing={setSelectedListing}
          notify={notify}
          onSignOut={signOut}
        />
      ) : (
        <AppShell
          user={user}
          route={route}
          plans={plans}
          adminTab={adminTab}
          setAdminTab={setAdminTab}
          isAdmin={isAdmin}
          mobileOpen={mobileOpen}
          setMobileOpen={setMobileOpen}
          onSelectSkill={setSelectedSkill}
          onSelectListing={setSelectedListing}
          notify={notify}
          onSignOut={signOut}
          setUser={setUser}
        />
      )}
      {selectedSkill && (
        <SkillModal
          skill={selectedSkill}
          user={user}
          onClose={() => setSelectedSkill(null)}
          notify={notify}
        />
      )}
      {selectedListing && (
        <ListingModal
          listing={selectedListing}
          user={user}
          onClose={() => setSelectedListing(null)}
          notify={notify}
          onPurchased={() => {}}
        />
      )}
      <ToastStack toasts={toasts} />
    </>
  )
}

function ToastStack({ toasts }) {
  return (
    <div className="toast-wrap">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.kind}`}>
          {toast.kind === 'success' ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
          <div><b>{toast.title}</b><span>{toast.body}</span></div>
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Public shell and landing                                            */
/* ------------------------------------------------------------------ */

function PublicShell({ user, route, plans, onSelectSkill, onSelectListing, notify, onSignOut }) {
  const page = route.path === '/' ? 'home' : route.path.slice(1)
  const go = (path) => navigate(path)
  return (
    <div>
      <header className="public-nav">
        <div className="public-nav-inner">
          <button className="brand" onClick={() => go('/')} aria-label="AgentDock home">
            <span className="brand-mark"><Boxes size={16} /></span>
            Agent<em>Dock</em>
          </button>
          <nav className="public-links">
            <button className={page === 'explore' ? 'active' : ''} onClick={() => go('/marketplace')}>Marketplace</button>
            <button className={page === 'pricing' ? 'active' : ''} onClick={() => go('/pricing')}>Pricing</button>
            <button className={page === 'docs' ? 'active' : ''} onClick={() => go('/docs')}>Docs</button>
            <button className={page === 'developers' ? 'active' : ''} onClick={() => go('/developers')}>Developers</button>
            <button className={page === 'rights' ? 'active' : ''} onClick={() => go('/rights')}>Rights</button>
          </nav>
          <div className="nav-actions">
            {user ? (
              <>
                <button className="btn btn-outline btn-sm" onClick={() => go('/dashboard')}>Open dashboard</button>
                <button className="btn btn-ghost btn-sm" onClick={onSignOut}>Sign out</button>
              </>
            ) : (
              <>
                <button className="btn btn-ghost btn-sm" onClick={() => go('/login')}>Sign in</button>
                <button className="btn btn-primary btn-sm" onClick={() => go('/register')}>Start free</button>
              </>
            )}
          </div>
        </div>
      </header>

      {page === 'home' && <Landing user={user} plans={plans} navigate={go} onSelectSkill={onSelectSkill} onSelectListing={onSelectListing} notify={notify} />}
      {page === 'marketplace' && <MarketplaceV2 user={user} navigate={go} onSelect={onSelectListing} notify={notify} />}
      {page === 'pricing' && <PricingPage user={user} navigate={go} plans={plans} notify={notify} />}
      {page === 'docs' && <DocsPage navigate={go} />}
      {page === 'developers' && <DevelopersPage navigate={go} />}
      {page === 'rights' && <RightsPage navigate={go} notify={notify} />}

      <footer className="public-footer">
        <div className="public-footer-inner">
          <button className="brand" onClick={() => go('/')}><span className="brand-mark"><Boxes size={15} /></span>Agent<em>Dock</em></button>
          <div className="public-footer-links">
            <button onClick={() => go('/marketplace')}>Marketplace</button>
            <button onClick={() => go('/pricing')}>Pricing</button>
            <button onClick={() => go('/docs')}>Documentation</button>
            <button onClick={() => go('/rights')}>Rights and takedowns</button>
            <button onClick={() => go('/developers')}>API and MCP</button>
          </div>
          <span>© {new Date().getFullYear()} AgentDock. Skills are provided by their licensors.</span>
        </div>
      </footer>
    </div>
  )
}

function Landing({ user, plans, navigate, onSelectSkill, onSelectListing, notify }) {
  const featured = useLoad(() => get('/api/v1/marketplace/featured'), [])
  const stats = useLoad(() => get('/api/v1/skills?limit=1'), [])
  const preview = (featured.data?.items || []).slice(0, 3)

  return (
    <main>
      <section className="hero">
        <div className="hero-grid">
          <div>
            <span className="eyebrow"><span className="status-dot" /> The skill layer for AI coding agents</span>
            <h1 className="hero-title">Stop installing skills.<br /><span className="grad">Start using them.</span></h1>
            <p className="hero-sub">The infrastructure behind your AI coding agent. AgentDock indexes, verifies and serves production-ready skills through one MCP endpoint, one API key and one CLI command — so your agent gets the right capability at the moment it needs it.</p>
            <div className="hero-actions">
              <button className="btn btn-primary btn-lg" onClick={() => navigate(user ? '/dashboard' : '/register')}>
                {user ? 'Open your workspace' : 'Start free'} <ArrowRight size={16} />
              </button>
              <button className="btn btn-outline btn-lg" onClick={() => navigate('/marketplace')}>Explore the catalogue</button>
            </div>
            <div className="hero-meta">
              <div><strong>{stats.data ? stats.data.total.toLocaleString() : '—'}</strong>Curated skills</div>
              <div><strong>MCP + REST + CLI</strong>Every agent, one protocol</div>
              <div><strong>MIT-first</strong>Legally reviewable</div>
            </div>
          </div>

          <div className="mock">
            <div className="mock-glow" />
            <div className="mock-window">
              <div className="mock-titlebar"><i /><i /><i /><span>agentdock · mcp session</span></div>
              <div className="mock-body">
                <div className="mock-side">
                  <i className="active" /><i /><i /><i /><i /><i /><i />
                </div>
                <div className="mock-main">
                  <div className="mock-prompt">Build a production analytics dashboard for our PostgreSQL database.</div>
                  <div className="mock-tool"><Cpu size={13} /> search_skills <b>200</b></div>
                  <div className="mock-skill">
                    <h4>React Analytics Dashboard</h4>
                    <p>Layout, chart selection, empty states and accessibility guidance from a reviewed snapshot.</p>
                    <div className="tags"><span className="tag">Frontend</span><span className="tag">React</span><span className="tag">MIT</span></div>
                  </div>
                  <div className="mock-tool"><Zap size={13} /> get_skill · version pinned <b>✓</b></div>
                </div>
              </div>
            </div>
            <div className="mock-float one"><ShieldCheck size={17} /><div><b>Static scan clear</b><span>No secrets, no obfuscation</span></div></div>
            <div className="mock-float two"><Database size={17} /><div><b>Immutable snapshot</b><span>Versioned retrieval</span></div></div>
          </div>
        </div>
      </section>

      <div className="logo-row" style={{ maxWidth: 1240, margin: '0 auto', padding: '0 28px' }}>
        <span>TRUSTED BY TEAMS BUILDING WITH</span>
        <span>Claude Code</span><span>Cursor</span><span>Windsurf</span><span>OpenCode</span><span>Codex</span>
      </div>

      <section className="section">
        <div className="section-head">
          <div className="section-eyebrow">Why AgentDock</div>
          <h2>Your agent already has the model.<br /><span className="grad">Give it the craft.</span></h2>
          <p>Stop pasting the same instructions into every session. AgentDock turns repeatable expertise into versioned, licensed, retrievable skills.</p>
        </div>
        <div className="feature-grid">
          {[
            { icon: Zap, title: 'On-demand retrieval', body: 'Agents search and pull a skill only when the task needs it, keeping context lean and instructions current.' },
            { icon: ShieldCheck, title: 'Reviewed and scanned', body: 'Every skill passes licence review and static analysis before it can be retrieved. Snapshots are immutable.' },
            { icon: Layers, title: 'Versioned snapshots', body: 'Pin a version or follow the latest reviewed release. Retrieval always reports the exact content hash.' },
            { icon: Users, title: 'Teams and workspaces', body: 'Shared collections, seat limits, team plans and usage analytics for the people who depend on your agents.' },
            { icon: CircleDollarSign, title: 'Marketplace and billing', body: 'Free and premium skills with entitlement checks, receipts, creator earnings and manual invoicing.' },
            { icon: Terminal, title: 'MCP, REST and CLI', body: 'One endpoint for agents, one API for your tools and one command for your terminal. Same catalogue everywhere.' },
          ].map((item) => (
            <div className="feature-card" key={item.title}>
              <div className="feature-icon"><item.icon size={19} /></div>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section" style={{ paddingTop: 0 }}>
        <div className="section-head">
          <div className="section-eyebrow">How it works</div>
          <h2>Three steps from<br /><span className="grad">task to trusted skill.</span></h2>
        </div>
        <div className="steps">
          {[
            { title: 'Describe the task', body: 'Your agent calls search_skills with the job it is trying to do. AgentDock ranks the reviewed catalogue by relevance and quality.' },
            { title: 'Retrieve the snapshot', body: 'get_skill returns the pinned instructions and resource manifest. Premium skills check the account entitlement first.' },
            { title: 'Work with confidence', body: 'The agent follows a versioned workflow, and your team keeps attribution, audit history and usage analytics.' },
          ].map((step, index) => (
            <div className="step" key={step.title}>
              <span className="step-number">{String(index + 1).padStart(2, '0')}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="section" style={{ paddingTop: 0 }}>
        <div className="section-head" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', maxWidth: 'none' }}>
          <div>
            <div className="section-eyebrow">Featured skills</div>
            <h2>Ready for the next<br /><span className="grad">agent session.</span></h2>
          </div>
          <button className="btn btn-outline" onClick={() => navigate('/marketplace')}>Browse all skills <ArrowRight size={15} /></button>
        </div>
        {featured.loading ? <Loading /> : (
          <div className="preview-grid">
            {preview.map((item) => (
              <article className="skill-card" key={item.id} onClick={() => onSelectListing(item)}>
                <div className="skill-top"><span className="skill-name">{item.title}</span>{item.price_cents ? <Pill tone="violet">{money(item.price_cents, item.currency)}</Pill> : <Pill tone="green">Free</Pill>}</div>
                <p className="skill-desc">{item.summary}</p>
                <div className="skill-foot"><span>{item.creator}</span><span>·</span><span>{item.skill?.license}</span>{item.rating > 0 && <><span>·</span><Stars value={item.rating} /></>}</div>
              </article>
            ))}
            {preview.length === 0 && <div className="empty" style={{ gridColumn: '1 / -1' }}><Package size={28} /><h3>No featured skills yet</h3><p>The catalogue is being prepared. Check back shortly.</p></div>}
          </div>
        )}
      </section>

      <PricingSection user={user} navigate={navigate} plans={plans} compact />

      <section className="section" style={{ paddingTop: 0 }}>
        <div className="cta-band">
          <h2>Give your agent the skills it deserves.</h2>
          <p>Create a free workspace, connect MCP and retrieve your first reviewed skill in minutes.</p>
          <div className="hero-actions">
            <button className="btn btn-primary btn-lg" onClick={() => navigate(user ? '/dashboard' : '/register')}>Start free <ArrowRight size={16} /></button>
            <button className="btn btn-outline btn-lg" onClick={() => navigate('/developers')}>Read the docs</button>
          </div>
        </div>
      </section>
    </main>
  )
}

/* ------------------------------------------------------------------ */
/* Marketplace                                                         */
/* ------------------------------------------------------------------ */

function MarketplacePage({ user, navigate, onSelect, notify, embedded = false }) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [featuredOnly, setFeaturedOnly] = useState(false)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ q: query, limit: '50' })
    if (category) params.set('category', category)
    if (featuredOnly) params.set('featured', 'true')
    get(`/api/v1/marketplace/listings?${params}`)
      .then((data) => { setItems(data.items || []); setError(null) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [category, featuredOnly])
  useEffect(() => { const timer = window.setTimeout(load, 260); return () => window.clearTimeout(timer) }, [query])

  const categories = useMemo(() => [...new Set(items.map((item) => item.skill?.category).filter(Boolean))], [items])

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="section-eyebrow">Marketplace</div>
          <h1>Skills that respect your stack</h1>
          <p>Free and premium listings, reviewed for licence, security and commercial clearance.</p>
        </div>
        {user && (
          <div className="page-actions">
            <button className="btn btn-outline btn-sm" onClick={() => navigate('/purchases')}>My purchases</button>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/creator')}>Creator studio</button>
          </div>
        )}
      </div>

      <div className="toolbar">
        <div className="topbar-search" style={{ minWidth: 260 }}>
          <Search size={15} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search listings, skills and creators" />
        </div>
        <select className="select" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">All categories</option>
          {categories.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={featuredOnly} onChange={(event) => setFeaturedOnly(event.target.checked)} /> Featured only</label>
        <div className="toolbar-spacer" />
        <span className="count-note">{items.length} listings</span>
      </div>

      {loading ? <Loading /> : error ? <div className="banner">{error}</div> : (
        <div className="preview-grid">
          {items.map((item) => (
            <article className="skill-card" key={item.id} onClick={() => onSelect(item)}>
              <div className="skill-top">
                <span className="skill-name">{item.title}</span>
                {item.featured && <Pill tone="cyan">Featured</Pill>}
              </div>
              <p className="skill-desc">{item.summary}</p>
              <div className="tags" style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {item.skill?.category && <span className="tag">{item.skill.category}</span>}
                <span className="tag">{item.skill?.license}</span>
                {item.rating > 0 && <span className="chip"><Star size={11} fill="currentColor" /> {item.rating.toFixed(1)} ({item.review_count})</span>}
              </div>
              <div className="skill-foot">
                <span>{item.creator}</span>
                <span className={`price ${item.price_cents ? 'premium' : ''}`}>{item.price_cents ? money(item.price_cents, item.currency) : 'Free'}</span>
              </div>
            </article>
          ))}
          {items.length === 0 && <div className="empty" style={{ gridColumn: '1 / -1' }}><Search size={28} /><h3>No listings found</h3><p>Try a different search term or category. New skills are added after review.</p></div>}
        </div>
      )}
    </div>
  )
}

function ListingModal({ listing, user, onClose, notify, onPurchased }) {
  const detail = useLoad(() => get(`/api/v1/marketplace/listings/${listing.id}`), [listing.id])
  const [busy, setBusy] = useState(false)
  const data = detail.data || listing

  const purchase = async () => {
    if (!user) { navigate('/login'); return }
    setBusy(true)
    try {
      const result = await post('/api/v1/marketplace/purchases', { listing_id: data.id })
      if (result.checkout_url) {
        window.open(result.checkout_url, '_blank', 'noopener')
        notify('info', 'Checkout opened', result.message || 'Complete the secure payment to unlock this skill.')
      } else if (result.status === 'pending') {
        notify('info', 'Invoice created', result.message || 'An administrator will record the payment.')
      } else {
        notify('success', 'Added to your account', data.title)
      }
      onPurchased?.()
      onClose()
    } catch (error) {
      notify('error', 'Purchase failed', error.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={data.title} subtitle={data.creator ? `by ${data.creator}` : 'AgentDock Studio'} onClose={onClose} wide>
      {detail.loading ? <Loading /> : (
        <>
          <div className="tags" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
            <span className="tag">{data.skill?.category}</span>
            <span className="tag">{data.skill?.license}</span>
            {data.skill?.security_status === 'clear' && <Pill tone="green">Security scan clear</Pill>}
            {data.featured && <Pill tone="cyan">Featured</Pill>}
          </div>
          <p className="muted" style={{ lineHeight: 1.75, fontSize: 13.5 }}>{data.summary}</p>
          <div className="divider" />
          <div className="grid-2-even">
            <div>
              <div className="label">Skill details</div>
              <div className="list">
                <div className="list-row"><span className="activity-icon"><BookOpen size={14} /></span><div className="list-row-main"><b>{data.skill?.name}</b><span>{data.skill?.description}</span></div></div>
                <div className="list-row"><span className="activity-icon"><Layers size={14} /></span><div className="list-row-main"><b>Version {data.skill?.version || 'latest'}</b><span>Immutable reviewed snapshot</span></div></div>
                <div className="list-row"><span className="activity-icon"><Shield size={14} /></span><div className="list-row-main"><b>{data.skill?.security_status || 'pending'}</b><span>Static analysis result</span></div></div>
              </div>
            </div>
            <div>
              <div className="label">Reviews</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}><Stars value={data.rating} /> <b>{data.rating.toFixed(1)}</b> <span className="muted small">{data.review_count} reviews</span></div>
              <div className="stack-sm">
                {(data.reviews || []).slice(0, 4).map((review, index) => (
                  <div key={index} className="panel panel-pad" style={{ padding: 12 }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Stars value={review.rating} /><b className="small">{review.author}</b><span className="dim tiny">{dateLabel(review.created_at)}</span></div>
                    <p className="muted small" style={{ marginTop: 6, lineHeight: 1.6 }}>{review.body || 'Verified purchase.'}</p>
                  </div>
                ))}
                {(!data.reviews || data.reviews.length === 0) && <p className="dim small">No written reviews yet.</p>}
              </div>
            </div>
          </div>
          <div className="divider" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div>
              <div className="metric-value">{data.price_cents ? money(data.price_cents, data.currency) : 'Free'}</div>
              <div className="dim small">one-time licence · per account or team</div>
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
              <button className="btn btn-outline" onClick={onClose}>Close</button>
              <button className="btn btn-primary" disabled={busy} onClick={purchase}>
                {busy ? 'Processing…' : data.price_cents ? 'Buy this skill' : 'Add to my account'}
              </button>
            </div>
          </div>
        </>
      )}
    </Modal>
  )
}

function SkillModal({ skill, user, onClose, notify }) {
  const [busy, setBusy] = useState(false)
  const retrieve = async () => {
    if (!user) { navigate('/login'); return }
    setBusy(true)
    try {
      const result = await post(`/api/v1/skills/${encodeURIComponent(skill.slug || skill.id)}/retrieve`, {})
      notify('success', 'Skill retrieved', `${result.skill.name} · version ${result.version}`)
      onClose()
    } catch (error) {
      notify('error', 'Retrieval blocked', error.message)
    } finally {
      setBusy(false)
    }
  }
  const save = async () => {
    if (!user) { navigate('/login'); return }
    try {
      await post('/api/v1/user/library', { skill_id: skill.id })
      notify('success', 'Saved to Favorites', skill.name)
    } catch (error) {
      notify('error', 'Could not save skill', error.message)
    }
  }
  return (
    <Modal title={skill.name} subtitle={skill.creator ? `by ${skill.creator}` : undefined} onClose={onClose} wide>
      <div className="tags" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
        <span className="tag">{skill.category}</span>
        <span className="tag">{skill.license}</span>
        {skill.version && <span className="tag">v{skill.version}</span>}
        {skill.premium && <Pill tone="violet">Premium</Pill>}
        {skill.security_status === 'clear' && <Pill tone="green">Scanned</Pill>}
        {skill.price_cents ? <Pill tone="cyan">{money(skill.price_cents, skill.currency)}</Pill> : <Pill tone="green">Free</Pill>}
      </div>
      <p className="muted" style={{ lineHeight: 1.75, fontSize: 13.5 }}>{skill.description}</p>
      <div className="divider" />
      <div className="grid-2-even">
        <div className="panel panel-pad">
          <div className="label">Compatibility</div>
          <div className="stack-sm">
            {(skill.compatibility || ['MCP-compatible agents']).map((item) => <div key={item} className="status-item"><Check size={14} /><div><b>{item}</b><span>Retrieval verified</span></div></div>)}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="label">Dependencies and permissions</div>
          <div className="stack-sm">
            {(skill.dependencies || []).map((item) => <div key={item} className="small muted">· {item}</div>)}
            {(skill.permissions || []).map((item) => <div key={item} className="small muted">· {item}</div>)}
            {(!skill.dependencies?.length && !skill.permissions?.length) && <p className="dim small">No special dependencies.</p>}
          </div>
        </div>
      </div>
      <div className="divider" />
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <button className="btn btn-outline" onClick={save} disabled={!user}>Save to library</button>
        <button className="btn btn-primary" onClick={retrieve} disabled={busy}>{busy ? 'Retrieving…' : 'Retrieve skill'}</button>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------------ */
/* Pricing                                                             */
/* ------------------------------------------------------------------ */

function PricingSection({ user, navigate, plans, compact }) {
  const [interval, setInterval] = useState('month')
  return (
    <section className="section" style={compact ? {} : { paddingTop: 20 }}>
      <div className="section-head" style={{ textAlign: 'center', margin: '0 auto 36px' }}>
        <div className="section-eyebrow">Pricing</div>
        <h2>One workspace.<br /><span className="grad">Every agent connected.</span></h2>
        <p>Start free. Upgrade when your team needs shared collections, larger workspaces and premium entitlements.</p>
        <div style={{ marginTop: 20, display: 'flex', justifyContent: 'center' }}>
          <Toggle value={interval} onChange={setInterval} options={[{ value: 'month', label: 'Monthly' }, { value: 'year', label: 'Annual · save 17%' }]} />
        </div>
      </div>
      <div className="pricing-grid">
        {(plans.length ? plans : []).map((plan, index) => {
          const price = interval === 'year' ? plan.annual_price_cents : plan.price_cents
          const featured = index === Math.min(1, plans.length - 1)
          return (
            <div className={`price-card ${featured ? 'featured' : ''}`} key={plan.code}>
              {featured && <span className="badge badge-violet">Most popular</span>}
              <div className="price-name">{plan.name}</div>
              <div className="price-amount">{price ? money(price, plan.currency) : 'Free'} <span>{price ? (interval === 'year' ? '/year' : '/month') : ''}</span></div>
              <p className="price-desc">{plan.description}</p>
              <ul className="price-features">
                {(plan.features || []).map((feature) => <li key={feature}><Check size={13} /> {feature}</li>)}
                {plan.member_limit > 1 && <li><Check size={13} /> Up to {plan.member_limit} members</li>}
              </ul>
              <button
                className={`btn ${featured ? 'btn-primary' : 'btn-outline'} btn-block`}
                onClick={() => navigate(user ? (plan.member_limit > 1 ? '/teams' : '/billing') : '/register')}
              >
                {plan.price_cents ? (user ? 'Choose plan' : 'Start with ' + plan.name) : 'Start free'}
              </button>
            </div>
          )
        })}
        {plans.length === 0 && <div className="empty" style={{ gridColumn: '1 / -1' }}><CircleDollarSign size={28} /><h3>Plans are not configured</h3><p>An administrator has not published subscription plans yet.</p></div>}
      </div>
    </section>
  )
}

function PricingPage({ user, navigate, plans, notify }) {
  return (
    <main>
      <PricingSection user={user} navigate={navigate} plans={plans} />
      <section className="section" style={{ paddingTop: 0 }}>
        <div className="panel panel-pad">
          <div className="panel-head">
            <div><div className="panel-title">Need a larger deployment?</div><div className="panel-sub">Custom seat counts, private catalogue reviews, SAML-ready administration and invoicing are available on request.</div></div>
            <button className="btn btn-outline" onClick={() => navigate('/rights')}>Contact sales</button>
          </div>
        </div>
      </section>
    </main>
  )
}

/* ------------------------------------------------------------------ */
/* Auth                                                                */
/* ------------------------------------------------------------------ */

function AuthPage({ mode, route, setUser, notify, plans }) {
  const [form, setForm] = useState({ email: '', password: '', name: '', current_password: '', new_password: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const token = route.query.token
  const normalized = mode === 'register' ? 'register' : mode === 'forgot-password' ? 'forgot' : mode === 'reset-password' ? 'reset' : mode === 'verify-email' ? 'verify' : 'login'

  useEffect(() => {
    if (normalized !== 'verify' || !token) return
    post('/api/v1/auth/verify-email', { token })
      .then(() => setDone('Your email is verified. Sign in to continue.'))
      .catch((err) => setError(err.message))
  }, [normalized, token])

  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }))

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      let result
      if (normalized === 'login') result = await post('/api/v1/auth/login', { email: form.email, password: form.password })
      else if (normalized === 'register') result = await post('/api/v1/auth/register', { email: form.email, password: form.password, name: form.name })
      else if (normalized === 'forgot') result = await post('/api/v1/auth/forgot-password', { email: form.email })
      else if (normalized === 'reset') result = await post('/api/v1/auth/reset-password', { token, password: form.new_password })
      else throw new Error('Verification is still pending.')
      if (normalized === 'login' || normalized === 'register' || normalized === 'reset') {
        setUser(result.user)
        notify('success', normalized === 'register' ? 'Account created' : 'Welcome back', result.user.email)
        navigate('/dashboard')
      } else {
        setDone(result.message)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const titles = {
    login: ['Welcome back', 'Sign in to retrieve skills, manage your workspace and connect your agents.'],
    register: ['Create your workspace', 'Free forever for one person. Upgrade when your team grows.'],
    forgot: ['Reset your password', 'We will email a single-use reset link. It expires after 60 minutes.'],
    reset: ['Choose a new password', 'Use at least 12 characters. Other sessions will be signed out.'],
    verify: ['Verifying your email', 'Checking the verification link…'],
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        {done ? (
          <div className="auth-success">
            <div className="feature-icon"><CheckCircle2 size={24} /></div>
            <h1>{normalized === 'verify' ? 'Email verified' : 'Check your inbox'}</h1>
            <p className="muted" style={{ marginTop: 10 }}>{done}</p>
            <div style={{ marginTop: 20, display: 'flex', gap: 10, justifyContent: 'center' }}>
              <button className="btn btn-primary" onClick={() => navigate(normalized === 'verify' ? '/login' : '/login')}>Continue to sign in</button>
              <button className="btn btn-outline" onClick={() => navigate('/')}>Back home</button>
            </div>
          </div>
        ) : (
          <>
            <h1>{titles[normalized][0]}</h1>
            <p>{titles[normalized][1]}</p>
            <form onSubmit={submit}>
              {normalized === 'register' && <Field label="Name"><input className="input" value={form.name} onChange={update('name')} placeholder="Ada Lovelace" /></Field>}
              {normalized !== 'reset' && normalized !== 'verify' && (
                <Field label="Email"><input className="input" type="email" required value={form.email} onChange={update('email')} placeholder="you@example.com" /></Field>
              )}
              {(normalized === 'login' || normalized === 'register') && (
                <Field label="Password"><input className="input" type="password" required minLength={normalized === 'register' ? 12 : 1} value={form.password} onChange={update('password')} placeholder="••••••••••••" /></Field>
              )}
              {normalized === 'reset' && (
                <Field label="New password"><input className="input" type="password" required minLength={12} value={form.new_password} onChange={update('new_password')} placeholder="At least 12 characters" /></Field>
              )}
              {error && <div className="form-error">{error}</div>}
              {normalized === 'verify' && !error && <p className="form-note">This should only take a moment.</p>}
              {normalized !== 'verify' && (
                <button className="btn btn-primary btn-block btn-lg" style={{ marginTop: 8 }} disabled={busy}>
                  {busy ? 'Please wait…' : normalized === 'login' ? 'Sign in' : normalized === 'register' ? 'Create account' : normalized === 'forgot' ? 'Send reset link' : 'Reset password'}
                </button>
              )}
            </form>
            <div className="auth-alt">
              {normalized === 'login' && <>{'New to AgentDock? '}<button onClick={() => navigate('/register')}>Create a free workspace</button></>}
              {normalized === 'register' && <>{'Already have an account? '}<button onClick={() => navigate('/login')}>Sign in</button></>}
              {normalized === 'forgot' && <button onClick={() => navigate('/login')}>Back to sign in</button>}
              {normalized === 'reset' && <button onClick={() => navigate('/login')}>Back to sign in</button>}
            </div>
            {normalized === 'login' && <div className="auth-alt"><button onClick={() => navigate('/forgot-password')}>Forgot your password?</button></div>}
          </>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* App shell                                                           */
/* ------------------------------------------------------------------ */

const NAV = [
  { group: 'Workspace', items: [
    { path: '/dashboard', label: 'Overview', icon: LayoutDashboard },
    { path: '/explore', label: 'Explore skills', icon: Search },
    { path: '/library', label: 'Library', icon: Library },
    { path: '/vault', label: 'Version vault', icon: Database },
    { path: '/exec', label: 'Execution console', icon: Terminal },
  ] },
  { group: 'Commerce', items: [
    { path: '/marketplace', label: 'Marketplace', icon: Package },
    { path: '/purchases', label: 'My purchases', icon: CheckCircle2 },
    { path: '/creator', label: 'Creator studio', icon: Sparkles },
    { path: '/teams', label: 'Teams', icon: Users },
    { path: '/billing', label: 'Billing', icon: CircleDollarSign },
  ] },
  { group: 'Account', items: [
    { path: '/usage', label: 'Usage', icon: BarChart3 },
    { path: '/integrations', label: 'Integrations', icon: PlugIcon },
    { path: '/settings', label: 'Settings', icon: Settings },
  ] },
]

function PlugIcon(props) { return <Terminal {...props} /> }

function AppShell({ user, route, plans, adminTab, setAdminTab, isAdmin, mobileOpen, setMobileOpen, onSelectSkill, onSelectListing, notify, onSignOut, setUser }) {
  const page = route.path === '/' ? '/dashboard' : route.path
  const [notifications, setNotifications] = useState([])
  const [query, setQuery] = useState('')

  useEffect(() => {
    get('/api/v1/account/notifications').then((data) => setNotifications(data.items || [])).catch(() => {})
  }, [])

  useEffect(() => {
    if (page === '/explore' && query.trim()) {
      const timer = window.setTimeout(() => navigate(`/explore?q=${encodeURIComponent(query)}`), 240)
      return () => window.clearTimeout(timer)
    }
  }, [query, page])

  const content = () => {
    if (page === '/dashboard') return <Dashboard user={user} navigate={navigate} onSelectSkill={onSelectSkill} notify={notify} />
    if (page === '/explore') return <Explore user={user} query={route.query.q || ''} navigate={navigate} onSelect={onSelectSkill} notify={notify} />
    if (page === '/library') return <LibraryPage user={user} navigate={navigate} notify={notify} />
    if (page === '/vault') return <VaultPage navigate={navigate} onSelect={onSelectSkill} />
    if (page === '/exec') return <ExecutionConsole navigate={navigate} notify={notify} />
    if (page === '/marketplace') return <MarketplaceV2 user={user} navigate={navigate} onSelect={onSelectListing} notify={notify} />
    if (page === '/purchases') return <PurchasesPage navigate={navigate} onSelect={onSelectSkill} />
    if (page === '/creator') return <CreatorPage user={user} navigate={navigate} notify={notify} />
    if (page === '/teams') return <TeamsPage user={user} route={route} navigate={navigate} notify={notify} />
    if (page === '/billing') return <BillingPage user={user} plans={plans} navigate={navigate} notify={notify} />
    if (page === '/usage') return <UsagePage navigate={navigate} onSelect={onSelectSkill} />
    if (page === '/integrations') return <IntegrationsPage user={user} navigate={navigate} notify={notify} />
    if (page === '/settings') return <SettingsPage user={user} route={route} setUser={setUser} notify={notify} onSignOut={onSignOut} />
    if (page === '/admin' && isAdmin) return <AdminPage tab={adminTab} setTab={setAdminTab} notify={notify} />
    return <Dashboard user={user} navigate={navigate} onSelectSkill={onSelectSkill} notify={notify} />
  }

  const unread = notifications.filter((item) => !item.read).length
  const initials = (user.name || user.email || 'A').slice(0, 1).toUpperCase()

  return (
    <div className="app-layout">
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <div className="sidebar-logo"><span className="brand-mark"><Boxes size={16} /></span> Agent<em>Dock</em></div>
        {isAdmin && (
          <div className="nav-group">
            <div className="nav-group-label">Administration</div>
            <button className={`nav-link ${page === '/admin' ? 'active' : ''}`} onClick={() => navigate('/admin')}><Shield size={16} /> Control center</button>
          </div>
        )}
        {NAV.map((group) => (
          <div className="nav-group" key={group.group}>
            <div className="nav-group-label">{group.group}</div>
            {group.items.map((item) => (
              <button key={item.path} className={`nav-link ${page === item.path ? 'active' : ''}`} onClick={() => navigate(item.path)}>
                <item.icon size={16} /> {item.label}
              </button>
            ))}
          </div>
        ))}
        <div className="sidebar-spacer" />
        <div className="sidebar-user">
          <span className="avatar">{initials}</span>
          <div style={{ minWidth: 0 }}><b>{user.name || user.email}</b><span>{user.role}</span></div>
          <button onClick={onSignOut} title="Sign out"><LogOut size={15} /></button>
        </div>
      </aside>

      <div className="app-main">
        <div className="topbar">
          <button className="icon-btn mobile-toggle" onClick={() => setMobileOpen((value) => !value)} aria-label="Toggle navigation"><Menu size={17} /></button>
          <div className="topbar-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search skills and pages" /></div>
          <div className="topbar-actions">
            <button className="icon-btn" title="Notifications" onClick={() => navigate('/settings?tab=notifications')}>
              <Bell size={16} />{unread > 0 && <span className="dot" />}
            </button>
            <button className="icon-btn" title="Marketplace" onClick={() => navigate('/marketplace')}><Package size={16} /></button>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/billing')}>Upgrade</button>
          </div>
        </div>
        <div className="content">{content()}</div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Dashboard and catalogue                                             */
/* ------------------------------------------------------------------ */

function Dashboard({ user, navigate, onSelectSkill, notify }) {
  const entitlements = useLoad(() => get('/api/v1/account/entitlements'), [])
  const usage = useLoad(() => get('/api/v1/account/usage'), [])
  const discovery = useLoad(() => get('/api/v1/skills/discovery?track=false'), [])
  const library = useLoad(() => get('/api/v1/user/library'), [])

  const recommended = discovery.data?.recommended || []
  const max = Math.max(1, ...(usage.data?.series || []).map((item) => item.retrievals))

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="section-eyebrow">Overview</div>
          <h1>{greeting()}, {user.name || user.email.split('@')[0]}</h1>
          <p>Your agent workspace is ready. Retrieve a skill, connect an integration or invite your team.</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-outline" onClick={() => navigate('/explore')}><Search size={15} /> Explore skills</button>
          <button className="btn btn-primary" onClick={() => navigate('/integrations')}><PlugIcon size={15} /> Connect agent</button>
        </div>
      </div>

      {(usage.error || library.error || entitlements.error) && (
        <div className="banner" style={{ marginBottom: 18 }}>
          <AlertTriangle size={16} />
          <div>
            <b>Live account data could not load.</b>{' '}
            {usage.error?.status === 401 || library.error?.status === 401
              ? 'Your browser session was not accepted. Reload and sign in again.'
              : 'The gateway request failed. Check the connection and reload.'}
            <button className="btn btn-outline btn-sm" style={{ marginLeft: 12 }} onClick={() => window.location.reload()}>Reload</button>
          </div>
        </div>
      )}

      <div className="metric-grid">
        <div className="metric-card"><div className="metric-label"><CircleDollarSign size={14} /> Current plan</div><div className="metric-value">{entitlements.data?.plan_name || 'Free'}</div><div className="metric-note">{entitlements.data?.plan_code || 'free'}</div></div>
        <div className="metric-card"><div className="metric-label"><Search size={14} /> Searches executed</div><div className="metric-value">{usage.data?.stats?.searches_executed ?? 0}</div><div className="metric-note">successful</div></div>
        <div className="metric-card"><div className="metric-label"><BookOpen size={14} /> Discovery runs</div><div className="metric-value">{usage.data?.stats?.discovered ?? 0}</div><div className="metric-note">runs</div></div>
        <div className="metric-card"><div className="metric-label"><Zap size={14} /> Skills retrieved</div><div className="metric-value">{usage.data?.skills_retrieved ?? 0}</div><div className="metric-note">successful</div></div>
        <div className="metric-card"><div className="metric-label"><Library size={14} /> Saved skills</div><div className="metric-value">{library.data?.items?.length ?? '—'}</div><div className="metric-note">in your library</div></div>
        <div className="metric-card"><div className="metric-label"><Users size={14} /> Teams</div><div className="metric-value">{entitlements.data?.teams?.length ?? 0}</div><div className="metric-note">{entitlements.data?.teams?.length ? 'shared workspaces' : 'invite your team'}</div></div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <div><div className="panel-title">Successful first run</div><div className="panel-sub">Search, discover, connect and retrieve — everything is approved and retrievable by gateway.</div></div>
        </div>
        <div className="status-grid">
          <div className="status-item"><CheckCircle2 size={15} /><div><b>Search works</b><span>{usage.data?.skills_retrieved ?? 0} skills retrieved so far</span></div></div>
          <div className="status-item"><CheckCircle2 size={15} /><div><b>Recommended skills</b><span>{recommended.length} recommended skills shown above</span></div></div>
          <div className="status-item"><CheckCircle2 size={15} /><div><b>Use via API</b><span>Connect an agent or use the CLI</span></div></div>
          <div className="status-item"><CheckCircle2 size={15} /><div><b>Retrieve and save</b><span>Skills are approved and have versioned snapshots</span></div></div>
        </div>
        <div className="activity" style={{ marginTop: 12 }}>
          {(usage.data?.items || []).slice(0, 5).map((item, index) => (
            <div className="activity-row" key={index}>
              <span className="activity-icon"><Zap size={14} /></span>
              <div><b>{eventLabel(item.event)}</b><span>{eventDetail(item)}</span></div>
              <Pill tone="cyan">{item.source}</Pill>
              <time>{relativeLabel(item.created_at)}</time>
            </div>
          ))}
          {(!usage.data?.items || usage.data.items.length === 0) && <p className="muted small">Retrieve or save your first skill to build history here.</p>}
        </div>
      </div>

      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="panel-head">
            <div><div className="panel-title">Retrievals, last 14 days</div><div className="panel-sub">Every MCP, REST and CLI retrieval for your account</div></div>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/usage')}>Details</button>
          </div>
          {usage.loading ? <Loading /> : (
            <div className="chart">
              {(usage.data?.series || []).map((item) => (
                <div className="chart-col" key={item.date}>
                  <div className={`chart-bar ${item.retrievals ? '' : 'zero'}`} style={{ height: `${Math.max(4, (item.retrievals / max) * 130)}px` }} title={`${item.retrievals} on ${item.date}`} />
                  <span className="chart-label">{item.date.slice(5)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="panel panel-pad">
          <div className="panel-head">
            <div><div className="panel-title">Recommended for your agents</div><div className="panel-sub">Highest quality reviewed skills</div></div>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/explore')}>View all</button>
          </div>
          {discovery.loading ? <Loading /> : (
            <div className="activity">
              {(recommended.length ? recommended : []).slice(0, 5).map((skill) => (
                <button className="activity-row" key={skill.id} style={{ background: 'transparent', border: '0', borderBottom: '1px solid var(--line)', cursor: 'pointer', textAlign: 'left' }} onClick={() => onSelectSkill(skill)}>
                  <span className="activity-icon"><Sparkles size={14} /></span>
                  <div><b>{skill.name}</b><span>{skill.category} · {skill.license}</span></div>
                  <ChevronRight size={15} />
                </button>
              ))}
              {recommended.length === 0 && <p className="muted small">No recommendations yet.</p>}
            </div>
          )}
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <div><div className="panel-title">Your library</div><div className="panel-sub">Skills you saved for quick retrieval</div></div>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/library')}>Open library</button>
        </div>
        {library.loading ? <Loading /> : (
          <div className="preview-grid">
            {(library.data?.items || []).slice(0, 3).map((skill) => <SkillCard key={skill.id} skill={skill} onSelect={onSelectSkill} />)}
            {(library.data?.items || []).length === 0 && <div className="empty" style={{ gridColumn: '1 / -1' }}><Library size={28} /><h3>Your library is empty</h3><p>Save skills from Explore to build a fast, personal retrieval set.</p><button className="btn btn-primary btn-sm" onClick={() => navigate('/explore')}>Find a skill</button></div>}
          </div>
        )}
      </div>
    </div>
  )
}

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function Explore({ user, query, navigate, onSelect, notify }) {
  const [term, setTerm] = useState(query)
  const [category, setCategory] = useState('')
  const [community, setCommunity] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => { setTerm(query) }, [query])

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ q: term, limit: '50' })
    if (category) params.set('category', category)
    if (community) params.set('community', community)
    get(`/api/v1/skills/search?${params}`)
      .then((data) => { setItems(data.items || []); setTotal(data.total || 0); setError(null) })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [category, community])
  useEffect(() => { const timer = window.setTimeout(load, 240); return () => window.clearTimeout(timer) }, [term])

  const save = async (skill) => {
    if (!user) { navigate('/login'); return }
    try {
      await post('/api/v1/user/library', { skill_id: skill.id })
      notify('success', 'Saved', skill.name)
    } catch (err) { notify('error', 'Could not save', err.message) }
  }

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Catalogue</div><h1>Explore reviewed skills</h1><p>Every listing is licence-checked, statically scanned and served from an immutable snapshot.</p></div>
      </div>
      <div className="toolbar">
        <div className="topbar-search"><Search size={15} /><input value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Search by task, technology or category" /></div>
        <input className="input" style={{ width: 180 }} value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Category" />
        <input className="input" style={{ width: 180 }} value={community} onChange={(event) => setCommunity(event.target.value)} placeholder="Community" />
        <div className="toolbar-spacer" /><span className="count-note">{total} results</span>
      </div>
      {loading ? <Loading /> : error ? <div className="banner">{error}</div> : (
        <div className="preview-grid">
          {items.map((skill) => <SkillCard key={skill.id} skill={skill} onSelect={onSelect} onSave={save} />)}
          {items.length === 0 && <div className="empty" style={{ gridColumn: '1 / -1' }}><Search size={28} /><h3>No skills match</h3><p>Try fewer filters or a broader task description.</p></div>}
        </div>
      )}
    </div>
  )
}

function LibraryPage({ user, navigate, notify }) {
  const collections = useLoad(() => get('/api/v1/user/collections'), [])
  const [active, setActive] = useState(null)
  const items = useLoad(() => get(`/api/v1/user/collections/${active || 'none'}/items`), [active])
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const selected = (collections.data?.items || []).find((item) => item.id === active) || (collections.data?.items || [])[0]

  const create = async (event) => {
    event.preventDefault()
    try {
      const collection = await post('/api/v1/user/collections', { name, description })
      notify('success', 'Collection created', collection.name)
      setCreating(false); setName(''); setDescription('')
      window.location.reload()
    } catch (error) { notify('error', 'Could not create collection', error.message) }
  }

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Library</div><h1>Saved skills</h1><p>Organize the capabilities your agents retrieve most often.</p></div>
        <div className="page-actions"><button className="btn btn-primary" onClick={() => setCreating(true)}><Plus size={15} /> New collection</button></div>
      </div>
      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="label">Collections</div>
          <div className="stack-sm">
            {(collections.data?.items || []).map((collection) => (
              <button key={collection.id} className={`admin-tab ${selected?.id === collection.id ? 'active' : ''}`} style={{ justifyContent: 'flex-start' }} onClick={() => setActive(collection.id)}>
                <FolderOpen size={15} />
                <span style={{ flex: 1, textAlign: 'left' }}>{collection.name}</span>
                <span className="dim tiny">{collection.skill_count}</span>
                {collection.shared && <Pill tone="cyan">Team</Pill>}
              </button>
            ))}
            {(!collections.data?.items || collections.data.items.length === 0) && <p className="muted small">No collections yet.</p>}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">{selected?.name || 'Select a collection'}</div><div className="panel-sub">{selected?.description || 'Choose a collection on the left.'}</div></div></div>
          {items.loading ? <Loading /> : (
            <div className="activity">
              {(items.data?.items || []).map((skill) => (
                <div className="activity-row" key={skill.id}>
                  <span className="activity-icon"><BookOpen size={14} /></span>
                  <div><b>{skill.name}</b><span>{skill.category} · {skill.license}</span></div>
                  <button className="btn btn-ghost btn-sm" onClick={() => navigate('/explore')}>Find similar</button>
                </div>
              ))}
              {(items.data?.items || []).length === 0 && <p className="muted small">No skills in this collection yet.</p>}
            </div>
          )}
        </div>
      </div>
      {creating && (
        <Modal title="New collection" onClose={() => setCreating(false)}>
          <form onSubmit={create}>
            <Field label="Name"><input className="input" required value={name} onChange={(event) => setName(event.target.value)} /></Field>
            <Field label="Description"><input className="input" value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-outline" onClick={() => setCreating(false)}>Cancel</button>
              <button className="btn btn-primary">Create collection</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

function VaultPage({ navigate, onSelect }) {
  const vault = useLoad(() => get('/api/v1/user/vault'), [])
  const summary = vault.data?.summary || {}
  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Version vault</div><h1>Archived skill versions</h1><p>Every retrieval points at an immutable snapshot, even when upstream changes or disappears.</p></div>
      </div>
      <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Archived skills</div><div className="metric-value">{summary.archived_skills ?? '—'}</div></div>
        <div className="metric-card"><div className="metric-label">Available versions</div><div className="metric-value">{summary.available_versions ?? '—'}</div></div>
        <div className="metric-card"><div className="metric-label">Last sync</div><div className="metric-value" style={{ fontSize: 18 }}>{dateTimeLabel(summary.last_sync_at)}</div></div>
        <div className="metric-card"><div className="metric-label">Upstream unavailable</div><div className="metric-value">{summary.upstream_unavailable ?? '—'}</div><div className="metric-note">reviewed snapshots retained</div></div>
      </div>
      <div className="panel panel-pad">
        {vault.loading ? <Loading /> : (
          <div className="activity">
            {(vault.data?.items || []).map((skill) => (
              <button className="activity-row" key={skill.id} style={{ background: 'transparent', border: '0', borderBottom: '1px solid var(--line)', cursor: 'pointer', textAlign: 'left' }} onClick={() => onSelect(skill)}>
                <span className="activity-icon"><Database size={14} /></span>
                <div><b>{skill.name}</b><span>{skill.version_count} versions · {skill.upstream_status}</span></div>
                <Pill tone={skill.verification_status === 'verified' ? 'green' : 'amber'}>{skill.verification_status}</Pill>
              </button>
            ))}
            {(vault.data?.items || []).length === 0 && <EmptyState icon={Database} title="No archived skills" body="Save a skill to your library to keep an immutable version here." action="Open library" onAction={() => navigate('/library')} />}
          </div>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Purchases, creator and teams                                        */
/* ------------------------------------------------------------------ */

function PurchasesPage({ navigate, onSelect }) {
  const purchases = useLoad(() => get('/api/v1/marketplace/purchases'), [])
  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Purchases</div><h1>Premium entitlements</h1><p>Skills your account or teams own. Retrieval checks these entitlements first.</p></div>
        <button className="btn btn-outline" onClick={() => navigate('/marketplace')}>Browse marketplace</button>
      </div>
      {purchases.loading ? <Loading /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Skill</th><th>Amount</th><th>Status</th><th>Purchased</th><th></th></tr></thead>
            <tbody>
              {(purchases.data?.items || []).map((purchase) => (
                <tr key={purchase.id}>
                  <td className="main"><b>{purchase.title}</b><span>{purchase.skill_name}</span></td>
                  <td>{purchase.amount_cents ? money(purchase.amount_cents, purchase.currency) : 'Free'}</td>
                  <td><Pill tone={purchase.status === 'paid' ? 'green' : purchase.status === 'refunded' ? 'red' : 'amber'}>{purchase.status}</Pill></td>
                  <td className="muted">{dateLabel(purchase.paid_at || purchase.created_at)}</td>
                  <td><button className="btn btn-ghost btn-sm" onClick={() => onSelect({ id: purchase.skill_id, slug: purchase.skill_slug, name: purchase.skill_name })}>Open</button></td>
                </tr>
              ))}
              {(purchases.data?.items || []).length === 0 && <tr><td colSpan="5"><EmptyState icon={Package} title="No purchases yet" body="Buy a premium skill to unlock retrieval here." action="Open marketplace" onAction={() => navigate('/marketplace')} /></td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function CreatorPage({ user, navigate, notify }) {
  const profile = useLoad(() => get('/api/v1/creator/profile'), [])
  const listings = useLoad(() => get('/api/v1/marketplace/my-listings'), [])
  const earnings = useLoad(() => get('/api/v1/creator/earnings'), [])
  const [form, setForm] = useState({ display_name: '', bio: '', website: '' })
  const [busy, setBusy] = useState(false)
  const current = profile.data?.profile

  useEffect(() => {
    if (current) setForm({ display_name: current.display_name, bio: current.bio, website: current.website })
  }, [current?.id])

  const apply = async (event) => {
    event.preventDefault(); setBusy(true)
    try {
      await post('/api/v1/creator/apply', form)
      notify('success', 'Application submitted', 'An administrator will review your creator profile.')
      window.location.reload()
    } catch (error) { notify('error', 'Application failed', error.message) } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Creator studio</div><h1>Sell your skills</h1><p>Publish premium listings, track reviews and see your earnings after the platform commission.</p></div>
      </div>
      <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Status</div><div className="metric-value" style={{ fontSize: 20 }}>{current ? current.status : 'Not applied'}</div></div>
        <div className="metric-card"><div className="metric-label">Revenue share</div><div className="metric-value">{current ? `${(current.revenue_share_bps / 100).toFixed(0)}%` : '85%'}</div></div>
        <div className="metric-card"><div className="metric-label">Lifetime earnings</div><div className="metric-value">{money(earnings.data?.total_cents || 0)}</div></div>
        <div className="metric-card"><div className="metric-label">Pending payout</div><div className="metric-value">{money(earnings.data?.pending_cents || 0)}</div></div>
      </div>

      {!current || current.status === 'rejected' ? (
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">Apply to become a creator</div><div className="panel-sub">We review identity, licensing and the quality of your first listing before approval.</div></div></div>
          <form onSubmit={apply}>
            <div className="field-row">
              <Field label="Display name"><input className="input" required value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></Field>
              <Field label="Website"><input className="input" value={form.website} onChange={(event) => setForm({ ...form, website: event.target.value })} /></Field>
            </div>
            <Field label="Bio"><textarea className="textarea" value={form.bio} onChange={(event) => setForm({ ...form, bio: event.target.value })} /></Field>
            <button className="btn btn-primary" disabled={busy}>{busy ? 'Submitting…' : 'Submit application'}</button>
          </form>
        </div>
      ) : (
        <div className="grid-2">
          <div className="panel panel-pad">
            <div className="panel-head"><div><div className="panel-title">Your listings</div><div className="panel-sub">Approved listings appear in the marketplace</div></div></div>
            <div className="activity">
              {(listings.data?.items || []).map((listing) => (
                <div className="activity-row" key={listing.id}>
                  <span className="activity-icon"><Package size={14} /></span>
                  <div><b>{listing.title}</b><span>{money(listing.price_cents, listing.currency)} · {listing.status}</span></div>
                  <Pill tone={listing.status === 'approved' ? 'green' : 'amber'}>{listing.status}</Pill>
                </div>
              ))}
              {(!listings.data?.items || listings.data.items.length === 0) && <p className="muted small">No listings yet. Listing creation arrives with the next API release.</p>}
            </div>
          </div>
          <div className="panel panel-pad">
            <div className="panel-head"><div><div className="panel-title">Earnings</div><div className="panel-sub">Pending earnings are payable after the refund window closes</div></div></div>
            <div className="activity">
              {(earnings.data?.items || []).map((item) => (
                <div className="activity-row" key={item.id}>
                  <span className="activity-icon"><CircleDollarSign size={14} /></span>
                  <div><b>{money(item.amount_cents)}</b><span>{item.status}</span></div>
                  <time>{dateLabel(item.created_at)}</time>
                </div>
              ))}
              {(!earnings.data?.items || earnings.data.items.length === 0) && <p className="muted small">No earnings yet.</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function TeamsPage({ user, route, navigate, notify }) {
  const teams = useLoad(() => get('/api/v1/teams'), [])
  const [form, setForm] = useState({ name: '', email: '', role: 'member' })
  const [creating, setCreating] = useState(false)
  const [inviting, setInviting] = useState(null)
  const [inviteLink, setInviteLink] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const team = (teams.data?.items || []).find((item) => item.id === selectedId) || (teams.data?.items || [])[0]
  const usage = useLoad(() => get(`/api/v1/teams/${team?.id || 'none'}/usage`), [team?.id])

  useEffect(() => {
    const token = route.query.invite
    if (!token || !user) return
    post('/api/v1/teams/invitations/accept', { token })
      .then(() => notify('success', 'Invitation accepted', 'You joined the team workspace.'))
      .catch((error) => notify('error', 'Invitation failed', error.message))
      .finally(() => navigate('/teams'))
  }, [route.query.invite, user?.id])

  const create = async (event) => {
    event.preventDefault()
    try {
      const created = await post('/api/v1/teams', { name: form.name })
      notify('success', 'Team created', created.name)
      setCreating(false); setForm({ ...form, name: '' })
      window.location.reload()
    } catch (error) { notify('error', 'Could not create team', error.message) }
  }

  const invite = async (event) => {
    event.preventDefault()
    try {
      const result = await post(`/api/v1/teams/${team.id}/invitations`, { email: form.email, role: form.role })
      setInviteLink(result.invite_link)
      setForm({ ...form, email: '' })
      notify('success', 'Invitation created', 'Share the one-time link with your teammate.')
    } catch (error) { notify('error', 'Could not invite', error.message) }
  }

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Teams</div><h1>Shared workspaces</h1><p>Invite teammates, share collections and keep one plan for the people building with your agents.</p></div>
        <div className="page-actions"><button className="btn btn-primary" onClick={() => setCreating(true)}><UserPlus size={15} /> New team</button></div>
      </div>
      {inviteLink && (
        <div className="banner info" style={{ marginBottom: 18 }}>
          <CheckCircle2 size={17} />
          <div style={{ flex: 1 }}><b>Invitation link created</b><br />Share this one-time link: <span className="mono small">{inviteLink}</span></div>
          <button className="btn btn-outline btn-sm" onClick={() => copy(inviteLink)}><Copy size={13} /> Copy</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setInviteLink('')}>Dismiss</button>
        </div>
      )}
      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="label">Your teams</div>
          <div className="stack-sm">
            {(teams.data?.items || []).map((item) => (
              <button key={item.id} className={`admin-tab ${team?.id === item.id ? 'active' : ''}`} style={{ justifyContent: 'flex-start' }} onClick={() => setSelectedId(item.id)}>
                <Users size={15} /><span style={{ flex: 1, textAlign: 'left' }}>{item.name}</span>
                <span className="dim tiny">{item.member_count}/{item.seat_limit}</span>
                <Pill tone="violet">{item.plan_name}</Pill>
              </button>
            ))}
            {(!teams.data?.items || teams.data.items.length === 0) && <p className="muted small">You are not in a team yet.</p>}
          </div>
        </div>
        <div className="panel panel-pad">
          {team ? (
            <>
              <div className="panel-head">
                <div><div className="panel-title">{team.name}</div><div className="panel-sub">Plan {team.plan_name} · {team.member_count}/{team.seat_limit} seats · your role: {team.role}</div></div>
                {(team.role === 'owner' || team.role === 'admin') && <button className="btn btn-outline btn-sm" onClick={() => setInviting(true)}><UserPlus size={14} /> Invite</button>}
              </div>
              <div className="label">Members</div>
              <div className="activity">
                {(team.members || []).map((member) => (
                  <div className="activity-row" key={member.user_id}>
                    <span className="avatar">{(member.name || member.email).slice(0, 1).toUpperCase()}</span>
                    <div><b>{member.name || member.email}</b><span>{member.email}</span></div>
                    <Pill tone={member.role === 'owner' ? 'violet' : 'cyan'}>{member.role}</Pill>
                  </div>
                ))}
              </div>
              <div className="divider" />
              <div className="label">Team usage</div>
              {usage.loading ? <Loading /> : (
                <div className="status-grid">
                  <div className="status-item"><Zap size={15} /><div><b>{usage.data.retrievals}</b><span>retrievals</span></div></div>
                  <div className="status-item"><Terminal size={15} /><div><b>{Object.keys(usage.data.by_source || {}).length}</b><span>sources used</span></div></div>
                </div>
              )}
            </>
          ) : <EmptyState icon={Users} title="No team selected" body="Create a team to invite collaborators and share a plan." action="New team" onAction={() => setCreating(true)} />}
        </div>
      </div>

      {creating && (
        <Modal title="Create a team" onClose={() => setCreating(false)}>
          <form onSubmit={create}>
            <Field label="Team name"><input className="input" required minLength={2} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Core Platform" /></Field>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-outline" onClick={() => setCreating(false)}>Cancel</button>
              <button className="btn btn-primary">Create team</button>
            </div>
          </form>
        </Modal>
      )}
      {inviting && team && (
        <Modal title={`Invite to ${team.name}`} onClose={() => setInviting(false)}>
          <form onSubmit={invite}>
            <Field label="Email"><input className="input" type="email" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></Field>
            <Field label="Role">
              <select className="select" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
                <option value="member">Member</option><option value="admin">Admin</option>
              </select>
            </Field>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-outline" onClick={() => setInviting(false)}>Cancel</button>
              <button className="btn btn-primary">Create invitation</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Billing and usage                                                   */
/* ------------------------------------------------------------------ */

function BillingPage({ user, plans, navigate, notify }) {
  const subscription = useLoad(() => get('/api/v1/account/subscription'), [])
  const billing = useLoad(() => get('/api/v1/account/billing'), [])
  const teams = useLoad(() => get('/api/v1/teams'), [])
  const [interval, setInterval] = useState('month')
  const [teamId, setTeamId] = useState('')
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  const checkout = async (plan) => {
    setBusy(true)
    try {
      const payload = { plan_code: plan.code, interval }
      if (plan.member_limit > 1) {
        if (!teamId) { notify('error', 'Choose a team', 'Team plans need a workspace.'); setBusy(false); return }
        payload.team_id = teamId
      }
      const result = await post('/api/v1/account/subscription/checkout', payload)
      if (result.checkout_url) window.open(result.checkout_url, '_blank', 'noopener')
      notify('info', 'Checkout created', result.message)
      window.location.reload()
    } catch (error) { notify('error', 'Checkout failed', error.message) } finally { setBusy(false) }
  }

  const cancel = async () => {
    setCancelling(true)
    try {
      await post('/api/v1/account/subscription/cancel', { reason: 'Cancelled from billing page' })
      notify('success', 'Cancellation scheduled', 'Access continues until the end of the period.')
      window.location.reload()
    } catch (error) { notify('error', 'Could not cancel', error.message) } finally { setCancelling(false) }
  }

  const provider = billing.data?.provider || subscription.data?.provider || { configured: false, message: '' }
  const current = subscription.data?.subscription

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Billing</div><h1>Subscription and payments</h1><p>Your plan, invoices and purchase history in one place.</p></div>
      </div>

      {!provider.configured && <div className="banner" style={{ marginBottom: 18 }}><AlertTriangle size={17} /><div><b>Payments are not fully configured.</b><br />{provider.message}</div></div>}
      {provider.manual && provider.configured && <div className="banner info" style={{ marginBottom: 18 }}><ClipboardList size={17} /><div><b>Manual invoicing is active.</b><br />Create a checkout, then an administrator records the bank or mobile-money payment before access is granted.</div></div>}

      <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Plan</div><div className="metric-value" style={{ fontSize: 20 }}>{subscription.data?.entitlements?.plan_name || 'Free'}</div><div className="metric-note">{current ? `renews ${dateLabel(current.current_period_end)}` : 'no paid subscription'}</div></div>
        <div className="metric-card"><div className="metric-label">Status</div><div className="metric-value" style={{ fontSize: 20 }}>{current?.status || 'active'}</div><div className="metric-note">{current?.cancel_at_period_end ? 'cancels at period end' : 'no cancellation scheduled'}</div></div>
        <div className="metric-card"><div className="metric-label">Provider</div><div className="metric-value" style={{ fontSize: 20 }}>{provider.label || 'Manual'}</div><div className="metric-note">{provider.configured ? 'configured' : 'awaiting credentials'}</div></div>
        <div className="metric-card"><div className="metric-label">Payments</div><div className="metric-value">{billing.data?.payments?.length ?? 0}</div><div className="metric-note">{billing.data?.purchases?.length ?? 0} purchases</div></div>
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 18 }}>
        <div className="panel-head">
          <div><div className="panel-title">Change plan</div><div className="panel-sub">Personal and team plans are available. Team plans need a workspace.</div></div>
          <Toggle value={interval} onChange={setInterval} options={[{ value: 'month', label: 'Monthly' }, { value: 'year', label: 'Annual' }]} />
        </div>
        {(teams.data?.items || []).length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <Field label="Team workspace (for team plans)"><select className="select" style={{ maxWidth: 360 }} value={teamId} onChange={(event) => setTeamId(event.target.value)}><option value="">Personal subscription</option>{teams.data.items.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}</select></Field>
          </div>
        )}
        <div className="pricing-grid">
          {(plans.filter((plan) => plan.price_cents > 0)).map((plan) => (
            <div className="price-card" key={plan.code}>
              <div className="price-name">{plan.name}</div>
              <div className="price-amount">{money(interval === 'year' ? plan.annual_price_cents : plan.price_cents, plan.currency)} <span>{interval === 'year' ? '/year' : '/month'}</span></div>
              <p className="price-desc">{plan.description}</p>
              <button className="btn btn-primary" disabled={busy} onClick={() => checkout(plan)}>Start checkout</button>
            </div>
          ))}
          {(plans.filter((plan) => plan.price_cents > 0)).length === 0 && <p className="muted small">No paid plans published.</p>}
        </div>
        {current && !current.cancel_at_period_end && (
          <div style={{ marginTop: 16, textAlign: 'right' }}><button className="btn btn-danger btn-sm" disabled={cancelling} onClick={cancel}>{cancelling ? 'Cancelling…' : 'Cancel subscription'}</button></div>
        )}
      </div>

      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">Payment history</div><div className="panel-sub">Invoices and payment status</div></div></div>
          <div className="activity">
            {(billing.data?.payments || []).map((payment) => (
              <div className="activity-row" key={payment.id}>
                <span className="activity-icon"><CircleDollarSign size={14} /></span>
                <div><b>{money(payment.amount_cents, payment.currency)}</b><span>{payment.reference} · {payment.purpose}</span></div>
                <Pill tone={payment.status === 'paid' ? 'green' : payment.status === 'refunded' ? 'red' : 'amber'}>{payment.status}</Pill>
                <time>{dateLabel(payment.created_at)}</time>
              </div>
            ))}
            {(!billing.data?.payments || billing.data.payments.length === 0) && <p className="muted small">No payments yet.</p>}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">Marketplace purchases</div><div className="panel-sub">Premium skill licences</div></div></div>
          <div className="activity">
            {(billing.data?.purchases || []).map((purchase) => (
              <div className="activity-row" key={purchase.id}>
                <span className="activity-icon"><Package size={14} /></span>
                <div><b>{purchase.amount_cents ? money(purchase.amount_cents, purchase.currency) : 'Free'}</b><span>{purchase.listing_id}</span></div>
                <Pill tone={purchase.status === 'paid' ? 'green' : 'amber'}>{purchase.status}</Pill>
                <time>{dateLabel(purchase.created_at)}</time>
              </div>
            ))}
            {(!billing.data?.purchases || billing.data.purchases.length === 0) && <p className="muted small">No marketplace purchases yet.</p>}
          </div>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <div><div className="panel-title">Payment methods</div><div className="panel-sub">Providers are visible here as soon as they are supported. Ones awaiting credentials cannot be selected for checkout.</div></div>
        </div>
        <div className="status-grid">
          {(billing.data?.providers || []).map((item) => (
            <div className={`status-item ${item.configured || item.active ? '' : 'warn'}`} key={item.provider}>
              {item.configured || item.active ? <CheckCircle2 size={15} /> : <Clock size={15} />}
              <div>
                <b>{item.label}{item.active ? ' · active' : ''}</b>
                <span>{item.configured ? item.description : `${item.description} Awaiting credentials.`}</span>
              </div>
              <div style={{ marginLeft: 'auto' }}>
                <Pill tone={item.configured || item.active ? 'green' : 'amber'}>{item.status}</Pill>
              </div>
            </div>
          ))}
          {(billing.data?.providers || []).length === 0 && <p className="muted small">Payment providers are not published.</p>}
        </div>
      </div>
    </div>
  )
}

function UsagePage({ navigate, onSelect }) {
  const usage = useLoad(() => get('/api/v1/account/usage'), [])
  const max = Math.max(1, ...(usage.data?.series || []).map((item) => item.retrievals))
  const stats = usage.data?.stats || {}
  const total = usage.data?.skills_retrieved ?? stats.retrievals_success ?? 0
  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Usage</div><h1>Retrieval analytics</h1><p>See which skills your agents actually use and where they come from.</p></div>
      </div>
      {usage.error && (
        <div className="banner" style={{ marginBottom: 18 }}>
          <AlertTriangle size={16} />
          <div>
            <b>Usage analytics could not load.</b>{' '}
            {usage.error?.status === 401 ? 'Your browser session was not accepted. Reload and sign in again.' : 'The gateway request failed. Check the connection and reload.'}
            <button className="btn btn-outline btn-sm" style={{ marginLeft: 12 }} onClick={() => window.location.reload()}>Reload</button>
          </div>
        </div>
      )}
      <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Total retrievals</div><div className="metric-value">{total}</div></div>
        <div className="metric-card"><div className="metric-label">MCP</div><div className="metric-value">{usage.data?.by_source?.mcp ?? stats.retrievals_success ?? 0}</div></div>
        <div className="metric-card"><div className="metric-label">REST</div><div className="metric-value">{usage.data?.by_source?.api ?? 0}</div></div>
        <div className="metric-card"><div className="metric-label">Web</div><div className="metric-value">{usage.data?.by_source?.web ?? 0}</div></div>
        <div className="metric-card"><div className="metric-label">Searches executed</div><div className="metric-value">{stats.searches_executed ?? 0}</div></div>
<div className="metric-card"><div className="metric-label">Searches failed</div><div className="metric-value">{stats.searches_failed ?? 0}</div></div>
        <div className="metric-card"><div className="metric-label">Discovery runs</div><div className="metric-value">{stats.discovered ?? 0}</div></div>
<div className="metric-card"><div className="metric-label">Discovery failed</div><div className="metric-value">{stats.discovered_failed ?? 0}</div></div>
        <div className="metric-card"><div className="metric-label">Retrievals failed</div><div className="metric-value">{stats.retrievals_failed ?? 0}</div></div>
<div className="metric-card"><div className="metric-label">Executed</div><div className="metric-value">{stats.executions ?? 0}</div></div>
<div className="metric-card"><div className="metric-label">Executed failed</div><div className="metric-value">{stats.executions_failed ?? 0}</div></div>
      </div>
      <div className="panel panel-pad">
        <div className="panel-head"><div><div className="panel-title">Daily retrievals</div><div className="panel-sub">Last 14 days</div></div></div>
        {usage.loading ? <Loading /> : (
          <div className="chart">
            {(usage.data?.series || []).map((item) => (
              <div className="chart-col" key={item.date}>
                <div className={`chart-bar ${item.retrievals ? '' : 'zero'}`} style={{ height: `${Math.max(4, (item.retrievals / max) * 130)}px` }} />
                <span className="chart-label">{item.date.slice(5)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head"><div><div className="panel-title">Recent activity</div></div></div>
        <div className="activity">
          {(usage.data?.items || []).map((item, index) => (
            <div className="activity-row" key={index}>
              <span className="activity-icon"><Zap size={14} /></span>
              <div><b>{eventLabel(item.event)}</b><span>{eventDetail(item)}</span></div>
              <Pill tone="cyan">{item.source}</Pill>
              <time>{relativeLabel(item.created_at)}</time>
            </div>
          ))}
          {(!usage.data?.items || usage.data.items.length === 0) && <p className="muted small">No retrieval activity yet.</p>}
        </div>
      </div>
    </div>
  )
}

function ExecutionConsole({ navigate, notify }) {
  const skills = useLoad(() => get('/api/v1/skills/search?limit=50'), [])
  const entitlements = useLoad(() => get('/api/v1/account/entitlements'), [])
  const [skill, setSkill] = useState('')
  const [packageData, setPackageData] = useState(null)
  const [script, setScript] = useState('')
  const [runtime, setRuntime] = useState('python3')
  const [args, setArgs] = useState('')
  const [timeoutSeconds, setTimeoutSeconds] = useState(120)
  const [memoryMb, setMemoryMb] = useState(1024)
  const [cpuMillicores, setCpuMillicores] = useState(1000)
  const [network, setNetwork] = useState(false)
  const [teamId, setTeamId] = useState('')
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [loadingPackage, setLoadingPackage] = useState(false)
  const [fileFilter, setFileFilter] = useState('')
  const [historyPage, setHistoryPage] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)

  const history = useLoad(() => {
    const params = new URLSearchParams({ limit: '20', offset: String(historyPage * 20) })
    if (statusFilter) params.set('status', statusFilter)
    return get(`/api/v1/executions?${params}`)
  }, [historyPage, statusFilter, refreshKey])

  const loadPackage = async (slug) => {
    setSkill(slug); setPackageData(null); setScript(''); setJob(null); setFileFilter('')
    if (!slug) return
    setLoadingPackage(true)
    try {
      const data = await get(`/api/v1/skills/${encodeURIComponent(slug)}/package`)
      setPackageData(data)
      if (data.groups?.scripts?.length) setScript(data.groups.scripts[0])
      else if (data.groups?.entrypoints?.length) setScript(data.groups.entrypoints[0])
      const ext = (data.groups?.scripts?.[0] || '').split('.').pop()
      setRuntime(ext === 'js' || ext === 'mjs' || ext === 'cjs' ? 'node' : ext === 'sh' || ext === 'bash' ? 'bash' : 'python3')
    } catch (error) { notify('error', 'Could not load package', error.message) }
    finally { setLoadingPackage(false) }
  }

  const run = async (event) => {
    event.preventDefault()
    if (!skill || !script) return
    setBusy(true); setJob(null)
    try {
      const created = await post('/api/v1/executions', {
        skill, team_id: teamId || undefined, command: runtime,
        arguments: [script, ...tokenizeArgs(args)],
        timeout_seconds: timeoutSeconds, max_memory_mb: memoryMb,
        max_cpu_millicores: cpuMillicores, network,
      })
      setJob(created)
      notify('success', 'Execution queued', created.id)
      setHistoryPage(0); setRefreshKey((value) => value + 1)
    } catch (error) { notify('error', 'Could not start execution', error.message) }
    finally { setBusy(false) }
  }

  const cancel = async () => {
    if (!job) return
    try {
      const updated = await post(`/api/v1/executions/${job.id}/cancel`, {})
      setJob(updated)
      notify('success', 'Execution canceled', job.id)
      setRefreshKey((value) => value + 1)
    } catch (error) { notify('error', 'Could not cancel', error.message) }
  }

  useEffect(() => {
    if (!job || ['succeeded', 'failed', 'canceled'].includes(job.status)) return undefined
    const timer = window.setInterval(async () => {
      try { setJob(await get(`/api/v1/executions/${job.id}`)) } catch { /* keep last state */ }
    }, 1000)
    return () => window.clearInterval(timer)
  }, [job?.id, job?.status])

  useEffect(() => {
    if (job && ['succeeded', 'failed', 'canceled'].includes(job.status)) {
      setRefreshKey((value) => value + 1)
    }
  }, [job?.status])

  const coverage = packageData?.statistics_bundle_coverage || {}
  const files = (packageData?.manifest || []).filter((item) =>
    !fileFilter || item.path.toLowerCase().includes(fileFilter.toLowerCase()))
  const downloadUrl = skill ? `/api/v1/skills/${encodeURIComponent(skill)}/package.zip` : '#'
  const quota = entitlements.data?.execution_quota || { limit: 0, used: 0, remaining: 0 }
  const skillNames = Object.fromEntries((skills.data?.items || []).map((item) => [item.id, item.name]))
  const teams = entitlements.data?.teams || []
  const historyItems = history.data?.items || []
  const totalHistory = history.data?.total || 0

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="section-eyebrow">Execution console</div>
          <h1>Run skill packages safely</h1>
          <p>Read the complete immutable package, then run approved Python, Node.js or shell scripts in a temporary, isolated container.</p>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric-card"><div className="metric-label">Daily quota</div><div className="metric-value">{quota.limit}</div><div className="metric-note">{quota.plan_code || 'plan'} executions</div></div>
        <div className="metric-card"><div className="metric-label">Used today</div><div className="metric-value">{quota.used}</div><div className="metric-note">{quota.remaining} remaining</div></div>
      </div>

      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">1. Choose an approved skill</div><div className="panel-sub">Every file is pinned to the exact SkillVault version.</div></div></div>
          <label className="field"><span className="label">Skill</span>
            <select className="select" value={skill} onChange={(event) => loadPackage(event.target.value)} disabled={skills.loading}>
              <option value="">{skills.loading ? 'Loading skills…' : 'Select a skill'}</option>
              {(skills.data?.items || []).map((item) => (
                <option key={item.id} value={item.slug}>{item.name} — {item.category || 'General'}</option>
              ))}
            </select>
          </label>
          {loadingPackage ? <Loading /> : packageData && (
            <div style={{ marginTop: 14 }}>
              <div className="status-grid">
                <div className="status-item"><Package size={15} /><div><b>{packageData.manifest.length}</b><span>files</span></div></div>
                <div className="status-item"><Code2 size={15} /><div><b>{coverage.scripts || 0}</b><span>scripts</span></div></div>
                <div className="status-item"><Database size={15} /><div><b>{coverage.datasets || 0}</b><span>datasets</span></div></div>
                <div className="status-item"><ShieldCheck size={15} /><div><b>{packageData.version}</b><span>immutable version</span></div></div>
              </div>
              <p className="muted small" style={{ marginTop: 12 }}>
                Version hash <code>{packageData.version_hash?.slice(0, 18)}…</code> · Workspace <code>{packageData.workspace_path}</code>
              </p>
              <a className="btn btn-outline btn-sm" href={downloadUrl} style={{ marginTop: 10 }}><Download size={14} /> Download full package ZIP</a>
            </div>
          )}
        </div>

        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">2. Run a script</div><div className="panel-sub">Approved runtimes only. No network unless explicitly enabled.</div></div></div>
          <form onSubmit={run}>
            <div className="field-row">
              <label className="field"><span className="label">Runtime</span>
                <select className="select" value={runtime} onChange={(event) => setRuntime(event.target.value)}>
                  <option value="python3">Python 3</option>
                  <option value="node">Node.js</option>
                  <option value="bash">Bash</option>
                </select>
              </label>
              <label className="field"><span className="label">Workspace</span>
                <select className="select" value={teamId} onChange={(event) => setTeamId(event.target.value)}>
                  <option value="">Personal</option>
                  {teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
                </select>
              </label>
            </div>
            <label className="field" style={{ marginTop: 10 }}><span className="label">Script</span>
              <select className="select" value={script} onChange={(event) => setScript(event.target.value)} disabled={!packageData}>
                <option value="">{packageData ? 'Select a script' : 'Load a skill first'}</option>
                {(packageData?.groups?.scripts || []).map((path) => <option key={path} value={path}>{path}</option>)}
              </select>
            </label>
            <label className="field" style={{ marginTop: 10 }}><span className="label">Arguments (quotes supported)</span>
              <input className="input" value={args} onChange={(event) => setArgs(event.target.value)}
                placeholder={'SaaS technology landing page --design-system'} disabled={!packageData} />
            </label>
            <div className="field-row" style={{ marginTop: 10 }}>
              <label className="field"><span className="label">Timeout (s)</span><input className="input" type="number" min="1" max="600" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(Number(event.target.value))} /></label>
              <label className="field"><span className="label">Memory (MB)</span><input className="input" type="number" min="64" max="4096" value={memoryMb} onChange={(event) => setMemoryMb(Number(event.target.value))} /></label>
              <label className="field"><span className="label">CPU (millicores)</span><input className="input" type="number" min="100" max="4000" step="100" value={cpuMillicores} onChange={(event) => setCpuMillicores(Number(event.target.value))} /></label>
            </div>
            <label className="filter-group" style={{ marginTop: 10 }}><input type="checkbox" checked={network} onChange={(event) => setNetwork(event.target.checked)} /> Allow network</label>
            <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
              <button className="btn btn-primary" disabled={busy || !script}>{busy ? 'Starting…' : 'Run in sandbox'}</button>
              {job && !['succeeded', 'failed', 'canceled'].includes(job.status) && (
                <button type="button" className="btn btn-danger" onClick={cancel}>Cancel</button>
              )}
            </div>
          </form>
          {job && (
            <div style={{ marginTop: 16 }}>
              <div className="status-item"><Activity size={15} /><div><b>{job.status}</b><span>{job.id} · exit {job.exit_code ?? '—'} · {job.metrics?.duration_ms ?? '—'} ms · {job.metrics?.peak_memory_bytes ? Math.round(job.metrics.peak_memory_bytes / 1024 / 1024) + ' MB' : '—'}</span></div></div>
              {job.dependencies?.detected && <p className="muted small" style={{ marginTop: 8 }}>Dependencies: {job.dependencies.locked ? 'locked' : 'unlocked'} · {job.dependencies.install_commands?.length || 0} install step(s)</p>}
              {job.stdout && <pre className="code-block console-output">{job.stdout}</pre>}
              {job.stderr && <pre className="code-block console-output">{job.stderr}</pre>}
              {job.error && <div className="banner" style={{ marginTop: 10 }}>{job.error}</div>}
            </div>
          )}
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <div><div className="panel-title">Execution history</div><div className="panel-sub">Duration, resources, status and errors for every run.</div></div>
          <select className="select" style={{ maxWidth: 180 }} value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setHistoryPage(0) }}>
            <option value="">All statuses</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="canceled">Canceled</option>
            <option value="running">Running</option>
            <option value="queued">Queued</option>
          </select>
        </div>
        {history.loading ? <Loading /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Job</th><th>Skill</th><th>Runtime</th><th>Status</th><th>Duration</th><th>Peak memory</th><th>Exit</th><th>Error</th></tr></thead>
              <tbody>
                {historyItems.map((item) => (
                  <tr key={item.id}>
                    <td className="mono small">{item.id.slice(0, 8)}</td>
                    <td>{skillNames[item.skill_id] || item.skill_id.slice(0, 8)}</td>
                    <td>{item.command}</td>
                    <td><Pill tone={item.status === 'succeeded' ? 'green' : item.status === 'failed' ? 'red' : 'amber'}>{item.status}</Pill></td>
                    <td>{item.metrics?.duration_ms ? `${item.metrics.duration_ms} ms` : '—'}</td>
                    <td>{item.metrics?.peak_memory_bytes ? `${Math.round(item.metrics.peak_memory_bytes / 1024 / 1024)} MB` : '—'}</td>
                    <td>{item.exit_code ?? '—'}</td>
                    <td className="muted small">{item.error?.slice(0, 80) || item.stderr?.slice(0, 80) || '—'}</td>
                  </tr>
                ))}
                {historyItems.length === 0 && <tr><td colSpan="8"><p className="muted small">No executions yet.</p></td></tr>}
              </tbody>
            </table>
          </div>
        )}
        {totalHistory > 20 && <div className="market-pagination"><span className="count-note">Page {historyPage + 1} of {Math.ceil(totalHistory / 20)}</span><div><button className="btn btn-outline btn-sm" disabled={historyPage === 0} onClick={() => setHistoryPage(historyPage - 1)}>Previous</button><button className="btn btn-outline btn-sm" disabled={(historyPage + 1) * 20 >= totalHistory} onClick={() => setHistoryPage(historyPage + 1)}>Next</button></div></div>}
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head">
          <div><div className="panel-title">3. Read every file without running anything</div><div className="panel-sub">Open a file directly or download the verified package.</div></div>
          <input className="input" style={{ maxWidth: 260 }} value={fileFilter} onChange={(event) => setFileFilter(event.target.value)} placeholder="Filter files" />
        </div>
        {!packageData ? <p className="muted small">Select a skill to browse its complete package.</p> : (
          <div className="activity">
            {files.map((item) => {
              const url = `/api/v1/skills/${encodeURIComponent(skill)}/resources/${item.path.split('/').map(encodeURIComponent).join('/')}`
              return (
                <div className="activity-row" key={item.path}>
                  <span className="activity-icon"><FileText size={14} /></span>
                  <div><b>{item.path}</b><span>{item.bytes} bytes · {item.sha256.slice(0, 12)}…</span></div>
                  <a className="btn btn-ghost btn-sm" href={url} target="_blank" rel="noreferrer">Open</a>
                </div>
              )
            })}
            {files.length === 0 && <p className="muted small">No files match “{fileFilter}”.</p>}
          </div>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Integrations and settings                                           */
/* ------------------------------------------------------------------ */

function IntegrationsPage({ user, navigate, notify }) {
  const [name, setName] = useState('Agent MCP')
  const [scopes, setScopes] = useState(['skills:read', 'library:read', 'account:read'])
  const [created, setCreated] = useState('')
  const [copied, setCopied] = useState(false)
  const [refreshKeys, setRefreshKeys] = useState(0)
  const [busy, setBusy] = useState(false)
  const integrations = useLoad(() => get('/api/v1/integrations'), [])
  const keys = useLoad(() => get('/api/v1/auth/api-keys'), [refreshKeys])

  const createKey = async (event) => {
    event.preventDefault(); setBusy(true)
    try {
      const result = await post('/api/v1/auth/api-keys', { name, scopes })
      setCreated(result.api_key)
      notify('success', 'API key created', 'Copy it now - it will not be shown again.')
      setName('Agent MCP'); setBusy(false)
      setRefreshKeys((value) => value + 1)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (error) { notify('error', 'Could not create key', error.message); setBusy(false) }
  }

  const revoke = async (keyId) => {
    try { await del(`/api/v1/auth/api-keys/${keyId}`); notify('success', 'Key revoked', 'The key stopped working immediately.'); setRefreshKeys((value) => value + 1) }
    catch (error) { notify('error', 'Could not revoke', error.message) }
  }

  const mcp = (integrations.data?.items || []).find((item) => item.id === 'mcp')

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Integrations</div><h1>Connect your agent</h1><p>One API key unlocks MCP, REST and the CLI against the same reviewed catalogue.</p></div>
      </div>
      {created && (
        <div className="banner info" style={{ marginBottom: 18 }}>
          <KeyRound size={17} />
          <div style={{ flex: 1 }}><b>Copy your API key now</b><br /><span className="mono small" style={{ userSelect: 'all', wordBreak: 'break-all' }}>{created}</span></div>
          <button className="btn btn-outline btn-sm" onClick={async () => {
            try {
              if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(created)
              } else {
                throw new Error('clipboard unavailable')
              }
              setCopied(true)
              alert('API key copied to clipboard!')
              window.setTimeout(() => setCopied(false), 1600)
            } catch {
              window.prompt('Copy your API key:', created)
            }
          }}><Copy size={13} /> {copied ? 'Copied!' : 'Copy'}</button>
        </div>
      )}
      <div className="grid-2">
        {(integrations.data?.items || []).map((item) => (
          <div className="panel panel-pad" key={item.id}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <span className="feature-icon" style={{ marginBottom: 0, width: 34, height: 34 }}>
                {item.id === 'mcp' ? <Terminal size={16} /> : item.id === 'rest' ? <Code2 size={16} /> : item.id === 'cli' ? <Terminal size={16} /> : <Github size={16} />}
              </span>
              <div><b>{item.name}</b><div className="dim small">{item.description}</div></div>
              <div style={{ marginLeft: 'auto' }}><Pill tone={item.status === 'available' ? 'green' : 'amber'}>{item.status}</Pill></div>
            </div>
            {item.endpoint && (
              <div className="copy-row">
                <div className="code-block">{item.endpoint}</div>
                <button className="icon-btn" onClick={() => copy(item.endpoint)} title="Copy endpoint"><Copy size={14} /></button>
              </div>
            )}
            {item.config && (
              <div className="code-block">{JSON.stringify(item.config, null, 2)}</div>
            )}
            {item.commands && (
              <div className="code-block">{item.commands.join('\n')}</div>
            )}
          </div>
        ))}
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-head"><div><div className="panel-title">API keys</div><div className="panel-sub">Keys are hashed at rest and can be revoked at any time.</div><div className="panel-sub" style={{ color: '#fbbf24', marginTop: 4 }}>The full key is shown only once, in the banner above, right after creation. If you lose it, revoke the key and create a new one.</div></div></div>
        <form onSubmit={createKey} className="toolbar" style={{ marginBottom: 18 }}>
          <input className="input" style={{ maxWidth: 220 }} value={name} onChange={(event) => setName(event.target.value)} placeholder="Key name" />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', maxWidth: 640 }}>
            {API_KEY_SCOPES.map((scope) => (
              <label className="filter-group" key={scope} title={scope === 'execution:run' ? 'Required for execute_skill_script' : undefined}>
                <input
                  type="checkbox"
                  checked={scopes.includes(scope)}
                  onChange={() => setScopes((current) => current.includes(scope)
                    ? current.filter((item) => item !== scope)
                    : [...current, scope])}
                />{' '}{scope}
              </label>
            ))}
          </div>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Creating…' : 'Create key'}</button>
        </form>
        <p className="muted small" style={{ marginTop: -8, marginBottom: 14 }}>
          Tick <code>execution:run</code> to use <code>execute_skill_script</code>. Read-only keys with only <code>skills:read</code> can list and retrieve files but cannot run scripts.
        </p>
        <div className="activity">
          {(keys.data?.items || []).map((key) => (
            <div className="activity-row" key={key.id}>
              <span className="activity-icon"><KeyRound size={14} /></span>
              <div><b>{key.name}</b><span>{key.prefix}… · {key.scopes.join(', ')}</span></div>
              <span className="dim tiny">last used {relativeLabel(key.last_used_at)}</span>
              <button className="btn btn-danger btn-sm" onClick={() => revoke(key.id)}>Revoke</button>
            </div>
          ))}
          {(!keys.data?.items || keys.data.items.length === 0) && <p className="muted small">No active API keys.</p>}
        </div>
      </div>
    </div>
  )
}

function SettingsPage({ user, route, setUser, notify, onSignOut }) {
  const [tab, setTab] = useState(route.query.tab || 'profile')
  const [profile, setProfile] = useState({ name: user.name || '' })
  const [passwords, setPasswords] = useState({ current_password: '', new_password: '' })
  const [notifications, setNotifications] = useState([])
  const [busy, setBusy] = useState(false)

  useEffect(() => { get('/api/v1/account/notifications').then((data) => setNotifications(data.items || [])).catch(() => {}) }, [])

  const saveProfile = async (event) => {
    event.preventDefault(); setBusy(true)
    try {
      const result = await patch('/api/v1/account/profile', profile)
      setUser(result.user); notify('success', 'Profile saved', result.user.name || result.user.email)
    } catch (error) { notify('error', 'Could not save profile', error.message) } finally { setBusy(false) }
  }

  const changePassword = async (event) => {
    event.preventDefault(); setBusy(true)
    try {
      await post('/api/v1/account/change-password', passwords)
      notify('success', 'Password changed', 'Other sessions and API keys were revoked.')
      setPasswords({ current_password: '', new_password: '' })
    } catch (error) { notify('error', 'Could not change password', error.message) } finally { setBusy(false) }
  }

  const markRead = async (id) => {
    await post(`/api/v1/account/notifications/${id}/read`, {})
    setNotifications((items) => items.map((item) => item.id === id ? { ...item, read: true } : item))
  }

  const removeAccount = async () => {
    const password = window.prompt('Enter your password to deactivate the account:')
    if (!password) return
    try {
      await post('/api/v1/account/delete', { password })
      onSignOut()
    } catch (error) { notify('error', 'Could not deactivate', error.message) }
  }

  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Settings</div><h1>Account settings</h1><p>Your profile, security, notifications and data controls.</p></div>
      </div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {[['profile', 'Profile'], ['security', 'Security'], ['notifications', 'Notifications']].map(([key, label]) => (
          <button key={key} className={`tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>

      {tab === 'profile' && (
        <div className="panel panel-pad" style={{ maxWidth: 620 }}>
          <form onSubmit={saveProfile}>
            <Field label="Name"><input className="input" value={profile.name} onChange={(event) => setProfile({ name: event.target.value })} /></Field>
            <Field label="Email"><input className="input" value={user.email} disabled /><div className="form-note">{user.email_verified ? 'Email verified' : 'Email not verified. Check your inbox or ask an administrator.'}</div></Field>
            <Field label="Role"><input className="input" value={user.role} disabled /></Field>
            <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save profile'}</button>
          </form>
        </div>
      )}

      {tab === 'security' && (
        <div className="grid-2" style={{ maxWidth: 900 }}>
          <div className="panel panel-pad">
            <form onSubmit={changePassword}>
              <Field label="Current password"><input className="input" type="password" required value={passwords.current_password} onChange={(event) => setPasswords({ ...passwords, current_password: event.target.value })} /></Field>
              <Field label="New password"><input className="input" type="password" required minLength={12} value={passwords.new_password} onChange={(event) => setPasswords({ ...passwords, new_password: event.target.value })} /></Field>
              <button className="btn btn-primary" disabled={busy}>Change password</button>
            </form>
          </div>
          <div className="panel panel-pad">
            <div className="panel-title" style={{ marginBottom: 8 }}>Danger zone</div>
            <p className="muted small" style={{ marginBottom: 14 }}>Deactivating your account revokes sessions and API keys. Marketplace purchases remain in your billing history.</p>
            <button className="btn btn-danger" onClick={removeAccount}>Deactivate account</button>
          </div>
        </div>
      )}

      {tab === 'notifications' && (
        <div className="panel panel-pad">
          <div className="activity">
            {notifications.map((item) => (
              <div className="activity-row" key={item.id}>
                <span className="activity-icon"><Bell size={14} /></span>
                <div><b>{item.title}</b><span>{item.body}</span></div>
                <span className="dim tiny">{relativeLabel(item.created_at)}</span>
                {!item.read && <button className="btn btn-ghost btn-sm" onClick={() => markRead(item.id)}>Mark read</button>}
              </div>
            ))}
            {notifications.length === 0 && <p className="muted small">No notifications yet.</p>}
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Docs and public information                                         */
/* ------------------------------------------------------------------ */

function DocsPage({ navigate }) {
  const steps = [
    { icon: KeyRound, title: '1. Create a key', body: 'Sign in, verify your email, then create an API key in Integrations. Tick skills:read for access and execution:run to run scripts.' },
    { icon: Search, title: '2. Discover skills', body: 'Ask your agent to search the reviewed catalogue. Results come from live SkillVault snapshots with licence and security metadata.' },
    { icon: Terminal, title: '3. Retrieve or execute', body: 'Read complete packages without installing them, or run approved scripts in a temporary, network-isolated sandbox.' },
  ]
  const tools = [
    ['search_skills', 'Find skills by task, category or community.'],
    ['get_skill', 'Retrieve full instructions and the resource manifest.'],
    ['resolve_skill_package', 'Resolve the complete immutable package and dependency plan.'],
    ['retrieve_skill_file', 'Read any exact file with its verified SHA-256.'],
    ['execute_skill_script', 'Run approved Python, Node or shell scripts in a sandbox.'],
    ['get_execution_status', 'Poll a queued or running job.'],
    ['retrieve_execution_result', 'Get stdout, stderr, exit code and resource metrics.'],
  ]
  return (
    <main className="docs-page">
      <div className="page-head">
        <div>
          <div className="section-eyebrow">Documentation</div>
          <h1>Build with AgentDock</h1>
          <p>Reviewed skills for your agent. Discover, retrieve and run complete packages through MCP, REST or the CLI — without permanent installation.</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/developers')}><Terminal size={15} /> Developer reference</button>
      </div>

      <div className="feature-grid" style={{ marginBottom: 18 }}>
        {steps.map(({ icon: Icon, title, body }) => (
          <div className="panel panel-pad" key={title}>
            <span className="feature-icon" style={{ marginBottom: 12 }}><Icon size={18} /></span>
            <h3 style={{ fontSize: 16, marginBottom: 8 }}>{title}</h3>
            <p className="muted small" style={{ lineHeight: 1.7 }}>{body}</p>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="panel-title" style={{ marginBottom: 10 }}>Connect MCP</div>
          <p className="muted small">Add this to your MCP client. Replace the key with one from Integrations.</p>
          <div className="code-block">{`{
  "mcpServers": {
    "agentdock": {
      "url": "https://agentdock.link/mcp",
      "headers": { "Authorization": "Bearer adk_..." }
    }
  }
}`}</div>
          <p className="muted small">Required scopes: <code>skills:read</code>. Add <code>execution:run</code> for script execution.</p>
        </div>
        <div className="panel panel-pad">
          <div className="panel-title" style={{ marginBottom: 10 }}>Use the CLI</div>
          <p className="muted small">The CLI talks to the same gateway as MCP and REST.</p>
          <div className="code-block">{`agentdock login --url https://agentdock.link
agentdock search "postgres performance"
agentdock get postgres-performance
agentdock connect mcp`}</div>
          <p className="muted small">Retrieval prints instructions on demand; it does not permanently install a skill.</p>
        </div>
      </div>

      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-title" style={{ marginBottom: 12 }}>Core MCP tools</div>
        <div className="status-grid">
          {tools.map(([name, body]) => (
            <div className="status-item" key={name}><Terminal size={14} /><div><b className="mono">{name}</b><span>{body}</span></div></div>
          ))}
        </div>
        <p className="muted small" style={{ marginTop: 12 }}>Full tool list, input schemas and argument validation are available from <code>tools/list</code>.</p>
      </div>

      <div className="grid-2" style={{ marginTop: 18 }}>
        <div className="panel panel-pad">
          <div className="panel-title" style={{ marginBottom: 10 }}>REST endpoints</div>
          <p className="muted small">Interactive OpenAPI reference: <code>/api/docs</code>.</p>
          <div className="code-block">{`GET  /api/v1/skills/search
POST /api/v1/skills/{id}/retrieve
GET  /api/v1/skills/{id}/package
POST /api/v1/executions
GET  /api/v1/executions
GET  /api/v1/marketplace/listings
GET  /api/v1/account/entitlements`}</div>
        </div>
        <div className="panel panel-pad">
          <div className="panel-title" style={{ marginBottom: 10 }}>Governance and quotas</div>
          <p className="muted small">Every snapshot is immutable, hash-verified and attributed. Administrators review admission, licences, security scans and rights requests in the Control Center.</p>
          <p className="muted small">Execution is sandboxed, network-off by default and limited by per-job CPU/memory/time settings. Daily quotas come from your active plan.</p>
          <div className="status-grid" style={{ marginTop: 12 }}>
            <div className="status-item"><ShieldCheck size={14} /><div><b>Security reviewed</b><span>only clear packages execute</span></div></div>
            <div className="status-item"><Database size={14} /><div><b>Immutable versions</b><span>pinned by content hash</span></div></div>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 28, display: 'flex', gap: 10 }}>
        <button className="btn btn-primary" onClick={() => navigate('/developers')}>Developer reference</button>
        <button className="btn btn-outline" onClick={() => navigate('/register')}>Create a workspace</button>
      </div>
    </main>
  )
}

function DevelopersPage({ navigate }) {
  const tools = [
    ['search_skills', 'Find reviewed skills by task, category or community.'],
    ['get_skill', 'Retrieve full instructions and the resource manifest.'],
    ['get_skill_resource', 'Read one file from a pinned snapshot.'],
    ['resolve_skill_package', 'Resolve the complete immutable package and dependency plan.'],
    ['list_skill_files', 'List every file with SHA-256 and byte size.'],
    ['retrieve_skill_file', 'Read any exact file, base64 encoded.'],
    ['execute_skill_script', 'Run an approved Python, Node or shell script in a sandbox.'],
    ['get_execution_status', 'Poll a queued or running execution.'],
    ['retrieve_execution_result', 'Read stdout, stderr, exit code and resource metrics.'],
    ['cancel_execution', 'Cancel a queued or running execution.'],
    ['list_skill_versions', 'List immutable versions of a skill.'],
    ['browse_marketplace', 'Browse approved free and premium listings.'],
    ['check_subscription', 'Read the plan, entitlements, teams and quota.'],
    ['save_skill_to_collection', 'Save a skill to a personal collection.'],
  ]
  return (
    <main className="docs-page">
      <div className="page-head">
        <div>
          <div className="section-eyebrow">Developers</div>
          <h1>One catalogue, three surfaces</h1>
          <p>MCP for agents, REST for applications, CLI for humans. Authentication is a bearer API key in every case.</p>
        </div>
      </div>
      <div className="panel panel-pad">
        <div className="panel-title" style={{ marginBottom: 12 }}>MCP tools</div>
        <div className="list">
          {tools.map(([name, body]) => (
            <div className="list-row" key={name}><span className="activity-icon"><Terminal size={14} /></span><div className="list-row-main"><b className="mono">{name}</b><span>{body}</span></div></div>
          ))}
        </div>
      </div>
      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-title" style={{ marginBottom: 10 }}>CLI</div>
        <div className="code-block">{`pip install agentdock
agentdock login --url https://agentdock.link
agentdock search "react dashboard"
agentdock get react-analytics-dashboard
agentdock connect mcp`}</div>
      </div>
      <div className="panel panel-pad" style={{ marginTop: 18 }}>
        <div className="panel-title" style={{ marginBottom: 10 }}>Execution and safety</div>
        <p className="muted small">Execution tools require the <code>execution:run</code> scope. Jobs are network-disabled by default, use per-job CPU/memory/time limits and run in a temporary workspace that is always cleaned up. Daily quotas come from the active plan and team workspace.</p>
        <p className="muted small">Requests are limited per client and authentication attempts are limited more tightly. Webhooks must present a valid provider or GitHub signature before any entitlement changes.</p>
      </div>
      <div style={{ marginTop: 28 }}><button className="btn btn-primary" onClick={() => navigate('/integrations')}>Create an API key</button></div>
    </main>
  )
}

function RightsPage({ navigate, notify }) {
  const [form, setForm] = useState({ requester_name: '', requester_email: '', repository_url: '', claim_type: 'takedown', details: '' })
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const submit = async (event) => {
    event.preventDefault(); setBusy(true)
    try {
      await post('/api/v1/rights-requests', form)
      setDone(true); notify('success', 'Request received', 'Our review team will respond before further distribution.')
    } catch (error) { notify('error', 'Could not submit', error.message) } finally { setBusy(false) }
  }
  return (
    <main className="legal">
      <div className="section-eyebrow">Rights and takedowns</div>
      <h1>Report a rights concern</h1>
      <p>We take copyright, licence and privacy claims seriously. Submitting a request opens a tracked review; distribution can be suspended while we investigate.</p>
      {done ? (
        <div className="panel panel-pad" style={{ marginTop: 24 }}><div className="auth-success"><div className="feature-icon"><CheckCircle2 size={22} /></div><h1>Request received</h1><p className="muted">Reference sent to {form.requester_email}.</p></div></div>
      ) : (
        <form className="panel panel-pad" style={{ marginTop: 24, maxWidth: 680 }} onSubmit={submit}>
          <div className="field-row">
            <Field label="Your name"><input className="input" required value={form.requester_name} onChange={(event) => setForm({ ...form, requester_name: event.target.value })} /></Field>
            <Field label="Email"><input className="input" type="email" required value={form.requester_email} onChange={(event) => setForm({ ...form, requester_email: event.target.value })} /></Field>
          </div>
          <Field label="Repository or skill URL"><input className="input" value={form.repository_url} onChange={(event) => setForm({ ...form, repository_url: event.target.value })} placeholder="https://github.com/…" /></Field>
          <Field label="Claim type">
            <select className="select" value={form.claim_type} onChange={(event) => setForm({ ...form, claim_type: event.target.value })}>
              <option value="takedown">Takedown request</option><option value="copyright">Copyright</option><option value="licence">Licence violation</option><option value="privacy">Privacy</option><option value="other">Other</option>
            </select>
          </Field>
          <Field label="Details"><textarea className="textarea" required minLength={20} value={form.details} onChange={(event) => setForm({ ...form, details: event.target.value })} placeholder="Describe the content, your ownership and the remedy you need." /></Field>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Submitting…' : 'Submit request'}</button>
        </form>
      )}
      <div style={{ marginTop: 24 }}><button className="btn btn-ghost" onClick={() => navigate('/')}>Back home</button></div>
    </main>
  )
}

/* ------------------------------------------------------------------ */
/* Administration                                                      */
/* ------------------------------------------------------------------ */

const ADMIN_TABS = [
  ['overview', 'Overview', LayoutDashboard], ['moderation', 'Moderation', ShieldCheck], ['marketplace', 'Marketplace', Package],
  ['creators', 'Creators', Sparkles], ['billing', 'Billing', CircleDollarSign], ['users', 'Users', Users],
  ['rights', 'Rights', FileText], ['imports', 'Imports', Upload], ['repositories', 'Repositories', Database],
  ['discovery', 'Discovery', Globe], ['security', 'Security', Shield], ['settings', 'Settings', Settings], ['audit', 'Audit', ClipboardList],
]

function AdminPage({ tab, setTab, notify }) {
  const analytics = useLoad(() => get('/api/v1/admin/analytics'), [tab])
  return (
    <div>
      <div className="page-head">
        <div><div className="section-eyebrow">Administration</div><h1>Control center</h1><p>Catalogue quality, revenue, rights and platform configuration in one place.</p></div>
      </div>
      <div className="admin-tabs">
        {ADMIN_TABS.map(([key, label, Icon]) => (
          <button key={key} className={`admin-tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}><Icon size={14} /> {label}</button>
        ))}
      </div>
      {tab === 'overview' && <AdminOverview analytics={analytics} />}
      {tab === 'moderation' && <AdminModeration notify={notify} />}
      {tab === 'marketplace' && <AdminMarketplace notify={notify} />}
      {tab === 'creators' && <AdminCreators notify={notify} />}
      {tab === 'billing' && <AdminBilling notify={notify} />}
      {tab === 'users' && <AdminUsers notify={notify} />}
      {tab === 'rights' && <AdminRights notify={notify} />}
      {tab === 'imports' && <AdminImports />}
      {tab === 'repositories' && <AdminRepositories notify={notify} />}
      {tab === 'discovery' && <AdminDiscovery notify={notify} />}
      {tab === 'security' && <AdminSecurity />}
      {tab === 'settings' && <AdminSettings notify={notify} />}
      {tab === 'audit' && <AdminAudit />}
    </div>
  )
}

function AdminOverview({ analytics }) {
  const data = analytics.data
  const max = Math.max(1, ...(data?.series || []).map((item) => Math.max(item.retrievals, item.signups)))
  return (
    <div>
      {analytics.loading ? <Loading /> : (
        <>
          <div className="admin-grid">
            <div className="admin-kpi"><span>Net revenue</span><strong>{money(data.revenue.net_cents, data.revenue.currency)}</strong><small>{money(data.revenue.gross_cents, data.revenue.currency)} gross</small></div>
            <div className="admin-kpi"><span>MRR</span><strong>{money(data.revenue.mrr_cents, data.revenue.currency)}</strong><small>{data.subscriptions.active} active subscriptions</small></div>
            <div className="admin-kpi"><span>Marketplace GMV</span><strong>{money(data.revenue.marketplace_gmv_cents, data.revenue.currency)}</strong><small>{money(data.revenue.commission_cents, data.revenue.currency)} commission</small></div>
            <div className="admin-kpi"><span>Total users</span><strong>{data.users.total}</strong><small>{data.users.new_30d} new in 30 days</small></div>
            <div className="admin-kpi"><span>Active users</span><strong>{data.users.active}</strong><small>{data.users.verified} verified</small></div>
            <div className="admin-kpi"><span>Workspaces</span><strong>{data.workspaces.total}</strong><small>{data.workspaces.active} with members</small></div>
            <div className="admin-kpi"><span>Approved skills</span><strong>{data.catalogue.approved}</strong><small>{data.catalogue.pending} pending approval</small></div>
            <div className="admin-kpi"><span>Failed jobs</span><strong>{data.operations.failed_jobs}</strong><small>{data.operations.queued_jobs} queued · {data.operations.running_jobs} running</small></div>
            <div className="admin-kpi"><span>API requests</span><strong>{data.operations.api_requests}</strong><small>{data.operations.mcp_requests} MCP requests</small></div>
            <div className="admin-kpi"><span>Security alerts</span><strong>{data.operations.security_findings}</strong><small>{data.operations.open_rights} open rights</small></div>
          </div>
          <div className="grid-2">
            <div className="panel panel-pad">
              <div className="panel-head"><div><div className="panel-title">Retrievals and signups</div><div className="panel-sub">Last 14 days</div></div></div>
              <div className="chart">
                {(data.series || []).map((item) => (
                  <div className="chart-col" key={item.date}>
                    <div className="chart-bar" style={{ height: `${Math.max(4, (item.retrievals / max) * 120)}px` }} title={`${item.retrievals} retrievals`} />
                    <span className="chart-label">{item.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel panel-pad">
              <div className="panel-head"><div><div className="panel-title">Catalogue health</div><div className="panel-sub">Review pipeline and distribution</div></div></div>
              <div className="status-grid">
                <div className="status-item"><Package size={15} /><div><b>{data.catalogue.approved}</b><span>approved skills</span></div></div>
                <div className="status-item warn"><Clock size={15} /><div><b>{data.catalogue.pending}</b><span>pending review</span></div></div>
                <div className="status-item warn"><AlertTriangle size={15} /><div><b>{data.catalogue.quarantined}</b><span>quarantined</span></div></div>
                <div className="status-item"><Shield size={15} /><div><b>{data.operations.security_findings}</b><span>security findings</span></div></div>
                <div className="status-item"><Activity size={15} /><div><b>{data.operations.sync_health}</b><span>synchronization health</span></div></div>
                <div className="status-item"><Database size={15} /><div><b>{data.operations.total_events}</b><span>tracked platform events</span></div></div>
              </div>
            </div>
          </div>
          <div className="grid-2" style={{ marginTop: 18 }}>
            <div className="panel panel-pad">
              <div className="panel-head"><div><div className="panel-title">Recent users</div><div className="panel-sub">Latest registrations</div></div></div>
              <div className="activity">
                {(data.recent_users || []).map((user) => (
                  <div className="activity-row" key={user.id}>
                    <span className="activity-icon"><Users size={14} /></span>
                    <div><b>{user.name || user.email}</b><span>{user.email} · {user.role}</span></div>
                    <time>{relativeLabel(user.created_at)}</time>
                  </div>
                ))}
                {(!data.recent_users || data.recent_users.length === 0) && <p className="muted small">No users yet.</p>}
              </div>
            </div>
            <div className="panel panel-pad">
              <div className="panel-head"><div><div className="panel-title">Recent payments</div><div className="panel-sub">Latest billing events</div></div></div>
              <div className="activity">
                {(data.recent_payments || []).map((payment) => (
                  <div className="activity-row" key={payment.id}>
                    <span className="activity-icon"><CreditCardIcon size={14} /></span>
                    <div><b>{money(payment.amount_cents, payment.currency)}</b><span>{payment.purpose} · {payment.status} · {payment.provider}</span></div>
                    <time>{relativeLabel(payment.created_at)}</time>
                  </div>
                ))}
                {(!data.recent_payments || data.recent_payments.length === 0) && <p className="muted small">No payments yet.</p>}
              </div>
            </div>
          </div>
          <div className="grid-2" style={{ marginTop: 18 }}>
            <div className="panel panel-pad">
              <div className="panel-head"><div><div className="panel-title">Skill approval decisions</div><div className="panel-sub">Latest moderation actions</div></div></div>
              <div className="activity">
                {(data.recent_decisions || []).map((decision, index) => (
                  <div className="activity-row" key={index}>
                    <span className="activity-icon"><Shield size={14} /></span>
                    <div><b>{decision.skill}</b><span>{decision.decision} · {decision.reason}</span></div>
                    <time>{relativeLabel(decision.created_at)}</time>
                  </div>
                ))}
                {(!data.recent_decisions || data.recent_decisions.length === 0) && <p className="muted small">No decisions yet.</p>}
              </div>
            </div>
            <div className="panel panel-pad">
              <div className="panel-head"><div><div className="panel-title">Synchronization jobs</div><div className="panel-sub">Latest repository sync events</div></div></div>
              <div className="activity">
                {(data.recent_sync_jobs || []).map((job) => (
                  <div className="activity-row" key={job.id}>
                    <span className="activity-icon"><RefreshCw size={14} /></span>
                    <div><b>{job.status}</b><span>{job.repository_id || 'repository'}{job.error ? ' · ' + job.error : ''}</span></div>
                    <time>{relativeLabel(job.completed_at || job.started_at)}</time>
                  </div>
                ))}
                {(!data.recent_sync_jobs || data.recent_sync_jobs.length === 0) && <p className="muted small">No sync jobs yet.</p>}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AdminModeration({ notify }) {
  const [status, setStatus] = useState('pending_review')
  const skills = useLoad(() => get(`/api/v1/admin/skills?status=${status}`), [status])
  const decide = async (skill, decision) => {
    const reason = window.prompt(decision === 'approved' ? 'Reason (licence and quality check):' : 'Reason for ' + decision + ':')
    if (!reason || reason.trim().length < 4) return
    try {
      await post(`/api/v1/admin/skills/${skill.id}/decision`, { decision, reason })
      notify('success', 'Decision recorded', `${skill.name} → ${decision}`)
      window.location.reload()
    } catch (error) { notify('error', 'Decision failed', error.message) }
  }
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {[['pending_review', 'Pending'], ['qualified', 'Qualified'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['quarantined', 'Quarantined']].map(([key, label]) => (
          <button key={key} className={`tab ${status === key ? 'active' : ''}`} onClick={() => setStatus(key)}>{label}</button>
        ))}
      </div>
      {skills.loading ? <Loading /> : (
        <div className="table-wrap">
          <table className="table"><thead><tr><th>Skill</th><th>Category</th><th>Creator</th><th>Licence</th><th>Security</th><th>Score</th><th>Actions</th></tr></thead>
            <tbody>
              {(skills.data?.items || []).map((skill) => (
                <tr key={skill.id}>
                  <td className="main"><b>{skill.name}</b><span>{skill.slug}</span></td>
                  <td>{skill.category}</td><td>{skill.creator}</td><td>{skill.license}</td>
                  <td><Pill tone={skill.security_status === 'clear' ? 'green' : 'amber'}>{skill.security_status}</Pill></td>
                  <td>{skill.score}</td>
                  <td><div className="list-row-actions">
                    <button className="btn btn-primary btn-sm" onClick={() => decide(skill, 'approved')}>Approve</button>
                    <button className="btn btn-danger btn-sm" onClick={() => decide(skill, 'rejected')}>Reject</button>
                    <button className="btn btn-outline btn-sm" onClick={() => decide(skill, 'quarantined')}>Quarantine</button>
                  </div></td>
                </tr>
              ))}
              {(skills.data?.items || []).length === 0 && <tr><td colSpan="7"><EmptyState icon={ShieldCheck} title="Queue is clear" body={`No skills with status ${status}.`} /></td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function AdminMarketplace({ notify }) {
  const [status, setStatus] = useState('pending')
  const listings = useLoad(() => get(`/api/v1/admin/marketplace/listings?status=${status}`), [status])
  const review = async (listing, next) => {
    const reason = window.prompt(`Reason for ${next} (optional):`) || ''
    try {
      await post(`/api/v1/admin/marketplace/listings/${listing.id}/status`, { status: next, reason })
      notify('success', 'Listing reviewed', `${listing.title} → ${next}`)
      window.location.reload()
    } catch (error) { notify('error', 'Review failed', error.message) }
  }
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {[['pending', 'Pending'], ['approved', 'Approved'], ['paused', 'Paused'], ['draft', 'Draft'], ['rejected', 'Rejected']].map(([key, label]) => (
          <button key={key} className={`tab ${status === key ? 'active' : ''}`} onClick={() => setStatus(key)}>{label}</button>
        ))}
      </div>
      {listings.loading ? <Loading /> : (
        <div className="table-wrap">
          <table className="table"><thead><tr><th>Listing</th><th>Price</th><th>Creator</th><th>Skill status</th><th>Commercial</th><th>Actions</th></tr></thead>
            <tbody>
              {(listings.data?.items || []).map((listing) => (
                <tr key={listing.id}>
                  <td className="main"><b>{listing.title}</b><span>{listing.skill_name}</span></td>
                  <td>{money(listing.price_cents, listing.currency)}</td><td>{listing.creator}</td>
                  <td><Pill tone={listing.skill_status === 'approved' ? 'green' : 'amber'}>{listing.skill_status}</Pill></td>
                  <td><Pill tone={listing.commercial_ok ? 'green' : 'red'}>{listing.commercial_ok ? 'Cleared' : 'Not cleared'}</Pill></td>
                  <td><div className="list-row-actions">
                    <button className="btn btn-primary btn-sm" onClick={() => review(listing, 'approved')}>Approve</button>
                    <button className="btn btn-outline btn-sm" onClick={() => review(listing, 'paused')}>Pause</button>
                    <button className="btn btn-danger btn-sm" onClick={() => review(listing, 'rejected')}>Reject</button>
                  </div></td>
                </tr>
              ))}
              {(listings.data?.items || []).length === 0 && <tr><td colSpan="6"><EmptyState icon={Package} title="No listings" body={`Nothing with status ${status}.`} /></td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function AdminCreators({ notify }) {
  const [status, setStatus] = useState('pending')
  const creators = useLoad(() => get(`/api/v1/admin/creators?status=${status}`), [status])
  const review = async (creator, next) => {
    const reason = window.prompt(`Reason for ${next} (optional):`) || ''
    try {
      await post(`/api/v1/admin/creators/${creator.user_id}/status`, { status: next, reason })
      notify('success', 'Creator reviewed', `${creator.display_name} → ${next}`)
      window.location.reload()
    } catch (error) { notify('error', 'Review failed', error.message) }
  }
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {[['pending', 'Pending'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['suspended', 'Suspended']].map(([key, label]) => (
          <button key={key} className={`tab ${status === key ? 'active' : ''}`} onClick={() => setStatus(key)}>{label}</button>
        ))}
      </div>
      {creators.loading ? <Loading /> : (
        <div className="table-wrap">
          <table className="table"><thead><tr><th>Creator</th><th>Email</th><th>Earnings</th><th>Pending</th><th>Listings</th><th>Actions</th></tr></thead>
            <tbody>
              {(creators.data?.items || []).map((creator) => (
                <tr key={creator.user_id}>
                  <td className="main"><b>{creator.display_name}</b><span>{creator.status}</span></td>
                  <td className="muted">{creator.email}</td>
                  <td>{money(creator.earnings_cents)}</td><td>{money(creator.pending_cents)}</td><td>{creator.listings}</td>
                  <td><div className="list-row-actions">
                    <button className="btn btn-primary btn-sm" onClick={() => review(creator, 'approved')}>Approve</button>
                    <button className="btn btn-danger btn-sm" onClick={() => review(creator, 'suspended')}>Suspend</button>
                  </div></td>
                </tr>
              ))}
              {(creators.data?.items || []).length === 0 && <tr><td colSpan="6"><EmptyState icon={Sparkles} title="No creators" body={`No creator profiles with status ${status}.`} /></td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function AdminBilling({ notify }) {
  const payments = useLoad(() => get('/api/v1/admin/payments?limit=100'), [])
  const subscriptions = useLoad(() => get('/api/v1/admin/subscriptions?limit=100'), [])
  const plans = useLoad(() => get('/api/v1/admin/plans'), [])
  const [status, setStatus] = useState('pending')
  const act = async (payment, action) => {
    const reason = window.prompt(`Reason for ${action} (required):`)
    if (!reason || reason.trim().length < 4) return
    try {
      await post(`/api/v1/admin/payments/${payment.id}/${action}`, { reason })
      notify('success', `Payment ${action}`, payment.reference)
      window.location.reload()
    } catch (error) { notify('error', 'Action failed', error.message) }
  }
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {[['pending', 'Pending'], ['paid', 'Paid'], ['refunded', 'Refunded'], ['failed', 'Failed']].map(([key, label]) => (
          <button key={key} className={`tab ${status === key ? 'active' : ''}`} onClick={() => setStatus(key)}>{label}</button>
        ))}
      </div>
      {payments.loading ? <Loading /> : (
        <div className="table-wrap" style={{ marginBottom: 22 }}>
          <table className="table"><thead><tr><th>Reference</th><th>Customer</th><th>Purpose</th><th>Amount</th><th>Provider</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {(payments.data?.items || []).filter((item) => !status || item.status === status).map((payment) => (
                <tr key={payment.id}>
                  <td className="main"><b>{payment.reference}</b><span>{payment.id}</span></td>
                  <td className="muted">{payment.user_email || '—'}</td><td>{payment.purpose}</td>
                  <td>{money(payment.amount_cents, payment.currency)}</td><td>{payment.provider}</td>
                  <td><Pill tone={payment.status === 'paid' ? 'green' : payment.status === 'refunded' ? 'red' : 'amber'}>{payment.status}</Pill></td>
                  <td><div className="list-row-actions">
                    {payment.status === 'pending' && <button className="btn btn-primary btn-sm" onClick={() => act(payment, 'fulfill')}>Record payment</button>}
                    {payment.status === 'paid' && <button className="btn btn-danger btn-sm" onClick={() => act(payment, 'refund')}>Refund</button>}
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="grid-2">
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">Active subscriptions</div></div></div>
          <div className="activity">
            {(subscriptions.data?.items || []).slice(0, 20).map((subscription) => (
              <div className="activity-row" key={subscription.id}>
                <span className="activity-icon"><CircleDollarSign size={14} /></span>
                <div><b>{subscription.plan_name}</b><span>{subscription.user_email || subscription.team_name || subscription.id}</span></div>
                <Pill tone={subscription.status === 'active' ? 'green' : 'amber'}>{subscription.status}</Pill>
              </div>
            ))}
            {(!subscriptions.data?.items || subscriptions.data.items.length === 0) && <p className="muted small">No subscriptions.</p>}
          </div>
        </div>
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">Plans</div></div></div>
          <div className="activity">
            {(plans.data?.items || []).map((plan) => (
              <div className="activity-row" key={plan.code}>
                <span className="activity-icon"><Layers size={14} /></span>
                <div><b>{plan.name}</b><span>{plan.code} · {money(plan.price_cents, plan.currency)}</span></div>
                <Pill tone={plan.is_active ? 'green' : 'dim'}>{plan.is_active ? 'Active' : 'Hidden'}</Pill>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function AdminUsers({ notify }) {
  const [q, setQ] = useState('')
  const users = useLoad(() => get(`/api/v1/admin/users?q=${encodeURIComponent(q)}&limit=100`), [q])
  const act = async (user, action, payload) => {
    try {
      if (action === 'role') {
        const role = window.prompt('New role (free, developer, creator, admin, super_admin):', user.role)
        if (!role) return
        await patch(`/api/v1/admin/users/${user.id}/role`, { role })
      } else {
        const active = window.confirm(`${user.is_active ? 'Deactivate' : 'Activate'} ${user.email}?`)
        if (!active) return
        await post(`/api/v1/admin/users/${user.id}/status`, { active: !user.is_active, reason: 'Administrator action' })
      }
      notify('success', 'User updated', user.email)
      window.location.reload()
    } catch (error) { notify('error', 'Action failed', error.message) }
  }
  return (
    <div>
      <div className="toolbar">
        <div className="topbar-search"><Search size={15} /><input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Search users by email or name" /></div>
      </div>
      {users.loading ? <Loading /> : (
        <div className="table-wrap">
          <table className="table"><thead><tr><th>User</th><th>Role</th><th>Plan</th><th>Retrievals</th><th>Teams</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {(users.data?.items || []).map((user) => (
                <tr key={user.id}>
                  <td className="main"><b>{user.name || user.email}</b><span>{user.email}</span></td>
                  <td><Pill tone={user.role === 'admin' || user.role === 'super_admin' ? 'violet' : 'cyan'}>{user.role}</Pill></td>
                  <td className="muted">{user.subscription?.plan_code || 'free'}</td>
                  <td>{user.skills_retrieved}</td><td>{user.teams}</td>
                  <td><Pill tone={user.is_active !== false ? 'green' : 'red'}>{user.is_active !== false ? 'active' : 'inactive'}</Pill></td>
                  <td><div className="list-row-actions">
                    <button className="btn btn-outline btn-sm" onClick={() => act(user, 'role')}>Change role</button>
                    <button className="btn btn-danger btn-sm" onClick={() => act(user, 'status')}>{user.is_active === false ? 'Activate' : 'Deactivate'}</button>
                  </div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function AdminRights({ notify }) {
  const [status, setStatus] = useState('open')
  const requests = useLoad(() => get(`/api/v1/admin/rights-requests?status=${status}`), [status])
  const resolve = async (item) => {
    const resolution = window.prompt('Resolution notes (required):')
    if (!resolution || resolution.trim().length < 4) return
    const suspend = window.confirm('Suspend distribution of the affected skill? OK = suspend, Cancel = keep distribution.')
    try {
      await post(`/api/v1/admin/rights-requests/${item.id}/resolve`, { status: 'resolved', resolution, suspend_distribution: suspend })
      notify('success', 'Rights request resolved', item.requester_email)
      window.location.reload()
    } catch (error) { notify('error', 'Could not resolve', error.message) }
  }
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {[['open', 'Open'], ['reviewing', 'Reviewing'], ['resolved', 'Resolved'], ['rejected', 'Rejected']].map(([key, label]) => (
          <button key={key} className={`tab ${status === key ? 'active' : ''}`} onClick={() => setStatus(key)}>{label}</button>
        ))}
      </div>
      {requests.loading ? <Loading /> : (
        <div className="stack">
          {(requests.data?.items || []).map((item) => (
            <div className="panel panel-pad" key={item.id}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <span className="activity-icon"><FileText size={15} /></span>
                <div style={{ flex: 1 }}>
                  <b>{item.requester_name} · {item.claim_type}</b>
                  <div className="muted small">{item.requester_email} · {item.skill_name || item.repository_url || 'General request'}</div>
                  <p className="muted small" style={{ marginTop: 8, lineHeight: 1.65 }}>{item.details}</p>
                </div>
                <Pill tone={item.status === 'open' ? 'amber' : item.status === 'resolved' ? 'green' : 'cyan'}>{item.status}</Pill>
              </div>
              {item.status !== 'resolved' && item.status !== 'rejected' && <div style={{ marginTop: 14, textAlign: 'right' }}><button className="btn btn-primary btn-sm" onClick={() => resolve(item)}>Resolve request</button></div>}
            </div>
          ))}
          {(requests.data?.items || []).length === 0 && <EmptyState icon={FileText} title="No rights requests" body={`No requests with status ${status}.`} />}
        </div>
      )}
    </div>
  )
}

function AdminImports() {
  const batches = useLoad(() => get('/api/v1/admin/import-batches'), [])
  const jobs = useLoad(() => get('/api/v1/admin/synchronization'), [])
  const [sources, setSources] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setMessage(null)
    try {
      const list = sources.split('\n').map((line) => line.trim()).filter(Boolean).map((url) => ({ repository_url: url, community: '' }))
      const result = await post('/api/v1/admin/import-batches', { sources: list })
      setMessage({ kind: 'success', text: `Queued ${result.source_count} repositories.` })
      setSources('')
      window.location.reload()
    } catch (error) { setMessage({ kind: 'error', text: error.message }) } finally { setBusy(false) }
  }
  return (
    <div>
      <div className="grid-2" style={{ marginBottom: 22 }}>
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">New import batch</div><div className="panel-sub">One repository URL per line. Every repository is queued for review.</div></div></div>
          <form onSubmit={submit}>
            <Field label="Repository URLs"><textarea className="textarea" value={sources} onChange={(event) => setSources(event.target.value)} placeholder="https://github.com/community/skills" /></Field>
            {message && <div className={`form-error ${message.kind === 'success' ? '' : ''}`} style={message.kind === 'success' ? { borderColor: 'rgba(52,211,153,.3)', background: 'rgba(52,211,153,.08)', color: '#a7f3d0' } : {}}>{message.text}</div>}
            <button className="btn btn-primary" disabled={busy}>{busy ? 'Queueing…' : 'Queue batch'}</button>
          </form>
        </div>
        <div className="panel panel-pad">
          <div className="panel-head"><div><div className="panel-title">Import batches</div></div></div>
          <div className="activity">
            {(batches.data?.items || []).slice(0, 12).map((batch) => (
              <div className="activity-row" key={batch.id}>
                <span className="activity-icon"><Upload size={14} /></span>
                <div><b>{batch.source_count} repositories</b><span>{batch.completed_count} completed · {batch.failed_count} failed</span></div>
                <Pill tone={batch.status === 'succeeded' ? 'green' : batch.status === 'failed' ? 'red' : 'amber'}>{batch.status}</Pill>
              </div>
            ))}
            {(!batches.data?.items || batches.data.items.length === 0) && <p className="muted small">No import batches yet.</p>}
          </div>
        </div>
      </div>
      <div className="panel panel-pad">
        <div className="panel-head"><div><div className="panel-title">Synchronization jobs</div><div className="panel-sub">Background import and sync work</div></div></div>
        <div className="table-wrap">
          <table className="table"><thead><tr><th>Repository</th><th>Operation</th><th>Status</th><th>Progress</th><th>Attempts</th><th>Error</th></tr></thead>
            <tbody>
              {(jobs.data?.items || []).slice(0, 30).map((job) => (
                <tr key={job.id}>
                  <td className="main"><b>{job.repository_url}</b><span>{job.id}</span></td>
                  <td>{job.operation}</td>
                  <td><Pill tone={job.status === 'succeeded' ? 'green' : job.status === 'failed' ? 'red' : 'amber'}>{job.status}</Pill></td>
                  <td className="muted">{job.progress_current}/{job.progress_total}</td>
                  <td>{job.attempt_count}</td>
                  <td className="muted small">{job.error || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function AdminRepositories({ notify }) {
  const repos = useLoad(() => get('/api/v1/admin/repositories'), [])
  const setStatus = async (repository, status) => {
    const reason = window.prompt(`Reason for ${status}:`)
    if (!reason || reason.trim().length < 4) return
    try {
      await post(`/api/v1/admin/repositories/${repository.id}/status`, { status, reason })
      notify('success', 'Repository updated', `${repository.url} → ${status}`)
      window.location.reload()
    } catch (error) { notify('error', 'Could not update', error.message) }
  }
  const sync = async (repository) => {
    try {
      const result = await post(`/api/v1/admin/repositories/${repository.id}/sync`, {})
      notify('success', 'Sync queued', result.message)
    } catch (error) { notify('error', 'Could not queue sync', error.message) }
  }
  return (
    <div className="table-wrap">
      <table className="table"><thead><tr><th>Repository</th><th>Community</th><th>Stars</th><th>Licence</th><th>Status</th><th>Last sync</th><th>Actions</th></tr></thead>
        <tbody>
          {(repos.data?.items || []).map((repository) => (
            <tr key={repository.id}>
              <td className="main"><b>{repository.owner}/{repository.name}</b><span>{repository.url}</span></td>
              <td>{repository.community || '—'}</td><td>{repository.stars}</td><td>{repository.license}</td>
              <td><Pill tone={repository.status === 'approved' ? 'green' : repository.status === 'excluded' ? 'red' : 'amber'}>{repository.status}</Pill></td>
              <td className="muted">{dateLabel(repository.last_sync_at)}</td>
              <td><div className="list-row-actions">
                <button className="btn btn-outline btn-sm" onClick={() => sync(repository)}><RefreshCw size={12} /> Sync</button>
                {repository.status !== 'approved' && <button className="btn btn-primary btn-sm" onClick={() => setStatus(repository, 'approved')}>Approve</button>}
                {repository.status === 'approved' && <button className="btn btn-danger btn-sm" onClick={() => setStatus(repository, 'excluded')}>Exclude</button>}
              </div></td>
            </tr>
          ))}
          {(repos.data?.items || []).length === 0 && <tr><td colSpan="7"><EmptyState icon={Database} title="No repositories" body="Import a batch or run discovery to populate repositories." /></td></tr>}
        </tbody>
      </table>
    </div>
  )
}

function AdminDiscovery({ notify }) {
  const discovery = useLoad(() => get('/api/v1/admin/discovery'), [])
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)
  const config = form || discovery.data?.config || {}
  useEffect(() => { if (discovery.data?.config && !form) setForm(discovery.data.config) }, [discovery.data])
  const save = async (run) => {
    setBusy(true)
    try {
      await post('/api/v1/admin/discovery', { topics: config.topics || [], keywords: config.keywords || [], languages: config.languages || [], min_stars: config.min_stars ?? 100, per_page: config.per_page ?? 30 })
      if (run) {
        const result = await post('/api/v1/admin/discovery/run', {})
        notify('success', 'Discovery complete', `${result.candidates_found} candidates, ${result.created_count} new repositories.`)
      } else notify('success', 'Discovery settings saved', 'The next scheduled run uses these values.')
      window.location.reload()
    } catch (error) { notify('error', 'Discovery failed', error.message) } finally { setBusy(false) }
  }
  return (
    <div className="grid-2">
      <div className="panel panel-pad">
        <div className="panel-head"><div><div className="panel-title">Discovery configuration</div><div className="panel-sub">Discovery records candidates only. Admission remains an explicit review.</div></div></div>
        {discovery.loading ? <Loading /> : (
          <div className="stack-sm">
            <Field label="Topics (comma separated)"><input className="input" value={(config.topics || []).join(', ')} onChange={(event) => setForm({ ...config, topics: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field>
            <Field label="Keywords"><input className="input" value={(config.keywords || []).join(', ')} onChange={(event) => setForm({ ...config, keywords: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></Field>
            <div className="field-row">
              <Field label="Minimum stars"><input className="input" type="number" value={config.min_stars ?? 100} onChange={(event) => setForm({ ...config, min_stars: Number(event.target.value) })} /></Field>
              <Field label="Results per query"><input className="input" type="number" value={config.per_page ?? 30} onChange={(event) => setForm({ ...config, per_page: Number(event.target.value) })} /></Field>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button className="btn btn-outline" disabled={busy} onClick={() => save(false)}>Save settings</button>
              <button className="btn btn-primary" disabled={busy} onClick={() => save(true)}>{busy ? 'Running…' : 'Save and run now'}</button>
            </div>
            {!discovery.data?.github_token_configured && <div className="banner warn"><AlertTriangle size={16} /><div>GitHub token is not configured. Discovery needs a read-only token.</div></div>}
          </div>
        )}
      </div>
      <div className="panel panel-pad">
        <div className="panel-head"><div><div className="panel-title">Recent runs</div></div></div>
        <div className="activity">
          {(discovery.data?.runs || []).map((run) => (
            <div className="activity-row" key={run.id}>
              <span className="activity-icon"><Globe size={14} /></span>
              <div><b>{run.candidates_found} candidates</b><span>{run.created_count} created · {run.status}</span></div>
              <time>{dateLabel(run.created_at)}</time>
            </div>
          ))}
          {(!discovery.data?.runs || discovery.data.runs.length === 0) && <p className="muted small">No discovery runs yet.</p>}
        </div>
      </div>
    </div>
  )
}

function AdminSecurity() {
  const security = useLoad(() => get('/api/v1/admin/security'), [])
  return (
    <div>
      {security.loading ? <Loading /> : (
        <>
          <div className="admin-grid">
            <div className="admin-kpi"><span>Scans</span><strong>{security.data.summary.scans}</strong></div>
            <div className="admin-kpi"><span>Clear</span><strong>{security.data.summary.clear}</strong></div>
            <div className="admin-kpi"><span>Flagged</span><strong>{security.data.summary.flagged}</strong></div>
            <div className="admin-kpi"><span>Open rights</span><strong>{security.data.summary.open_rights}</strong></div>
          </div>
          <div className="panel panel-pad">
            <div className="panel-head"><div><div className="panel-title">Risky skills</div><div className="panel-sub">Skills with security findings that still need review</div></div></div>
            <div className="table-wrap">
              <table className="table"><thead><tr><th>Skill</th><th>Security</th><th>Status</th></tr></thead>
                <tbody>
                  {(security.data.risky_skills || []).map((skill) => (
                    <tr key={skill.id}><td className="main"><b>{skill.name}</b><span>{skill.slug}</span></td>
                      <td><Pill tone={skill.security_status === 'clear' ? 'green' : 'amber'}>{skill.security_status}</Pill></td>
                      <td>{skill.status}</td></tr>
                  ))}
                  {(security.data.risky_skills || []).length === 0 && <tr><td colSpan="3"><EmptyState icon={ShieldCheck} title="No risky skills" body="Every indexed skill has a clear scan." /></td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AdminSettings({ notify }) {
  const settings = useLoad(() => get('/api/v1/admin/settings'), [])
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (settings.data?.items) {
      const map = {}
      settings.data.items.forEach((item) => { map[item.key] = item.value })
      setValues(map)
    }
  }, [settings.data])
  const save = async (key) => {
    setBusy(true)
    try {
      await patch('/api/v1/admin/settings', [{ key, value: values[key] || {} }])
      notify('success', 'Setting saved', key)
    } catch (error) { notify('error', 'Could not save', error.message) } finally { setBusy(false) }
  }
  const capabilities = settings.data?.capabilities || {}
  return (
    <div className="grid-2">
      <div className="panel panel-pad">
        <div className="panel-head"><div><div className="panel-title">Platform capabilities</div><div className="panel-sub">Configured in the server environment</div></div></div>
        <div className="status-grid">
          <div className={`status-item ${capabilities.email?.configured ? '' : 'warn'}`}><Check size={15} /><div><b>Email delivery</b><span>{capabilities.email?.configured ? capabilities.email.from : 'not configured'}</span></div></div>
          <div className={`status-item ${capabilities.payments?.configured ? '' : 'warn'}`}><CircleDollarSign size={15} /><div><b>{capabilities.payments?.label || 'Payments'}</b><span>{capabilities.payments?.configured ? 'configured' : 'awaiting credentials'}</span></div></div>
          <div className="status-item"><CreditCardIcon size={15} /><div><b>Supported providers</b><span>{(capabilities.providers || []).map((item) => `${item.label}: ${item.status}`).join(' · ') || 'manual only'}</span></div></div>
          <div className={`status-item ${capabilities.discovery?.github_token ? '' : 'warn'}`}><Globe size={15} /><div><b>GitHub discovery</b><span>{capabilities.discovery?.github_token ? 'token present' : 'no token'}</span></div></div>
          <div className="status-item"><Database size={15} /><div><b>Storage</b><span>{capabilities.storage?.s3 ? 'S3-compatible' : capabilities.storage?.path}</span></div></div>
        </div>
      </div>
      <div className="panel panel-pad">
        <div className="panel-head"><div><div className="panel-title">Editable settings</div><div className="panel-sub">Stored in the database and used by the next worker run</div></div></div>
        {settings.loading ? <Loading /> : (
          <div className="stack-sm">
            {[['security', 'Security policy'], ['marketplace', 'Marketplace policy'], ['discovery', 'Discovery defaults'], ['payment_prices', 'Payment provider price IDs']].map(([key, label]) => (
              <div key={key} className="field">
                <span className="label">{label}</span>
                <div className="copy-row">
                  <textarea className="textarea" style={{ minHeight: 88 }} value={JSON.stringify(values[key] || {}, null, 2)} onChange={(event) => { try { setValues({ ...values, [key]: JSON.parse(event.target.value) }) } catch { setValues({ ...values, [key]: event.target.value }) } }} />
                  <button className="btn btn-outline" disabled={busy} onClick={() => save(key)}>Save</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function AdminAudit() {
  const logs = useLoad(() => get('/api/v1/admin/audit-logs?limit=100'), [])
  return (
    <div className="table-wrap">
      <table className="table"><thead><tr><th>Action</th><th>Target</th><th>Details</th><th>When</th></tr></thead>
        <tbody>
          {(logs.data?.items || []).map((log) => (
            <tr key={log.id}>
              <td><span className="tag">{log.action}</span></td>
              <td className="muted">{log.target_type} {log.target_id}</td>
              <td className="muted small">{JSON.stringify(log.details || {})}</td>
              <td className="muted">{dateTimeLabel(log.created_at)}</td>
            </tr>
          ))}
          {(logs.data?.items || []).length === 0 && <tr><td colSpan="4"><EmptyState icon={ClipboardList} title="No audit entries" body="Privileged actions will appear here." /></td></tr>}
        </tbody>
      </table>
    </div>
  )
}

function MarketplaceV2({ user, navigate, onSelect, notify, embedded }) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('featured')
  const [featuredOnly, setFeaturedOnly] = useState(false)
  const [category, setCategory] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const featured = useLoad(() => get('/api/v1/marketplace/featured'), [])
  const categoryList = useLoad(() => get('/api/v1/marketplace/categories'), [])
  const pageSize = 24

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(offset), sort })
      if (query.trim()) params.set('q', query.trim().slice(0, 120))
      if (featuredOnly) params.set('featured', 'true')
      if (category) params.set('category', category)
      get(`/api/v1/marketplace/listings?${params}`)
        .then((data) => {
          if (active) {
            setItems(data.items || [])
            setTotal(data.total || 0)
          }
        })
        .catch((err) => { if (active) setError(err.message) })
        .finally(() => { if (active) setLoading(false) })
    }, query.trim() ? 240 : 0)
    return () => { active = false; clearTimeout(timer) }
  }, [query, sort, featuredOnly, category, offset])

  const cards = items.slice()
  const categories = categoryList.data?.items || []
  const firstResult = total === 0 ? 0 : offset + 1
  const lastResult = Math.min(offset + cards.length, total)
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const noResults = Boolean(query.trim() || category || featuredOnly)

  return (
    <div className="market-v2">
      <section className="market-hero">
        <div className="market-hero-grid">
          <div className="market-hero-copy">
            <span className="market-hero-overline"><Sparkles size={13} /> CURATED SKILL MARKETPLACE</span>
            <h1 className="market-hero-title">Skills that fit your stack.<br /><span className="accent">Reviewed, versioned, ready to run.</span></h1>
            <p className="market-hero-sub">Discover complete skill packages from trusted communities. Licences, security scans and immutable snapshots are checked before a listing reaches your agents — read them instantly or run approved scripts in a sandbox.</p>
            <div className="market-hero-actions">
              <button className="btn btn-primary btn-lg" onClick={() => navigate(user ? '/creator' : '/register')}><Star size={16} fill="#fff" /> Publish a skill</button>
              <button className="btn btn-outline btn-lg" onClick={() => navigate('/docs')}>How it works</button>
            </div>
          </div>
          <div className="market-hero-panel">
            <div className="market-hero-panel-head"><Package size={16} /><span>Marketplace at a glance</span><Pill tone="green">Live</Pill></div>
            <div className="market-hero-stats">
              <div><b>{total}</b><span>approved listings</span></div>
              <div><b>{categories.length}</b><span>categories</span></div>
            </div>
            <div className="market-hero-checks">
              <div><ShieldCheck size={14} /> Licence checked</div>
              <div><ShieldCheck size={14} /> Security reviewed</div>
              <div><Database size={14} /> Immutable versions</div>
              <div><Terminal size={14} /> Sandbox execution</div>
            </div>
          </div>
        </div>
      </section>

      <div className="market-toolbar">
        <div className="topbar-search search">
          <Search size={15} />
          <input value={query} onChange={(event) => { setOffset(0); setQuery(event.target.value) }} placeholder="Search skills, creators and listings" />
        </div>
        <Toggle value={sort} onChange={setSort} options={[
          { value: 'featured', label: 'Featured' },
          { value: 'newest', label: 'Newest' },
          { value: 'price_low', label: 'Lowest first' },
          { value: 'price_high', label: 'Highest first' },
        ]} />
        <div className="market-filters">
          <label className="filter-group"><input type="checkbox" checked={featuredOnly} onChange={(event) => { setOffset(0); setFeaturedOnly(event.target.checked) }} /> Featured only</label>
          <select className="select" value={category} onChange={(event) => { setOffset(0); setCategory(event.target.value) }} disabled={categories.length === 0}>
            <option value="">{categories.length ? 'Filter by category' : 'No categories yet'}</option>
            {categories.map(({ name, count }) => <option key={name} value={name}>{name} ({count})</option>)}
          </select>
          <span className="count-note">{total} listings</span>
        </div>
      </div>

      <div className="market-section">
        <div className="market-section-head"><h2>Featured in the marketplace</h2><button className="link" onClick={() => navigate('/marketplace')}>Explore everything</button></div>
        {featured.loading ? <Loading /> : (
          <div className="market-grid">
            {(featured.data?.items || []).slice(0, 4).map((item) => (
              <MarketCard key={item.id} item={item} onSelect={onSelect} />
            ))}
          </div>
        )}
      </div>

      <div className="market-section">
        <div className="market-section-head"><h2>All listings</h2><span className="count-note">{total === 0 ? '0 listings' : `Showing ${firstResult}–${lastResult} of ${total}`}</span></div>
        {loading ? <Loading /> : error ? <div className="banner">{error}</div> : (
          <div className="market-grid">
            {cards.map((item) => <MarketCard key={item.id} item={item} onSelect={onSelect} />)}
            {cards.length === 0 && <div className="market-empty-v2"><Package size={28} /><h3>{noResults ? 'No matching listings' : 'No marketplace listings yet'}</h3><p>{noResults ? 'Try another search or adjust your filters.' : 'Skills are added after creator review, licence review and security review. Check back or publish your own.'}</p>{!noResults && <button className="btn btn-primary btn-sm" onClick={() => navigate(user ? '/creator' : '/register')}>Publish a skill</button>}</div>}
          </div>
        )}
        {!loading && !error && total > pageSize && <div className="market-pagination">
          <span className="count-note">Page {Math.floor(offset / pageSize) + 1} of {pageCount}</span>
          <div><button className="btn btn-outline btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button>
            <button className="btn btn-outline btn-sm" disabled={offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)}>Next</button></div>
        </div>}
      </div>
    </div>
  )
}

function MarketCard({ item, onSelect }) {
  const price = item.price_cents > 0 ? money(item.price_cents, item.currency) : 'Free'
  const stars = item.skill?.stars || 0
  return (
    <article className="market-card" onClick={() => onSelect?.(item)}>
      <div className="market-card-head">
        <h3 className="line-clamp-2">{item.title}</h3>
        <span className="market-card-badge"><Check size={12} /> {item.featured ? 'Featured' : price === 'Free' ? 'Free' : 'Premium'}</span>
      </div>
      <p className="market-card-summary">{item.summary || `${item.skill?.category || 'Listed skill'} skill with ${item.skill?.security_status === 'clear' ? 'clear security scan' : 'security review pending'}.`}</p>
      <div className="market-card-meta">
        <span><Star size={11} fill="#fbbf24" color="#fbbf24" /> {stars} stars · {item.rating > 0 ? item.rating.toFixed(1) : 'Not rated'}</span>
        <span className="dot" />
        <span>{item.creator}</span>
        <span className="dot" />
        <span>{item.skill?.license}</span>
        {item.skill?.category && <><span className="dot" /><span>{item.skill.category}</span></>}
      </div>
      <div className="market-card-footer">
        <span className={`market-card-price ${price === 'Free' ? 'free' : ''}`}>
          {price}<span className="small">{price !== 'Free' ? '/licence' : ''}</span>
        </span>
        <button className="btn btn-outline btn-sm">View details</button>
      </div>
    </article>
  )
}
