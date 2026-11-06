import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  meta?: ReactNode
  actions?: ReactNode
  icon?: ReactNode
}

export function PageHeader({ title, meta, actions, icon }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div>
        <h1 className={`page-header__title${icon ? ' page-header__title--icon' : ''}`}>
          {icon && <span className="page-header__icon" aria-hidden="true">{icon}</span>}
          {title}
        </h1>
        {meta && <p className="page-header__meta">{meta}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  )
}
