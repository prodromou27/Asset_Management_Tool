import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  meta?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ title, meta, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div>
        <h1 className="page-header__title">{title}</h1>
        {meta && <p className="page-header__meta">{meta}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  )
}
