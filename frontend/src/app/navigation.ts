import {
  Activity,
  Boxes,
  Building2,
  FileUp,
  KeyRound,
  LayoutList,
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
      { to: '/licenses', label: 'Licenses', icon: KeyRound, permission: PERMISSIONS.licensesView },
    ],
  },
  {
    id: 'discovery',
    label: 'Sources',
    items: [
      { to: '/discovery', label: 'Discovery', icon: Radar, permission: PERMISSIONS.discoveryView },
      { to: '/imports', label: 'Imports', icon: FileUp, permission: PERMISSIONS.importsRun },
    ],
  },
  {
    id: 'admin',
    label: 'Administration',
    items: [
      { to: '/admin/sites', label: 'Sites & locations', icon: Building2, permission: PERMISSIONS.sitesManage },
      { to: '/admin/categories', label: 'Categories & fields', icon: Shapes, permission: PERMISSIONS.categoriesManage },
      { to: '/admin/integrations', label: 'Integrations', icon: PlugZap, permission: PERMISSIONS.integrationsManage },
      { to: '/admin/users', label: 'Users & roles', icon: Users, permission: PERMISSIONS.usersView },
      { to: '/admin/audit', label: 'Audit log', icon: ScrollText, permission: PERMISSIONS.auditView },
      { to: '/admin/security', label: 'Security policy', icon: ShieldCheck, permission: PERMISSIONS.securityView },
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
      const matches =
        item.to === '/' ? pathname === '/' : pathname === item.to || pathname.startsWith(`${item.to}/`)
      if (matches && (!best || item.to.length > best.length)) {
        best = { section: section.label, page: item.label, length: item.to.length }
      }
    }
  }
  return best ? { section: best.section, page: best.page } : {}
}
