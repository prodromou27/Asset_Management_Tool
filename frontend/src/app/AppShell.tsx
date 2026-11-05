import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Boxes, Building2, ChevronDown, ChevronRight, Menu, Search, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { logout, queryKeys } from '../shared/api/accounts'
import { PERMISSIONS } from '../shared/api/types'
import { getDisplayTimezoneWarning } from '../shared/format'
import { locate, SECTIONS, type NavItem } from './navigation'
import { useSession } from './useSession'
import { ThemeToggle } from './theme'

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? '?').slice(0, 2)
  return letters.toUpperCase()
}

function NavList({ items, onNavigate }: { items: NavItem[]; onNavigate: () => void }) {
  const { pathname } = useLocation()
  return (
    <ul className="nav-list">
      {items.map(({ to, label, icon: Icon, end, also }) => {
        const under = (root: string) => pathname === root || pathname.startsWith(`${root}/`)
        const active = pathname === to || (!end && to !== '/' && under(to)) || (also ?? []).some(under)
        return (
        <li key={to}>
          <Link
            to={to}
            aria-current={active ? 'page' : undefined}
            onClick={onNavigate}
            className={`nav-link${active ? ' nav-link--active' : ''}`}
          >
            <Icon className="nav-link__icon" size={18} strokeWidth={1.75} aria-hidden="true" />
            <span className="nav-link__label">{label}</span>
            {active && <ChevronRight className="nav-link__current" size={14} aria-hidden="true" />}
          </Link>
        </li>
        )
      })}
    </ul>
  )
}

function GlobalSearch() {
  const { can } = useSession()
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  if (!can(PERMISSIONS.assetsView)) return null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const q = value.trim()
    navigate(q ? `/assets?q=${encodeURIComponent(q)}` : '/assets')
  }

  return (
    <form className="global-search" role="search" onSubmit={submit}>
      <Search className="global-search__icon" size={16} aria-hidden="true" />
      <label className="visually-hidden" htmlFor="global-search">
        Search assets
      </label>
      <input
        id="global-search"
        className="global-search__input"
        type="search"
        placeholder="Search assets by name, tag, serial, IP…"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
    </form>
  )
}

function UserMenu() {
  const { me } = useSession()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear()
      queryClient.setQueryData(queryKeys.me, null)
      navigate('/login', { replace: true })
    },
  })

  useEffect(() => {
    if (!open) return
    ref.current?.querySelector<HTMLElement>('.user-menu__item')?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      ref.current?.querySelector<HTMLElement>('.user-menu__trigger')?.focus()
    }
    const onClick = (event: MouseEvent) =>
      ref.current && !ref.current.contains(event.target as Node) && setOpen(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  if (!me) return null
  const roles = me.roles.map((r) => r.name).join(', ') || 'No role'
  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="user-menu__trigger"
        aria-label={`Account menu for ${me.display_name || me.username}`}
        aria-expanded={open}
        aria-controls="user-menu-panel"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="avatar" aria-hidden="true">
          {initials(me.display_name || me.username)}
        </span>
        <span className="user-menu__text">
          <span className="user-menu__name">{me.display_name}</span>
          <span className="user-menu__role">{roles}</span>
        </span>
        <ChevronDown size={16} aria-hidden="true" className="user-menu__chevron" />
      </button>
      {open && (
        <div className="user-menu__panel" id="user-menu-panel">
          <p className="user-menu__username mono">{me.username}</p>
          <Link className="user-menu__item" to="/account/password" onClick={() => setOpen(false)}>
            Change password
          </Link>
          <button
            type="button"
            className="user-menu__item"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
          >
            Sign out
          </button>
          {signOut.isError && (
            <p className="user-menu__error" role="alert">
              Sign out failed. Your session may still be active. Try again.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, can } = useSession()
  const { pathname } = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  // A temporary password grants no access until replaced, so hide navigation.
  const restricted = me?.must_change_password ?? false
  const sections = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) => (!item.permission || can(item.permission)) && (!item.anyOf || item.anyOf.some((code) => can(code))),
    ),
  })).filter((section) => section.items.length > 0)
  const where = locate(pathname)
  const [sectionChoice, setSectionChoice] = useState({ pathname: '', section: '' })
  const currentSection = sectionChoice.pathname === pathname ? sectionChoice.section : where.section
  const timezoneWarning = getDisplayTimezoneWarning()

  useEffect(() => {
    if (!navOpen) return
    const nav = document.getElementById('app-nav')
    const body = document.querySelector<HTMLElement>('.app-shell__body')
    const masthead = document.querySelector<HTMLElement>('.workspace-masthead')
    const opener = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    if (body) body.inert = true
    if (masthead) masthead.inert = true
    const controls = () => [...(nav?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? [])]
    controls()[0]?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavOpen(false)
      if (event.key !== 'Tab') return
      const items = controls()
      const first = items[0]
      const last = items.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    const media = window.matchMedia?.('(max-width: 767px)')
    const onResize = () => { if (!media?.matches) setNavOpen(false) }
    media?.addEventListener('change', onResize)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      media?.removeEventListener('change', onResize)
      document.body.style.overflow = previousOverflow
      if (body) body.inert = false
      if (masthead) masthead.inert = false
      if (opener instanceof HTMLElement) opener.focus()
    }
  }, [navOpen])

  return (
    <div className={`app-shell${navOpen ? ' app-shell--nav-open' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="workspace-masthead">
        <div className="app-shell__brand">
          <span className="brand-mark" aria-hidden="true">
            <Boxes size={18} strokeWidth={2} />
          </span>
          <span className="brand-copy">
            <span className="brand-name">ITAM</span>
          </span>
        </div>
        <div className="workspace-global-nav" aria-label="Workspace areas">
          {!restricted && sections.map((section) => <button type="button" key={section.id}
            className={`workspace-area${currentSection === section.label ? ' workspace-area--current' : ''}`}
            aria-expanded={currentSection === section.label} aria-controls={`nav-items-${section.id}`}
            onClick={() => setSectionChoice({ pathname, section: section.label })}>
            {section.label}
          </button>)}
        </div>
        <div className="masthead-tools">
          {!restricted && <GlobalSearch />}
          <ThemeToggle />
          <UserMenu />
          <button type="button" className="nav-toggle" aria-label="Open navigation" aria-controls="app-nav" aria-expanded={navOpen} onClick={() => setNavOpen(true)}>
            <Menu size={20} aria-hidden="true" />
          </button>
        </div>
      </header>
      <nav className="app-shell__nav" id="app-nav" aria-label="Primary">
          <button
            type="button"
            className="nav-close"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
          >
            <X size={18} aria-hidden="true" />
          </button>
        <div className="workspace-organization">
          <Building2 size={20} aria-hidden="true" />
          <div><span className="workspace-organization__label">Organization</span>
            <strong title={me?.display_preferences?.organization_name}>{me?.display_preferences?.organization_name ?? 'ITAM'}</strong>
          </div>
        </div>
        <div className="workspace-navigation">
        {!restricted &&
          sections.map((section) => (
            <div className={`nav-group${currentSection === section.label ? ' nav-group--current' : ''}`} key={section.id}>
              <p className="nav-section" id={`nav-${section.id}`}>
                {section.label}
              </p>
              <div className="nav-items" id={`nav-items-${section.id}`}><NavList items={section.items} onNavigate={() => setNavOpen(false)} /></div>
            </div>
          ))}
        </div>
      </nav>
      {navOpen && (
        <div className="nav-backdrop" aria-hidden="true" onClick={() => setNavOpen(false)} />
      )}
      <div className="app-shell__body">
        <main className="app-shell__main" id="main" tabIndex={-1}>
          {where.page && (
            <nav className="top-bar__context" aria-label="Breadcrumb">
              <span className="top-bar__section">{where.section === 'Inventory' || where.section === 'Sources' ? me?.display_preferences?.organization_name ?? 'ITAM' : where.section}</span>
              <ChevronRight className="top-bar__sep" size={14} aria-hidden="true" />
              <span className="top-bar__page" aria-current="page">{where.page}</span>
            </nav>
          )}
          {timezoneWarning && <p className="state state--warning" role="status">{timezoneWarning}</p>}
          {children}
        </main>
      </div>
    </div>
  )
}
