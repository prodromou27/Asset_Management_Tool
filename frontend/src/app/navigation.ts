import {
  Activity,
  ChartNoAxesCombined,
  Settings,
  AppWindow,
  Boxes,
  Building2,
  DatabaseBackup,
  FileDown,
  FileUp,
  Globe,
  History,
  Library,
  LayoutList,
  Mail,
  PlugZap,
  Radar,
  ScrollText,
  Shapes,
  ShieldCheck,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { PERMISSIONS } from '../shared/api/types'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  permission?: string
  /** Shown when the user holds any of these (areas combining several permissions). */
  anyOf?: string[]
  /** Other path prefixes that belong to this entry (detail pages under another root). */
  also?: string[]
  /** Active only on this exact path (not on deeper routes owned by another entry). */
  end?: boolean
}

export interface NavSection {
  id: string
  label: string
  items: NavItem[]
}

export const SECTIONS: NavSection[] = [
  {
    id: 'inventory',
    label: 'Inventory',
    items: [
      { to: '/assets', label: 'Assets', icon: Boxes, permission: PERMISSIONS.assetsView },
      { to: '/groups', label: 'Groups', icon: LayoutList, permission: PERMISSIONS.groupsView },
      {
        to: '/software',
        label: 'Software & Licenses',
        icon: AppWindow,
        anyOf: [PERMISSIONS.assetsView, PERMISSIONS.licensesView],
      },
      { to: '/lifecycle', label: 'Lifecycle', icon: History, permission: PERMISSIONS.lifecycleView, end: true },
      {
        to: '/domains',
        label: 'Domains & Certificates',
        icon: Globe,
        permission: PERMISSIONS.certificatesView,
        also: ['/certificates'],
      },
    ],
  },
  {
    id: 'discovery',
    label: 'Sources',
    items: [
      { to: '/discovery', label: 'Discovery', icon: Radar, permission: PERMISSIONS.discoveryView },
      { to: '/imports', label: 'Imports', icon: FileUp, permission: PERMISSIONS.importsRun },
      { to: '/exports', label: 'Exports', icon: FileDown, permission: PERMISSIONS.exportsRun },
      { to: '/reports', label: 'Reports', icon: ChartNoAxesCombined, permission: PERMISSIONS.reportsView },
    ],
  },
  {
    id: 'admin',
    label: 'Administration',
    items: [
      { to: '/admin/general', label: 'General settings', icon: Settings, permission: PERMISSIONS.generalView },
      { to: '/admin/sites', label: 'Sites & locations', icon: Building2, permission: PERMISSIONS.sitesManage },
      { to: '/admin/categories', label: 'Categories & fields', icon: Shapes, permission: PERMISSIONS.categoriesManage },
      { to: '/admin/integrations', label: 'Integrations', icon: PlugZap, permission: PERMISSIONS.integrationsManage },
      {
        to: '/lifecycle/catalogue',
        label: 'Lifecycle catalogue',
        icon: Library,
        permission: PERMISSIONS.lifecycleView,
      },
      { to: '/admin/users', label: 'Users & roles', icon: Users, permission: PERMISSIONS.usersView },
      { to: '/admin/audit', label: 'Audit log', icon: ScrollText, permission: PERMISSIONS.auditView },
      { to: '/admin/security', label: 'Security policy', icon: ShieldCheck, permission: PERMISSIONS.securityView },
      { to: '/admin/smtp', label: 'SMTP & notifications', icon: Mail, permission: PERMISSIONS.notificationsView },
      { to: '/admin/backups', label: 'Backups & Recovery', icon: DatabaseBackup, permission: PERMISSIONS.backupsView },
    ],
  },
  {
    id: 'system',
    label: 'System',
    items: [{ to: '/', label: 'System health', icon: Activity }],
  },
]

const ACCOUNT_CONTEXT: Record<string, string> = { '/account/password': 'Change password' }

/** Section and page for the top bar, from the longest matching navigation entry. */
export function locate(pathname: string): { section?: string; page?: string } {
  if (ACCOUNT_CONTEXT[pathname]) return { section: 'Account', page: ACCOUNT_CONTEXT[pathname] }
  let best: { section: string; page: string; length: number } | undefined
  for (const section of SECTIONS) {
    for (const item of section.items) {
      const under = (root: string) => pathname === root || pathname.startsWith(`${root}/`)
      const matches = item.to === '/' ? pathname === '/' : under(item.to) || (item.also ?? []).some(under)
      if (matches && (!best || item.to.length > best.length)) {
        best = { section: section.label, page: item.label, length: item.to.length }
      }
    }
  }
  return best ? { section: best.section, page: best.page } : {}
}
