import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Dialog } from './Dialog'
import { Tabs } from './Tabs'

describe('shared UI regression checks', () => {
  it('handles removal of all permitted tabs without crashing', () => {
    const select = vi.fn()
    const view = render(<Tabs label="Details" selected="one" tabs={[{ id: 'one', label: 'One', content: 'Content' }]} onSelect={select} />)
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Content')
    view.rerender(<Tabs label="Details" selected="one" tabs={[]} onSelect={select} />)
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
  })

  it('does not submit a busy dialog twice via form submission', () => {
    const confirm = vi.fn()
    render(<Dialog open busy title="Saving" confirmLabel="Save" onClose={vi.fn()} onConfirm={confirm}>Pending</Dialog>)
    fireEvent.submit(screen.getByRole('dialog').querySelector('form')!)
    expect(confirm).not.toHaveBeenCalled()
  })
})
