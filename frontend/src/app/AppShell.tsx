import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Boxes, ChevronDown, Menu, Search, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { logout, queryKeys } from '../shared/api/accounts'
import { PERMISSIONS } from '../shared/api/types'
import { locate, SECTIONS, type NavItem } from './navigation'
import { useSession } from './useSession'

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? '?').slice(0, 2)
  return letters.toUpperCase()
}

function NavList({ items, onNavigate }: { items: NavItem[]; onNavigate: () => void }) {
  return (
    <ul className="nav-list">
      {items.map(({ to, label, icon: Icon, end }) => (
        <li key={to}>
          <NavLink
            to={to}
            end={end || to === '/'}
            onClick={onNavigate}
            className={({ isActive }) => `nav-link${isActive ? ' nav-link--active' : ''}`}
          >
            <Icon className="nav-link__icon" size={18} strokeWidth={1.75} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        </li>
      ))}
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
    onSettled: () => {
      queryClient.clear()
      queryClient.setQueryData(queryKeys.me, null)
      navigate('/login', { replace: true })
    },
  })

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
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

  useEffect(() => {
    if (!navOpen) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setNavOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navOpen])

  return (
    <div className={`app-shell${navOpen ? ' app-shell--nav-open' : ''}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <nav className="app-shell__nav" id="app-nav" aria-label="Primary">
        <div className="app-shell__brand">
          <span className="brand-mark" aria-hidden="true">
            <Boxes size={18} strokeWidth={2} />
          </span>
          <span className="brand-name">ITAM</span>
          <button
            type="button"
            className="nav-close"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {!restricted &&
          sections.map((section) => (
            <div className="nav-group" key={section.id}>
              <p className="nav-section" id={`nav-${section.id}`}>
                {section.label}
              </p>
              <NavList items={section.items} onNavigate={() => setNavOpen(false)} />
            </div>
          ))}
      </nav>
      {navOpen && (
        <div className="nav-backdrop" aria-hidden="true" onClick={() => setNavOpen(false)} />
      )}
      <div className="app-shell__body">
        <header className="top-bar">
          <button
            type="button"
            className="nav-toggle"
            aria-label="Open navigation"
            aria-controls="app-nav"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(true)}
          >
            <Menu size={20} aria-hidden="true" />
          </button>
          {where.page && (
            <p className="top-bar__context">
              <span className="top-bar__section">{where.section}</span>
              <span className="top-bar__sep" aria-hidden="true">
                /
              </span>
              <span className="top-bar__page">{where.page}</span>
            </p>
          )}
          <div className="top-bar__end">
            {!restricted && <GlobalSearch />}
            <UserMenu />
          </div>
        </header>
        <main className="app-shell__main" id="main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  )
}
