import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AssetGroup, GroupMembership, RuleField } from '../../shared/api/types'
import {
  ASSET_ID,
  CATEGORIES,
  CAT_SWITCH,
  SITE_HQ,
  makeAsset,
  makeField,
  makeMe,
  mockApi,
  page,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const GROUP_ID = '77777777-7777-4777-8777-777777777701'
const FIELDS: RuleField[] = [
  { field: 'manufacturer', label: 'Manufacturer', kind: 'text', operators: ['eq', 'contains', 'in'], choices: [], ref: '', nullable: true },
  {
    field: 'business_status',
    label: 'Business status',
    kind: 'enum',
    operators: ['eq', 'in'],
    choices: [
      { value: 'deployed', label: 'Deployed' },
      { value: 'in_stock', label: 'In stock' },
    ],
    ref: '',
    nullable: false,
  },
  { field: 'category', label: 'Category', kind: 'ref', operators: ['eq', 'in'], choices: [], ref: 'category', nullable: false },
  { field: 'created_at', label: 'Registered', kind: 'date', operators: ['before', 'after'], choices: [], ref: '', nullable: false },
]

function makeGroup(overrides: Partial<AssetGroup> = {}): AssetGroup {
  return {
    id: GROUP_ID,
    name: 'Cisco switches',
    description: 'Network refresh scope',
    kind: 'dynamic',
    parent: null,
    owner: null,
    rule: { field: 'manufacturer', operator: 'eq', value: 'Cisco' },
    rule_version: 1,
    member_count: 2,
    last_evaluated_at: '2026-11-04T08:00:00Z',
    created_at: '2026-11-04T08:00:00Z',
    modified_at: '2026-11-04T08:00:00Z',
    version: 3,
    ...overrides,
  }
}

function membership(overrides: Partial<GroupMembership> = {}): GroupMembership {
  return {
    id: 'm1',
    asset: { id: ASSET_ID, name: 'sw-core-01', site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' }, category: 'Switch', manufacturer: 'Cisco', model: 'C9300' },
    source: 'evaluated',
    rule_version: 1,
    added_at: '2026-11-04T08:00:00Z',
    added_by: null,
    added_reason: 'Matches rule version 1',
    removed_at: null,
    removed_by: null,
    removed_reason: '',
    ...overrides,
  }
}

const reference = {
  'GET /groups/fields/': { body: FIELDS },
  'GET /asset-categories/': { body: CATEGORIES },
  'GET /sites/': { body: [SITE_HQ] },
  'GET /locations/': { body: [] },
  'GET /departments/': { body: [] },
  'GET /users/lookup/': { body: [{ id: '00000000-0000-4000-8000-000000000001', username: 'admin.one', display_name: 'Admin One' }] },
  'GET /integrations/': { body: [] },
}

describe('Groups list and creation', () => {
  it('lists groups with kind, rule summary and visible member count', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...reference,
      'GET /groups/': { body: [makeGroup(), makeGroup({ id: 'g2', name: 'Refresh 2027', kind: 'static', rule: null, member_count: 5 })] },
    })
    renderApp('/groups')

    const table = await screen.findByRole('region', { name: 'Groups' })
    const row = (await within(table).findByRole('link', { name: 'Cisco switches' })).closest('tr')!
    expect(within(row).getByText('Dynamic')).toBeInTheDocument()
    expect(await within(row).findByText('Manufacturer is Cisco')).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: 'Members (your sites)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New group' })).toBeInTheDocument()
  })

  it('creates a dynamic group after a live preview', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...reference,
      'GET /groups/': { body: [] },
      'POST /groups/preview/': { body: { count: 2, sample: [{ id: ASSET_ID, name: 'sw-core-01', site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' } }], would_add: null, would_remove: null } },
      'POST /groups/': { status: 201, body: makeGroup() },
      [`GET /groups/${GROUP_ID}/`]: { body: makeGroup() },
      [`GET /groups/${GROUP_ID}/assets/`]: { body: page([membership()]) },
      [`GET /groups/${GROUP_ID}/rule-versions/`]: { body: [] },
    })
    renderApp('/groups')

    fireEvent.click(await screen.findByRole('button', { name: 'New group' }))
    const dialog = screen.getByRole('dialog', { name: 'New group' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Cisco switches' } })
    fireEvent.click(within(dialog).getByLabelText(/Dynamic — members follow a rule/))
    fireEvent.change(await within(dialog).findByLabelText('Condition 1 value'), { target: { value: 'Cisco' } })

    expect(await within(dialog).findByText('sw-core-01', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(within(dialog).getByRole('region', { name: 'Rule preview' })).toHaveTextContent('2 matching assets in your sites')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create group' }))

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST' && c.path === '/groups/')?.body).toEqual({
        name: 'Cisco switches',
        kind: 'dynamic',
        description: '',
        parent: null,
        owner: null,
        rule: { op: 'and', rules: [{ field: 'manufacturer', operator: 'eq', value: 'Cisco' }] },
      }),
    )
    expect(await screen.findByRole('heading', { name: 'Cisco switches' })).toBeInTheDocument()
  })

  it('offers enum and category pickers and nested groups', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe() }, ...reference, 'GET /groups/': { body: [] } })
    renderApp('/groups')

    fireEvent.click(await screen.findByRole('button', { name: 'New group' }))
    const dialog = screen.getByRole('dialog', { name: 'New group' })
    fireEvent.click(within(dialog).getByLabelText(/Dynamic — members follow a rule/))
    fireEvent.change(await within(dialog).findByLabelText('Condition 1 field'), { target: { value: 'category' } })
    expect(within(within(dialog).getByLabelText('Condition 1 value')).getByRole('option', { name: /Switch/ })).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add nested group' }))
    expect(within(dialog).getByLabelText('Group 2 match')).toHaveValue('or')
    fireEvent.change(within(dialog).getByLabelText('Condition 2.1 field'), { target: { value: 'business_status' } })
    fireEvent.change(within(dialog).getByLabelText('Condition 2.1 operator'), { target: { value: 'in' } })
    expect(within(dialog).getByLabelText('Condition 2.1 value')).toHaveProperty('multiple', true)
  })

  it('hides creation without groups.manage', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe({ permissions: ['groups.view', 'assets.view'] }) },
      ...reference,
      'GET /groups/': { body: [makeGroup()] },
    })
    renderApp('/groups')

    expect(await screen.findByRole('link', { name: 'Cisco switches' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New group' })).not.toBeInTheDocument()
  })
})

describe('Group detail', () => {
  it('exports this group with its members', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...reference,
      'GET /groups/': { body: [makeGroup()] },
      [`GET /groups/${GROUP_ID}/`]: { body: makeGroup() },
      [`GET /groups/${GROUP_ID}/assets/`]: { body: page([membership()]) },
      [`GET /groups/${GROUP_ID}/rule-versions/`]: { body: [] },
      'GET /exports/families/': {
        body: [
          {
            code: 'groups',
            label: 'Asset groups',
            description: '',
            allowed: true,
            filter_keys: [],
            columns: [{ key: 'id', label: 'Group ID', personal: false, allowed: true }],
            related: [{ key: 'members', label: 'Members' }],
            personal_data_allowed: true,
          },
        ],
      },
      'POST /exports/': { status: 202, body: { id: 'x1' } },
      'GET /exports/': { body: page([]) },
    })
    renderApp(`/groups/${GROUP_ID}`)

    fireEvent.click(await screen.findByRole('button', { name: 'Export members' }))
    const dialog = await screen.findByRole('dialog', { name: 'Export asset groups' })
    expect(await within(dialog).findByLabelText('This group (Cisco switches)')).toBeChecked()
    expect(within(dialog).getByLabelText('Members')).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Start export' }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/exports/')!
      expect(post.body).toMatchObject({
        family: 'groups',
        scope: 'selected',
        ids: [GROUP_ID],
        related: ['members'],
      })
    })
  })

  it('edits a dynamic rule with a membership diff and a reason', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...reference,
      'GET /groups/': { body: [makeGroup()] },
      [`GET /groups/${GROUP_ID}/`]: { body: makeGroup() },
      [`GET /groups/${GROUP_ID}/assets/`]: { body: page([membership()]) },
      [`GET /groups/${GROUP_ID}/rule-versions/`]: {
        body: [{ number: 1, rule: makeGroup().rule, reason: 'Created', created_by: 'admin.one', created_at: '2026-11-04T08:00:00Z' }],
      },
      [`POST /groups/${GROUP_ID}/preview/`]: { body: { count: 1, sample: [], would_add: 0, would_remove: 1 } },
      [`PATCH /groups/${GROUP_ID}/`]: { body: makeGroup({ rule_version: 2, version: 4 }) },
    })
    renderApp(`/groups/${GROUP_ID}`)

    const members = await screen.findByRole('region', { name: /Members/ })
    expect(await within(members).findByText('Matched rule version 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Edit rule' }))
    fireEvent.change(await screen.findByLabelText('Condition 1 value'), { target: { value: 'Juniper' } })
    expect(await screen.findByText(/would add 0, remove 1/, {}, { timeout: 3000 })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Save rule and re-evaluate' }))
    expect(screen.getByText('Explain why the rule changes (at least 5 characters).')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Reason for the change'), { target: { value: 'Vendor switch' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save rule and re-evaluate' }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.headers['If-Match']).toBe('"3"')
      expect(patch.body).toEqual({
        rule: { op: 'and', rules: [{ field: 'manufacturer', operator: 'eq', value: 'Juniper' }] },
        reason: 'Vendor switch',
      })
    })
  })

  it('adds and removes static members with a reason', async () => {
    const group = makeGroup({ kind: 'static', rule: null, rule_version: 0, member_count: 1 })
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...reference,
      'GET /groups/': { body: [group] },
      [`GET /groups/${GROUP_ID}/`]: { body: group },
      [`GET /groups/${GROUP_ID}/assets/`]: {
        body: page([membership({ source: 'explicit', rule_version: null, added_by: 'admin.one', added_reason: 'Refresh scope' })]),
      },
      'GET /assets/': { body: page([makeAsset({ id: 'a2', name: 'sw-access-02' })]) },
      [`POST /groups/${GROUP_ID}/members/`]: { body: { added: 1, removed: 0 } },
    })
    renderApp(`/groups/${GROUP_ID}`)

    expect(await screen.findByText('Added by admin.one')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit rule' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add assets…' }))
    const dialog = screen.getByRole('dialog', { name: `Add assets to ${group.name}` })
    fireEvent.change(within(dialog).getByLabelText('Find assets'), { target: { value: 'sw-access' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Search' }))
    fireEvent.click(await within(dialog).findByLabelText(/sw-access-02/))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add 1' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/members/'))?.body).toEqual({ add: ['a2'], reason: '' }),
    )

    fireEvent.click(screen.getByLabelText('Select sw-core-01'))
    fireEvent.click(screen.getByRole('button', { name: 'Remove selected…' }))
    const remove = screen.getByRole('dialog', { name: `Remove 1 from ${group.name}?` })
    fireEvent.change(within(remove).getByLabelText('Reason'), { target: { value: 'Already replaced' } })
    fireEvent.click(within(remove).getByRole('button', { name: 'Remove' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith('/members/')).at(-1)?.body).toEqual({
        remove: [ASSET_ID],
        reason: 'Already replaced',
      }),
    )
  })
})

describe('Asset groups tab', () => {
  it('shows the groups an asset belongs to and why', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
      [`GET /assets/${ASSET_ID}/groups/`]: {
        body: [{ id: GROUP_ID, name: 'Cisco switches', kind: 'dynamic', source: 'evaluated', rule_version: 2, added_at: '2026-11-04T08:00:00Z' }],
      },
    })
    renderApp(`/assets/${ASSET_ID}?tab=groups`)

    const panel = await screen.findByRole('region', { name: 'Asset groups' })
    expect(await within(panel).findByRole('link', { name: 'Cisco switches' })).toHaveAttribute('href', `/groups/${GROUP_ID}`)
    expect(within(panel).getByText('Matches rule version 2')).toBeInTheDocument()
  })
})
