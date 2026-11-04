import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { assetKeys, fetchUserLookup } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import { createGroup, fetchGroups, fetchRuleFields, groupKeys, type RuleNode } from '../../shared/api/groups'
import { PERMISSIONS } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { RuleBuilder } from './RuleBuilder'
import { describeRule, emptyRule, ruleComplete } from './ruleUtils'
import { RulePreview } from './RulePreview'

export function GroupsPage() {
  const { can } = useSession()
  const [creating, setCreating] = useState(false)
  const groups = useQuery({ queryKey: groupKeys.list, queryFn: fetchGroups })
  const fields = useQuery({ queryKey: groupKeys.fields, queryFn: fetchRuleFields })

  return (
    <div className="page page--wide">
      <PageHeader
        title="Groups"
        meta="Static lists and rule-based (dynamic) groups of assets. Groups never grant access: you only see members in your sites."
        actions={
          can(PERMISSIONS.groupsManage) && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              New group
            </Button>
          )
        }
      />
      <section className="panel panel--flush" aria-live="polite" aria-label="Groups">
        {groups.isPending && <LoadingState label="Loading groups…" />}
        {groups.isError && <QueryErrorState error={groups.error} what="groups" />}
        {groups.data && groups.data.length === 0 && (
          <EmptyState title="No groups yet.">Create a static list or a rule that selects assets automatically.</EmptyState>
        )}
        {groups.data && groups.data.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Kind</th>
                <th scope="col" className="num">
                  Members (your sites)
                </th>
                <th scope="col">Owner</th>
                <th scope="col">Last evaluated</th>
              </tr>
            </thead>
            <tbody>
              {groups.data.map((g) => (
                <tr key={g.id}>
                  <td>
                    <Link to={`/groups/${g.id}`}>{g.name}</Link>
                    {g.parent && <span className="cell-secondary">In {g.parent.name}</span>}
                    {g.description && <span className="cell-secondary">{g.description}</span>}
                  </td>
                  <td>
                    <StatusBadge tone="neutral" label={g.kind === 'dynamic' ? 'Dynamic' : 'Static'} />
                    {g.kind === 'dynamic' && (
                      <span className="cell-secondary">{describeRule(g.rule as RuleNode, fields.data)}</span>
                    )}
                  </td>
                  <td className="num">{g.member_count}</td>
                  <td>{g.owner?.display_name ?? <span className="cell-muted">None</span>}</td>
                  <td className="nowrap">
                    {g.kind === 'dynamic' ? formatDateTime(g.last_evaluated_at) : <span className="cell-muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {creating && <CreateGroupDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

function CreateGroupDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const groups = useQuery({ queryKey: groupKeys.list, queryFn: fetchGroups })
  const users = useQuery({ queryKey: assetKeys.userLookup, queryFn: fetchUserLookup })
  const [kind, setKind] = useState<'static' | 'dynamic'>('static')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [parent, setParent] = useState('')
  const [owner, setOwner] = useState('')
  const [rule, setRule] = useState<RuleNode>(emptyRule)
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const mutation = useMutation({
    mutationFn: () =>
      createGroup({
        name: name.trim(),
        kind,
        description: description.trim(),
        parent: parent || null,
        owner: owner || null,
        ...(kind === 'dynamic' ? { rule } : {}),
      }),
    onSuccess: async (group) => {
      await queryClient.invalidateQueries({ queryKey: groupKeys.all })
      navigate(`/groups/${group.id}`)
    },
  })
  const server = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const shown = { ...server, ...errors }
  return (
    <Dialog
      open
      title="New group"
      confirmLabel="Create group"
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        const errs: Record<string, string[]> = {}
        if (!name.trim()) errs.name = ['Enter a name.']
        if (kind === 'dynamic' && !ruleComplete(rule)) errs.rule = ['Fill in every condition.']
        setErrors(errs)
        if (!Object.keys(errs).length) mutation.mutate()
      }}
    >
      {mutation.error && !Object.keys(server).length && <p className="field__error">{mutation.error.message}</p>}
      <fieldset className="fieldset">
        <legend className="field__label">Kind</legend>
        <div className="radio-list">
          <label className="radio">
            <input type="radio" name="group_kind" checked={kind === 'static'} onChange={() => setKind('static')} />
            Static — members are added and removed by hand
          </label>
          <label className="radio">
            <input type="radio" name="group_kind" checked={kind === 'dynamic'} onChange={() => setKind('dynamic')} />
            Dynamic — members follow a rule and update automatically
          </label>
        </div>
      </fieldset>
      <TextField label="Name" name="group_name" value={name} onChange={(e) => setName(e.target.value)} error={shown.name} />
      <TextField
        label="Description"
        name="group_description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        error={shown.description}
      />
      <div className="form-grid">
        <SelectField
          label="Inside group"
          name="group_parent"
          options={[{ value: '', label: 'None (top level)' }, ...(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))]}
          value={parent}
          onChange={(e) => setParent(e.target.value)}
          error={shown.parent}
        />
        <SelectField
          label="Owner"
          name="group_owner"
          options={[{ value: '', label: 'No owner' }, ...(users.data ?? []).map((u) => ({ value: u.id, label: u.display_name }))]}
          value={owner}
          onChange={(e) => setOwner(e.target.value)}
          error={shown.owner}
        />
      </div>
      {kind === 'dynamic' && (
        <>
          <RuleBuilder value={rule} onChange={setRule} />
          {shown.rule && <p className="field__error">{shown.rule.join(' ')}</p>}
          <RulePreview rule={rule} />
        </>
      )}
    </Dialog>
  )
}
