import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { isApiError } from '../../shared/api/client'
import {
  addManualSoftware,
  fetchAssetSoftware,
  removeManualSoftware,
  softwareKeys,
} from '../../shared/api/software'
import { PERMISSIONS, type SoftwareInstallation } from '../../shared/api/types'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { TextAreaField, TextField } from '../../shared/ui/Field'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { LIFECYCLE_STATUS } from '../lifecycle/labels'

/** docs/08 asset detail "Software" tab. Discovered rows come from the asset's linked
 * sources; manual rows can be added and removed by people who may edit the asset. */
export function AssetSoftwarePanel({ assetId, archived }: { assetId: string; archived: boolean }) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [showRemoved, setShowRemoved] = useState(false)
  const rows = useQuery({
    queryKey: softwareKeys.asset(assetId, showRemoved),
    queryFn: () => fetchAssetSoftware(assetId, showRemoved),
  })
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<SoftwareInstallation | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: softwareKeys.all })
  const remove = useMutation({
    mutationFn: (reason: string) => removeManualSoftware(removing!.id, reason),
    onSuccess: () => {
      setRemoving(null)
      refresh()
    },
  })
  const edit = can(PERMISSIONS.assetsEdit) && !archived

  return (
    <section className="panel panel--flush" aria-labelledby="software-title">
      <div className="panel__header">
        <h2 className="section-title" id="software-title">
          Installed software
        </h2>
        <div className="action-row">
          <label className="checkbox checkbox--inline">
            <input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} />
            <span className="checkbox__label">Show removed</span>
          </label>
          {edit && <Button onClick={() => setAdding(true)}>Record software</Button>}
        </div>
      </div>
      {rows.isPending && <LoadingState label="Loading software…" />}
      {rows.isError && <QueryErrorState error={rows.error} what="software" />}
      {rows.isSuccess && rows.data.length === 0 && (
        <EmptyState title="No software recorded.">
          Software appears when a linked Endpoint Central or Intune integration collects it, or when
          it is recorded here.
        </EmptyState>
      )}
      {rows.data && rows.data.length > 0 && (
        <table className="data-table">
          <caption className="visually-hidden">Installed software</caption>
          <thead>
            <tr>
              <th scope="col">Product</th>
              <th scope="col">Version</th>
              <th scope="col">Source</th>
              <th scope="col">Seen</th>
              <th scope="col">Lifecycle</th>
              {edit && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.data.map((r) => {
              const s = LIFECYCLE_STATUS[r.lifecycle_status]
              return (
                <tr key={r.id}>
                  <td>
                    <Link to={`/software/products/${r.product_id}`}>{r.name}</Link>
                    <span className="cell-secondary">{r.publisher || 'Publisher not reported'}</span>
                    {r.removed_at && <span className="cell-secondary">Removed {formatDate(r.removed_at)}: {r.removed_reason}</span>}
                  </td>
                  <td className="mono">{r.version || '–'}</td>
                  <td>
                    {r.source}
                    {r.created_by && <span className="cell-secondary">by {r.created_by}</span>}
                  </td>
                  <td className="nowrap">
                    {formatDate(r.first_seen_at)} – {formatDate(r.last_seen_at)}
                  </td>
                  <td>
                    <StatusBadge tone={s.tone} label={s.label} />
                  </td>
                  {edit && (
                    <td>
                      {r.source === 'Manual' && !r.removed_at && (
                        <Button variant="quiet" onClick={() => setRemoving(r)}>
                          Remove…
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {adding && <AddDialog assetId={assetId} onClose={() => setAdding(false)} onSaved={refresh} />}
      {removing && (
        <ReasonDialog
          title={`Remove ${removing.name} ${removing.version}`.trim()}
          confirmLabel="Remove entry"
          help="The entry is kept as removed for the record."
          busy={remove.isPending}
          error={remove.isError ? remove.error.message : null}
          onClose={() => setRemoving(null)}
          onConfirm={(reason) => remove.mutate(reason)}
        />
      )}
    </section>
  )
}

function AddDialog({ assetId, onClose, onSaved }: { assetId: string; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ name: '', publisher: '', version: '', note: '' })
  const save = useMutation({
    mutationFn: () => addManualSoftware(assetId, form),
    onSuccess: () => {
      onSaved()
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog open title="Record installed software" confirmLabel="Record software" busy={save.isPending} onClose={onClose} onConfirm={() => save.mutate()}>
      {save.isError && <ErrorSummary message={save.error.message} fieldErrors={errors} fieldLabels={{ name: 'Name' }} />}
      <TextField label="Name" name="sw-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} />
      <TextField label="Publisher" name="sw-publisher" value={form.publisher} onChange={(e) => setForm({ ...form, publisher: e.target.value })} />
      <TextField label="Version" name="sw-version" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
      <TextAreaField label="Note (optional)" name="sw-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
    </Dialog>
  )
}
