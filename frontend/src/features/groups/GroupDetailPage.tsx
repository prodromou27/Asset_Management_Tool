import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { assetKeys, fetchAssets, fetchUserLookup } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  archiveGroup,
  changeGroupMembers,
  evaluateGroup,
  fetchGroup,
  fetchGroupMembers,
  fetchGroups,
  fetchRuleFields,
  fetchRuleVersions,
  groupKeys,
  updateGroup,
  type RuleNode,
} from '../../shared/api/groups'
import { PERMISSIONS, type AssetGroup } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { ExportDialog } from '../exports/ExportDialog'
import { RuleBuilder } from './RuleBuilder'
import { describeRule, ruleComplete } from './ruleUtils'
import { RulePreview } from './RulePreview'

export function GroupDetailPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const group = useQuery({ queryKey: groupKeys.detail(id), queryFn: () => fetchGroup(id) })
  const fields = useQuery({ queryKey: groupKeys.fields, queryFn: fetchRuleFields })
  const [editing, setEditing] = useState(false)
  const [archiving, setArchiving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: groupKeys.all })
  const evaluate = useMutation({ mutationFn: () => evaluateGroup(id), onSuccess: refresh })
  const archive = useMutation({
    mutationFn: (reason: string) => archiveGroup(id, group.data!.version, reason),
    onSuccess: async () => {
      await refresh()
      navigate('/groups')
    },
  })

  const crumb = (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <Link to="/groups">Groups</Link>
    </nav>
  )
  if (group.isPending) return <LoadingState label="Loading group…" />
  if (group.isError)
    return (
      <div className="page">
        {crumb}
        <QueryErrorState error={group.error} what="this group" />
      </div>
    )
  const g = group.data
  const manage = can(PERMISSIONS.groupsManage)
  return (
    <div className="page page--wide">
      {crumb}
      <PageHeader
        title={g.name}
        meta={`${g.kind === 'dynamic' ? 'Dynamic' : 'Static'} group · ${g.member_count} members in your sites`}
        actions={
          <>
            {can(PERMISSIONS.exportsRun) && (
              <Button onClick={() => setExporting(true)}>Export members</Button>
            )}
            {manage && (
              <>
                {g.kind === 'dynamic' && (
                  <Button busy={evaluate.isPending} onClick={() => evaluate.mutate()}>
                    Re-evaluate now
                  </Button>
                )}
                <Button onClick={() => setEditing(true)}>Edit details</Button>
                <Button variant="danger" onClick={() => setArchiving(true)}>
                  Archive…
                </Button>
              </>
            )}
          </>
        }
      />
      <ExportDialog
        open={exporting}
        onClose={() => setExporting(false)}
        family="groups"
        selected={{ ids: [g.id], label: `This group (${g.name})` }}
        defaultRelated={['members']}
      />
      {evaluate.data && (
        <p className="inline-success" role="status">
          Evaluated: {evaluate.data.added} added, {evaluate.data.removed} removed, {evaluate.data.members} members in
          total.
        </p>
      )}
      <div className="detail-layout">
        <div className="stack">
          {g.kind === 'dynamic' && <RulePanel group={g} manage={manage} fieldsLabel={describeRule(g.rule as RuleNode, fields.data)} />}
          <Members group={g} />
        </div>
        <div className="detail-layout__side">
          <section className="panel" aria-labelledby="group-details">
            <h2 className="section-title" id="group-details">
              Details
            </h2>
            <dl className="meta-grid meta-grid--stacked">
              <dt>Description</dt>
              <dd>{g.description || 'None'}</dd>
              <dt>Owner</dt>
              <dd>{g.owner?.display_name ?? 'None'}</dd>
              <dt>Inside group</dt>
              <dd>{g.parent ? <Link to={`/groups/${g.parent.id}`}>{g.parent.name}</Link> : 'Top level'}</dd>
              {g.kind === 'dynamic' && (
                <>
                  <dt>Rule version</dt>
                  <dd>{g.rule_version}</dd>
                  <dt>Last evaluated</dt>
                  <dd>{formatDateTime(g.last_evaluated_at)}</dd>
                </>
              )}
              <dt>Created</dt>
              <dd>{formatDateTime(g.created_at)}</dd>
            </dl>
            <p className="field__help">Membership never grants access to assets in other sites.</p>
          </section>
          {g.kind === 'dynamic' && <RuleHistory group={g} />}
        </div>
      </div>
      {editing && <EditDetailsDialog group={g} onClose={() => setEditing(false)} onSaved={refresh} />}
      {archiving && (
        <ReasonDialog
          title={`Archive ${g.name}?`}
          confirmLabel="Archive group"
          help="The group disappears from lists; its membership history is kept. Groups used by other rules cannot be archived."
          busy={archive.isPending}
          error={archive.error ? archive.error.message : null}
          onClose={() => setArchiving(false)}
          onConfirm={(reason) => archive.mutate(reason)}
        />
      )}
    </div>
  )
}

function RulePanel({ group, manage, fieldsLabel }: { group: AssetGroup; manage: boolean; fieldsLabel: string }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<RuleNode | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => updateGroup(group.id, group.version, { rule: draft as never, reason: reason.trim() }),
    onSuccess: async () => {
      setDraft(null)
      setReason('')
      await queryClient.invalidateQueries({ queryKey: groupKeys.all })
    },
  })
  const serverError = isApiError(save.error)
    ? Object.values(save.error.fieldErrors).flat().join(' ') || save.error.message
    : null
  return (
    <section className="panel" aria-labelledby="rule-heading">
      <h2 className="section-title" id="rule-heading">
        Rule (version {group.rule_version})
      </h2>
      {!draft ? (
        <>
          <p>{fieldsLabel}</p>
          {manage && (
            <Button onClick={() => setDraft(group.rule as RuleNode)}>Edit rule</Button>
          )}
        </>
      ) : (
        <form
          className="form-stack"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (!ruleComplete(draft)) return setError('Fill in every condition.')
            if (reason.trim().length < 5) return setError('Explain why the rule changes (at least 5 characters).')
            setError(null)
            save.mutate()
          }}
        >
          <RuleBuilder value={draft} onChange={setDraft} />
          <RulePreview rule={draft} groupId={group.id} />
          <TextAreaField
            label="Reason for the change"
            name="rule_reason"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            help="Stored with the new rule version and in the audit log."
          />
          {(error || serverError) && <p className="field__error">{error ?? serverError}</p>}
          <div className="form-actions">
            <Button variant="quiet" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={save.isPending}>
              Save rule and re-evaluate
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}

function RuleHistory({ group }: { group: AssetGroup }) {
  const versions = useQuery({ queryKey: groupKeys.versions(group.id), queryFn: () => fetchRuleVersions(group.id) })
  const fields = useQuery({ queryKey: groupKeys.fields, queryFn: fetchRuleFields })
  return (
    <section className="panel" aria-labelledby="rule-history">
      <h2 className="section-title" id="rule-history">
        Rule history
      </h2>
      {versions.data && (
        <ol className="plain-list">
          {versions.data.map((v) => (
            <li key={v.number}>
              <strong>Version {v.number}</strong> · {formatDateTime(v.created_at)} by {v.created_by ?? 'system'}
              <span className="cell-secondary">{describeRule(v.rule as RuleNode, fields.data)}</span>
              {v.reason && <span className="cell-secondary">Reason: {v.reason}</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function Members({ group }: { group: AssetGroup }) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [history, setHistory] = useState(false)
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [removing, setRemoving] = useState(false)
  const [adding, setAdding] = useState(false)
  const editable = group.kind === 'static' && can(PERMISSIONS.groupsMembers)
  const members = useInfiniteQuery({
    queryKey: groupKeys.members(group.id, history, q),
    queryFn: ({ pageParam }) => fetchGroupMembers(group.id, history, q, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const remove = useMutation({
    mutationFn: (reason: string) => changeGroupMembers(group.id, { remove: [...selected], reason }),
    onSuccess: async () => {
      setSelected(new Set())
      setRemoving(false)
      await queryClient.invalidateQueries({ queryKey: groupKeys.all })
    },
  })
  const items = members.data?.pages.flatMap((p) => p.items) ?? []
  const total = members.data?.pages[0]?.count
  return (
    <section className="panel panel--flush" aria-labelledby="members-heading" aria-live="polite">
      <h2 className="section-title section-title--inset" id="members-heading">
        Members{total !== undefined && ` (${total})`}
      </h2>
      <div className="toolbar toolbar--inset">
        <form
          role="search"
          onSubmit={(e) => {
            e.preventDefault()
            setQ(search.trim())
          }}
        >
          <TextField label="Asset name" name="member_q" value={search} onChange={(e) => setSearch(e.target.value)} />
        </form>
        <SelectField
          label="Show"
          name="member_history"
          options={[
            { value: '', label: 'Current members' },
            { value: 'history', label: 'Current and removed' },
          ]}
          value={history ? 'history' : ''}
          onChange={(e) => setHistory(Boolean(e.target.value))}
        />
        {editable && (
          <div className="toolbar__actions">
            <Button onClick={() => setAdding(true)}>Add assets…</Button>
            <Button variant="danger" disabled={selected.size === 0} onClick={() => setRemoving(true)}>
              Remove selected…
            </Button>
          </div>
        )}
      </div>
      {members.isPending && <LoadingState label="Loading members…" />}
      {members.isError && <QueryErrorState error={members.error} what="members" />}
      {members.isSuccess && items.length === 0 && <EmptyState title="No members in your sites." />}
      {items.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              {editable && (
                <th scope="col">
                  <span className="visually-hidden">Select</span>
                </th>
              )}
              <th scope="col">Asset</th>
              <th scope="col">Site</th>
              <th scope="col">Category</th>
              <th scope="col">Why</th>
              <th scope="col">Since</th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id} className={m.removed_at ? 'row--muted' : undefined}>
                {editable && (
                  <td>
                    {!m.removed_at && (
                      <input
                        type="checkbox"
                        aria-label={`Select ${m.asset.name}`}
                        checked={selected.has(m.asset.id)}
                        onChange={() =>
                          setSelected((s) => {
                            const next = new Set(s)
                            if (next.has(m.asset.id)) next.delete(m.asset.id)
                            else next.add(m.asset.id)
                            return next
                          })
                        }
                      />
                    )}
                  </td>
                )}
                <td>
                  <Link to={`/assets/${m.asset.id}`}>{m.asset.name}</Link>
                  {(m.asset.manufacturer || m.asset.model) && (
                    <span className="cell-secondary">{[m.asset.manufacturer, m.asset.model].filter(Boolean).join(' ')}</span>
                  )}
                </td>
                <td className="mono">{m.asset.site.code}</td>
                <td>{m.asset.category}</td>
                <td>
                  {m.source === 'evaluated' ? `Matched rule version ${m.rule_version}` : `Added by ${m.added_by ?? 'unknown'}`}
                  {m.added_reason && m.source === 'explicit' && <span className="cell-secondary">{m.added_reason}</span>}
                  {m.removed_at && (
                    <span className="cell-secondary">
                      Removed {formatDateTime(m.removed_at)}
                      {m.removed_by ? ` by ${m.removed_by}` : ''}: {m.removed_reason}
                    </span>
                  )}
                </td>
                <td className="nowrap">{formatDateTime(m.added_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {members.hasNextPage && (
        <div className="table-footer">
          <Button onClick={() => members.fetchNextPage()} busy={members.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      )}
      {removing && (
        <ReasonDialog
          title={`Remove ${selected.size} from ${group.name}?`}
          confirmLabel="Remove"
          help="The membership history is kept with your reason."
          busy={remove.isPending}
          error={remove.error ? remove.error.message : null}
          onClose={() => setRemoving(false)}
          onConfirm={(reason) => remove.mutate(reason)}
        />
      )}
      {adding && <AddMembersDialog group={group} onClose={() => setAdding(false)} />}
    </section>
  )
}

function AddMembersDialog({ group, onClose }: { group: AssetGroup; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [chosen, setChosen] = useState<Map<string, string>>(new Map())
  const [reason, setReason] = useState('')
  const results = useQuery({
    queryKey: assetKeys.list({ q }),
    queryFn: () => fetchAssets({ q }),
    enabled: q.length > 0,
  })
  const add = useMutation({
    mutationFn: () => changeGroupMembers(group.id, { add: [...chosen.keys()], reason: reason.trim() }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupKeys.all })
      onClose()
    },
  })
  return (
    <Dialog
      open
      title={`Add assets to ${group.name}`}
      confirmLabel={`Add ${chosen.size}`}
      busy={add.isPending || chosen.size === 0}
      onClose={onClose}
      onConfirm={() => add.mutate()}
    >
      <div className="toolbar" role="search">
        <TextField
          label="Find assets"
          name="add_q"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              setQ(search.trim())
            }
          }}
          help="Name, tag, serial, hostname, IP or MAC."
        />
        <div className="toolbar__actions">
          <Button onClick={() => setQ(search.trim())}>Search</Button>
        </div>
      </div>
      {results.data && (
        <ul className="plain-list" aria-label="Search results">
          {results.data.items.map((a) => (
            <li key={a.id}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={chosen.has(a.id)}
                  onChange={() =>
                    setChosen((c) => {
                      const next = new Map(c)
                      if (next.has(a.id)) next.delete(a.id)
                      else next.set(a.id, a.name)
                      return next
                    })
                  }
                />
                {a.name} <span className="cell-secondary mono">{a.site.code}</span>
              </label>
            </li>
          ))}
          {results.data.items.length === 0 && <li className="cell-muted">No assets found in your sites.</li>}
        </ul>
      )}
      <TextField
        label="Reason (optional)"
        name="add_reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      {add.error && <p className="field__error">{add.error.message}</p>}
    </Dialog>
  )
}

function EditDetailsDialog({ group, onClose, onSaved }: { group: AssetGroup; onClose: () => void; onSaved: () => Promise<void> }) {
  const groups = useQuery({ queryKey: groupKeys.list, queryFn: fetchGroups })
  const users = useQuery({ queryKey: assetKeys.userLookup, queryFn: fetchUserLookup })
  const [name, setName] = useState(group.name)
  const [description, setDescription] = useState(group.description)
  const [parent, setParent] = useState(group.parent?.id ?? '')
  const [owner, setOwner] = useState(group.owner?.id ?? '')
  const save = useMutation({
    mutationFn: () =>
      updateGroup(group.id, group.version, {
        name: name.trim(),
        description: description.trim(),
        parent: parent || null,
        owner: owner || null,
      }),
    onSuccess: async () => {
      await onSaved()
      onClose()
    },
  })
  const fieldErrors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog open title={`Edit ${group.name}`} confirmLabel="Save" busy={save.isPending} onClose={onClose} onConfirm={() => save.mutate()}>
      {save.error && !Object.keys(fieldErrors).length && <p className="field__error">{save.error.message}</p>}
      <TextField label="Name" name="edit_name" value={name} onChange={(e) => setName(e.target.value)} error={fieldErrors.name} />
      <TextField
        label="Description"
        name="edit_description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <SelectField
        label="Inside group"
        name="edit_parent"
        options={[
          { value: '', label: 'None (top level)' },
          ...(groups.data ?? []).filter((g) => g.id !== group.id).map((g) => ({ value: g.id, label: g.name })),
        ]}
        value={parent}
        onChange={(e) => setParent(e.target.value)}
        error={fieldErrors.parent}
      />
      <SelectField
        label="Owner"
        name="edit_owner"
        options={[{ value: '', label: 'No owner' }, ...(users.data ?? []).map((u) => ({ value: u.id, label: u.display_name }))]}
        value={owner}
        onChange={(e) => setOwner(e.target.value)}
      />
    </Dialog>
  )
}
