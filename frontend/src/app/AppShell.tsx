import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { logout, queryKeys } from '../shared/api/accounts'
import { PERMISSIONS } from '../shared/api/types'
import { useSession } from './useSession'

interface NavItem {
  to: string
  label: string
  permission?: string
}

const PRIMARY: NavItem[] = [
  { to: '/assets', label: 'Assets', permission: PERMISSIONS.assetsView },
  { to: '/discovery', label: 'Discovery', permission: PERMISSIONS.discoveryView },
  { to: '/groups', label: 'Groups', permission: PERMISSIONS.groupsView },
  { to: '/licenses', label: 'Licenses', permission: PERMISSIONS.licensesView },
  { to: '/', label: 'System health' },
]

const ADMINISTRATION: NavItem[] = [
  { to: '/admin/sites', label: 'Sites & locations', permission: PERMISSIONS.sitesManage },
  { to: '/admin/categories', label: 'Categories & fields', permission: PERMISSIONS.categoriesManage },
  { to: '/admin/integrations', label: 'Integrations', permission: PERMISSIONS.integrationsManage },
  { to: '/admin/users', label: 'Users & roles', permission: PERMISSIONS.usersView },
  { to: '/admin/audit', label: 'Audit log', permission: PERMISSIONS.auditView },
  { to: '/admin/security', label: 'Security policy', permission: PERMISSIONS.securityView },
]

function NavList({ items }: { items: NavItem[] }) {
  return (
    <ul className="nav-list">
      {items.map((item) => (
        <li key={item.to}>
          <NavLink
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => `nav-link${isActive ? ' nav-link--active' : ''}`}
          >
            {item.label}
          </NavLink>
        </li>
      ))}
    </ul>
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
  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="user-menu__trigger"
        aria-expanded={open}
        aria-controls="user-menu-panel"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="user-menu__name">{me.display_name}</span>
        <span className="user-menu__role">{me.roles.map((r) => r.name).join(', ') || 'No role'}</span>
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
  // A temporary password grants no access until replaced, so hide navigation.
  const restricted = me?.must_change_password ?? false
  const adminItems = ADMINISTRATION.filter((item) => !item.permission || can(item.permission))

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <nav className="app-shell__nav" aria-label="Primary">
        <div className="app-shell__brand">ITAM</div>
        {!restricted && (
          <NavList items={PRIMARY.filter((item) => !item.permission || can(item.permission))} />
        )}
        {!restricted && adminItems.length > 0 && (
          <>
            <p className="nav-section" id="nav-admin">
              Administration
            </p>
            <NavList items={adminItems} />
          </>
        )}
      </nav>
      <div className="app-shell__body">
        <header className="top-bar">
          <UserMenu />
        </header>
        <main className="app-shell__main" id="main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  )
}
