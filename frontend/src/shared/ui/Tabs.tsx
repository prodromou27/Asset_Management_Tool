import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabItem {
  id: string
  label: string
  content: ReactNode
}

interface TabsProps {
  label: string
  tabs: TabItem[]
  selected: string
  onSelect: (id: string) => void
}

/** WAI-ARIA tabs: arrow keys, Home/End, roving tabindex. Selection is controlled
 * so callers can persist it in the URL (survives reload, docs/07). */
export function Tabs({ label, tabs, selected, onSelect }: TabsProps) {
  const baseId = useId()
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const current = tabs.find((tab) => tab.id === selected) ?? tabs[0]

  function move(event: KeyboardEvent, index: number) {
    const last = tabs.length - 1
    const target = {
      ArrowRight: index === last ? 0 : index + 1,
      ArrowLeft: index === 0 ? last : index - 1,
      Home: 0,
      End: last,
    }[event.key]
    if (target === undefined) return
    event.preventDefault()
    const next = tabs[target]
    onSelect(next.id)
    refs.current[next.id]?.focus()
  }

  return (
    <div className="tabs">
      <div role="tablist" aria-label={label} className="tabs__list">
        {tabs.map((tab, index) => {
          const active = tab.id === current.id
          return (
            <button
              key={tab.id}
              ref={(node) => {
                refs.current[tab.id] = node
              }}
              type="button"
              role="tab"
              id={`${baseId}-tab-${tab.id}`}
              aria-selected={active}
              aria-controls={`${baseId}-panel-${tab.id}`}
              tabIndex={active ? 0 : -1}
              className={`tabs__tab${active ? ' tabs__tab--active' : ''}`}
              onClick={() => onSelect(tab.id)}
              onKeyDown={(event) => move(event, index)}
            >
              {tab.label}
            </button>
          )
        })}
      </div>
      <div
        role="tabpanel"
        id={`${baseId}-panel-${current.id}`}
        aria-labelledby={`${baseId}-tab-${current.id}`}
        tabIndex={0}
        className="tabs__panel"
      >
        {current.content}
      </div>
    </div>
  )
}
