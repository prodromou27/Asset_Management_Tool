import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CAT_WS } from '../../test/api'
import { CategoryIcon } from './CategoryIcon'

describe('category icon inheritance', () => {
  it('inherits from a renamed parent for administrator-defined child codes', () => {
    const root = { ...CAT_WS, name: 'End user devices' }
    const child = { ...CAT_WS, id: 'custom', code: 'loan-devices', parent: root.id }
    const { container } = render(<>
      <CategoryIcon category={root} />
      <CategoryIcon category={child} categories={[root, child]} />
    </>)
    const icons = container.querySelectorAll('svg')
    expect(icons[0].outerHTML).toBe(icons[1].outerHTML)
    expect(icons[0]).toHaveAttribute('aria-hidden', 'true')
  })

  it('uses the custom-root fallback when metadata has a cycle or missing parent', () => {
    const root = { ...CAT_WS, id: 'custom', code: 'lab-equipment', parent: null }
    const cycle = { ...root, parent: root.id }
    const orphan = { ...root, parent: 'missing' }
    const { container } = render(<>
      <CategoryIcon category={root} />
      <CategoryIcon category={cycle} categories={[cycle]} />
      <CategoryIcon category={orphan} />
    </>)
    const icons = [...container.querySelectorAll('svg')]
    expect(icons).toHaveLength(3)
    expect(new Set(icons.map((icon) => icon.outerHTML)).size).toBe(1)
  })
})
