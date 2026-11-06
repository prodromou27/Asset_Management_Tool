import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useId, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { assetKeys, fetchCategories } from '../shared/api/assets'
import { CategoryIcon } from '../shared/ui/CategoryIcon'

export function AssetTypeNav({ onNavigate }: { onNavigate: () => void }) {
  const [expanded, setExpanded] = useState(true)
  const contentId = useId()
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
  const DisclosureIcon = expanded ? ChevronDown : ChevronRight
  return <div className="asset-types">
    <button type="button" className="asset-types__heading" aria-expanded={expanded}
      aria-controls={contentId} onClick={() => setExpanded((value) => !value)}>
      Asset types<DisclosureIcon size={12} aria-hidden="true" />
    </button>
    <div id={contentId} hidden={!expanded}>
    {categories.isPending && <p className="asset-types__note">Loading asset types…</p>}
    {categories.isError && <p className="asset-types__note">Asset types unavailable. <button type="button" onClick={() => void categories.refetch()}>Retry</button></p>}
    {categories.isSuccess && !roots.length && <p className="asset-types__note">No active asset types.</p>}
    <ul className="nav-list">
      {roots.map((category) => {
        const active = pathname === '/assets' && root === category.id
        return <li key={category.id}><Link to={`/assets?category=${encodeURIComponent(category.id)}`}
          className={`nav-link asset-type-link${active ? ' nav-link--active' : ''}`}
          aria-current={active ? 'page' : undefined} onClick={onNavigate}>
          <CategoryIcon category={category} className="nav-link__icon" /><span>{category.name}</span>
        </Link></li>
      })}
    </ul>
    </div>
  </div>
}
