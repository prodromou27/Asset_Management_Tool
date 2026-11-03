import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { assetKeys, fetchCategories } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  approveCandidate,
  discoveryKeys,
  fetchCandidate,
  fetchObservation,
  holdCandidate,
  rejectCandidate,
} from '../../shared/api/discovery'
import { PERMISSIONS, type Candidate } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { BUSINESS_STATUS, categoryOptions, options } from '../assets/labels'
import {
  agreement,
  CANDIDATE_STATUS,
  KEY_LABEL,
  KEY_STRENGTH,
  RULE_LABEL,
  RULE_TONE,
  scoreLabel,
} from './labels'

type Normalized = {
  manufacturer?: string | null
  model?: string | null
  serial_number?: string | null
  serial_verified?: boolean
  hardware_uuid?: string | null
  hostnames?: string[]
  interfaces?: { name: string; mac: string | null }[]
  ip_addresses?: { address: string; vrf: string; interface: string | null }[]
  os_name?: string | null
  os_version?: string | null
  firmware_version?: string | null
  device_type?: string | null
  warnings?: string[]
}

export function CandidatePage() {
  const { id = '' } = useParams()
  const candidate = useQuery({ queryKey: discoveryKeys.candidate(id), queryFn: () => fetchCandidate(id) })

  if (candidate.isPending) return <LoadingState label="Loading candidate…" />
  if (candidate.isError) {
    return (
      <div className="page">
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to="/discovery">Discovery</Link>
        </nav>
        <QueryErrorState error={candidate.error} what="this candidate" />
      </div>
    )
  }
  const c = candidate.data
  const open = c.status === 'open' || c.status === 'held'

  return (
    <div className="page page--wide">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/discovery">Discovery</Link>
      </nav>
      <PageHeader
        title={`Device ${c.external_id} from ${c.instance.name}`}
        meta={
          <>
            <StatusBadge tone={RULE_TONE[c.rule]} label={RULE_LABEL[c.rule]} />
            <span>Confidence {scoreLabel(c.score)}</span>
            <span>Status: {CANDIDATE_STATUS[c.status]}</span>
            <span className="mono">{c.site.code}</span>
          </>
        }
      />
      {c.conflicts.length > 0 && (
        <div className="inline-note inline-note--warning" role="note">
          <p className="history-reason">Check before deciding:</p>
          <ul className="change-list">
            {c.conflicts.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="detail-layout">
        <div className="detail-layout__main">
          <ObservedDevice candidate={c} />
          <Matches candidate={c} />
        </div>
        <aside className="detail-layout__side">
          {open ? <Decision key={c.version} candidate={c} /> : <DecisionSummary candidate={c} />}
        </aside>
      </div>
    </div>
  )
}

function ObservedDevice({ candidate }: { candidate: Candidate }) {
  const [showRaw, setShowRaw] = useState(false)
  const raw = useQuery({
    queryKey: discoveryKeys.observation(candidate.observation.id),
    queryFn: () => fetchObservation(candidate.observation.id),
    enabled: showRaw,
  })
  const n = candidate.observation.normalized as Normalized
  const unknown = (text = 'Not reported') => <span className="cell-muted">{text}</span>

  return (
    <section className="panel" aria-labelledby="observed-heading">
      <div className="section-header">
        <h2 className="section-title" id="observed-heading">
          Observed device
        </h2>
        <Button variant="quiet" aria-expanded={showRaw} onClick={() => setShowRaw((v) => !v)}>
          {showRaw ? 'Hide raw payload' : 'Show raw payload'}
        </Button>
      </div>
      <dl className="meta-grid meta-grid--two">
        <dt>Manufacturer</dt>
        <dd>{n.manufacturer ?? unknown()}</dd>
        <dt>Model</dt>
        <dd>{n.model ?? unknown()}</dd>
        <dt>Serial number</dt>
        <dd className="mono">
          {n.serial_number ?? unknown('Unknown')}
          {n.serial_number && !n.serial_verified && (
            <span className="cell-secondary">Not verified (manufacturer unknown)</span>
          )}
        </dd>
        <dt>Hardware UUID</dt>
        <dd className="mono">{n.hardware_uuid ?? unknown()}</dd>
        <dt>Operating system</dt>
        <dd>{[n.os_name, n.os_version].filter(Boolean).join(' ') || unknown()}</dd>
        <dt>Firmware</dt>
        <dd className="mono">{n.firmware_version ?? unknown()}</dd>
        <dt>Hostnames</dt>
        <dd className="mono">{n.hostnames?.length ? n.hostnames.join(', ') : unknown('None')}</dd>
        <dt>Device type</dt>
        <dd>
          {n.device_type ?? unknown()}
          {candidate.suggested_category && (
            <span className="cell-secondary">Suggested category: {candidate.suggested_category.name}</span>
          )}
        </dd>
      </dl>
      {(n.interfaces?.length ?? 0) + (n.ip_addresses?.length ?? 0) > 0 && (
        <table className="data-table data-table--compact">
          <caption className="audit-detail__caption">Interfaces and addresses</caption>
          <thead>
            <tr>
              <th scope="col">Interface</th>
              <th scope="col">MAC</th>
              <th scope="col">IP addresses (VRF)</th>
            </tr>
          </thead>
          <tbody>
            {(n.interfaces ?? []).map((i) => (
              <tr key={i.name}>
                <td className="mono">{i.name}</td>
                <td className="mono">{i.mac ?? unknown()}</td>
                <td className="mono">
                  {(n.ip_addresses ?? [])
                    .filter((a) => a.interface === i.name)
                    .map((a) => `${a.address}${a.vrf ? ` (${a.vrf})` : ''}`)
                    .join(', ') || unknown('None')}
                </td>
              </tr>
            ))}
            {(n.ip_addresses ?? [])
              .filter((a) => !a.interface || !(n.interfaces ?? []).some((i) => i.name === a.interface))
              .map((a) => (
                <tr key={a.address}>
                  <td className="cell-muted">No interface</td>
                  <td />
                  <td className="mono">{`${a.address}${a.vrf ? ` (${a.vrf})` : ''}`}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      {n.warnings && n.warnings.length > 0 && (
        <>
          <h3 className="subsection-title">Normalisation warnings</h3>
          <ul className="change-list">
            {n.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      )}
      <p className="field__help">
        Observed {formatDateTime(candidate.observation.observed_at)}, received{' '}
        {formatDateTime(candidate.observation.received_at)}. Checksum{' '}
        <span className="mono">{candidate.observation.checksum.slice(0, 12)}…</span>
      </p>
      {showRaw && (
        <div aria-live="polite">
          {raw.isPending && <LoadingState label="Loading raw payload…" />}
          {raw.isError && <QueryErrorState error={raw.error} what="the raw payload" />}
          {raw.data && (
            <pre className="raw-payload" tabIndex={0} aria-label="Raw source payload">
              {JSON.stringify(raw.data.payload, null, 2)}
            </pre>
          )}
        </div>
      )}
    </section>
  )
}

function Matches({ candidate }: { candidate: Candidate }) {
  return (
    <section className="panel panel--flush" aria-labelledby="matches-heading">
      <h2 className="section-title section-title--inset" id="matches-heading">
        Possible matches
      </h2>
      {candidate.matches.length === 0 ? (
        <p className="state">
          No visible asset shares an identifier with this device.
          {candidate.hidden_match_count > 0 &&
            ` ${candidate.hidden_match_count} possible match(es) are in sites you cannot access.`}
        </p>
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Confidence</th>
                <th scope="col">Matching identifiers</th>
                <th scope="col">Manufacturer</th>
                <th scope="col">Category</th>
              </tr>
            </thead>
            <tbody>
              {candidate.matches.map((m) => (
                <tr key={m.asset_id} className="row--top">
                  <td>
                    <Link to={`/assets/${m.asset_id}`}>{m.asset_name}</Link>
                  </td>
                  <td className="nowrap">{scoreLabel(m.score)}</td>
                  <td>
                    <ul className="change-list change-list--plain">
                      {m.keys.map((k) => (
                        <li key={k.key}>
                          <StatusBadge {...KEY_STRENGTH[k.strength]} />{' '}
                          {KEY_LABEL[k.key] ?? k.key}: <span className="mono">{k.value}</span>
                        </li>
                      ))}
                    </ul>
                  </td>
                  <td>{agreement(m.manufacturer_agrees, 'Unknown on one side')}</td>
                  <td>{agreement(m.category_agrees, 'No type reported')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {candidate.hidden_match_count > 0 && (
            <p className="field__help table-note">
              {candidate.hidden_match_count} more possible match(es) are in sites you cannot access.
            </p>
          )}
        </>
      )}
      <p className="field__help table-note">
        IP address, hostname or MAC alone never links a device automatically.
      </p>
    </section>
  )
}

type Action = 'link' | 'create' | 'hold' | 'reject'

function Decision({ candidate }: { candidate: Candidate }) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [action, setAction] = useState<Action>(() =>
    candidate.matches.length ? 'link' : can(PERMISSIONS.assetsCreate) ? 'create' : 'reject',
  )
  const [asset, setAsset] = useState(candidate.proposed_asset?.id ?? candidate.matches[0]?.asset_id ?? '')
  const [name, setName] = useState('')
  const [category, setCategory] = useState(candidate.suggested_category?.id ?? '')
  const [businessStatus, setBusinessStatus] = useState('deployed')
  const [reason, setReason] = useState('')
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})
  const categories = useQuery({
    queryKey: assetKeys.categories,
    queryFn: fetchCategories,
    enabled: action === 'create',
  })

  const mutation = useMutation({
    mutationFn: () => {
      const why = reason.trim()
      if (action === 'reject') return rejectCandidate(candidate.id, candidate.version, why)
      if (action === 'hold') return holdCandidate(candidate.id, candidate.version, why)
      if (action === 'link') return approveCandidate(candidate.id, candidate.version, { action, asset, reason: why })
      return approveCandidate(candidate.id, candidate.version, {
        action,
        reason: why,
        name: name.trim() || undefined,
        category: category || undefined,
        business_status: businessStatus,
      })
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(discoveryKeys.candidate(candidate.id), updated)
      queryClient.invalidateQueries({ queryKey: ['discovery', 'candidates'] })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  if (!can(PERMISSIONS.reconciliationDecide)) {
    return (
      <section className="panel">
        <h2 className="section-title">Decision</h2>
        <p>Awaiting a decision by an ITAM Manager or System Admin.</p>
      </section>
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string[]> = {}
    if (reason.trim().length < 5) errors.reason = ['Enter a reason of at least 5 characters.']
    if (action === 'link' && !asset) errors.asset = ['Choose the asset to link.']
    if (action === 'create' && !category) errors.category = ['Choose a category.']
    setClientErrors(errors)
    if (!Object.keys(errors).length) mutation.mutate()
  }

  const server = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = Object.keys(clientErrors).length ? clientErrors : server
  const canCreate = can(PERMISSIONS.assetsCreate)
  const actions: { value: Action; label: string }[] = [
    ...(candidate.matches.length ? [{ value: 'link' as const, label: 'Link to an existing asset' }] : []),
    ...(canCreate ? [{ value: 'create' as const, label: 'Create a new asset' }] : []),
    ...(candidate.status === 'open' ? [{ value: 'hold' as const, label: 'Put on hold' }] : []),
    { value: 'reject', label: 'Reject (not an inventory asset)' },
  ]

  return (
    <section className="panel" aria-labelledby="decision-heading">
      <h2 className="section-title" id="decision-heading">
        Decision
      </h2>
      {(Object.keys(errors).length > 0 || mutation.error) && (
        <ErrorSummary
          message={Object.keys(errors).length ? 'Check the highlighted fields.' : (mutation.error?.message ?? 'Could not save the decision.')}
          fieldErrors={errors}
          fieldLabels={{ reason: 'Reason', asset: 'Asset', category: 'Category', name: 'Name' }}
        />
      )}
      <form className="form-stack" onSubmit={submit} noValidate>
        <fieldset className="fieldset">
          <legend className="field__label">Action</legend>
          <div className="radio-list">
            {actions.map((a) => (
              <label key={a.value} className="radio">
                <input
                  type="radio"
                  name="decision_action"
                  value={a.value}
                  checked={action === a.value}
                  onChange={() => setAction(a.value)}
                />
                {a.label}
              </label>
            ))}
          </div>
        </fieldset>
        {action === 'link' && (
          <SelectField
            label="Asset"
            name="link_asset"
            options={[
              { value: '', label: 'Choose a match' },
              ...candidate.matches.map((m) => ({ value: m.asset_id, label: `${m.asset_name} (${m.score})` })),
            ]}
            value={asset}
            onChange={(e) => setAsset(e.target.value)}
            error={errors.asset}
            help="Links this source device to the asset. Technical fields update under field authority; locked values raise conflicts."
          />
        )}
        {action === 'create' && (
          <>
            <TextField
              label="Name"
              name="new_name"
              placeholder={(candidate.observation.normalized as Normalized).hostnames?.[0]?.split('.')[0] ?? candidate.external_id}
              value={name}
              onChange={(e) => setName(e.target.value)}
              error={errors.name}
              help="Leave empty to use the short hostname or device ID."
            />
            <SelectField
              label="Category"
              name="new_category"
              options={[{ value: '', label: 'Choose a category' }, ...categoryOptions(categories.data ?? [], { activeOnly: true })]}
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              error={errors.category}
            />
            <SelectField
              label="Business status"
              name="new_status"
              options={options(BUSINESS_STATUS)}
              value={businessStatus}
              onChange={(e) => setBusinessStatus(e.target.value)}
            />
            <p className="field__help">Created in site {candidate.site.code}. Owner and location can be set afterwards.</p>
          </>
        )}
        <TextAreaField
          label="Reason"
          name="decision_reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          error={errors.reason}
          help="Recorded in the audit log."
        />
        <div className="form-actions">
          <Button type="submit" variant={action === 'reject' ? 'danger' : 'primary'} busy={mutation.isPending}>
            {{ link: 'Link device', create: 'Create asset', hold: 'Put on hold', reject: 'Reject device' }[action]}
          </Button>
        </div>
      </form>
    </section>
  )
}

function DecisionSummary({ candidate }: { candidate: Candidate }) {
  return (
    <section className="panel" aria-labelledby="decision-heading">
      <h2 className="section-title" id="decision-heading">
        Decision
      </h2>
      <dl className="meta-grid meta-grid--stacked">
        <dt>Outcome</dt>
        <dd>{CANDIDATE_STATUS[candidate.status]}</dd>
        <dt>Decided</dt>
        <dd>
          {formatDateTime(candidate.decided_at)}
          {candidate.decided_by && ` by ${candidate.decided_by}`}
        </dd>
        <dt>Reason</dt>
        <dd>{candidate.decision_reason || 'Not recorded'}</dd>
        {candidate.resulting_asset && (
          <>
            <dt>Asset</dt>
            <dd>
              <Link to={`/assets/${candidate.resulting_asset.id}`}>{candidate.resulting_asset.name}</Link>
            </dd>
          </>
        )}
      </dl>
    </section>
  )
}
