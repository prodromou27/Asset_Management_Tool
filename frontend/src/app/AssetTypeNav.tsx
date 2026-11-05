import { useQuery } from '@tanstack/react-query'
import { Boxes, HardDrive, Monitor, Network, Printer, Server, ShieldCheck } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { assetKeys, fetchCategories } from '../shared/api/assets'

const ICONS = { workstations: Monitor, servers: Server, networking: Network, printers: Printer, storage: HardDrive, security: ShieldCheck }

export function AssetTypeNav({ onNavigate }: { onNavigate: () => void }) {
  const { pathname, search } = useLocation()
  const categories = useQuery({ queryKey: assetKeys.categories, queryFn: fetchCategories })
  const selected = new URLSearchParams(search).get('category')
  const byId = new Map((categories.data ?? []).map((category) => [category.id, category]))
  let root = selected
  const visited = new Set<string>()
  while (root && !visited.has(root) && byId.get(root)?.parent) {
    visited.add(root)
    root = byId.get(root)!.parent
  }
  const roots = (categories.data ?? []).filter((category) => !category.parent && category.is_active)
  return <div className="asset-types">
    <p className="asset-types__heading">Asset types</p>
    {categories.isPending && <p className="asset-types__note">Loading asset types…</p>}
    {categories.isError && <p className="asset-types__note">Asset types unavailable. <button type="button" onClick={() => void categories.refetch()}>Retry</button></p>}
    {categories.isSuccess && !roots.length && <p className="asset-types__note">No active asset types.</p>}
    <ul className="nav-list">
      {roots.map((category) => {
        const active = pathname === '/assets' && root === category.id
        const Icon = ICONS[category.code as keyof typeof ICONS] ?? Boxes
        return <li key={category.id}><Link to={`/assets?category=${encodeURIComponent(category.id)}`}
          className={`nav-link asset-type-link${active ? ' nav-link--active' : ''}`}
          aria-current={active ? 'page' : undefined} onClick={onNavigate}>
          <Icon className="nav-link__icon" size={16} aria-hidden="true" /><span>{category.name}</span>
        </Link></li>
      })}
    </ul>
  </div>
}
