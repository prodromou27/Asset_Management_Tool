import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  disableUser,
  enableUser,
  fetchRoles,
  fetchUser,
  queryKeys,
  resetUserPassword,
  unlockUser,
  updateUser,
  bindEntra,
} from '../../shared/api/accounts'
import { assetKeys, fetchSites } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import { PERMISSIONS, type User } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { userStatus } from './userStatus'

type ActionKind = 'disable' | 'enable' | 'unlock' | 'reset' | null

export function UserDetailPage() {
  const { id = '' } = useParams()
  const location = useLocation()
  const { me, can } = useSession()
  const user = useQuery({ queryKey: queryKeys.user(id), queryFn: () => fetchUser(id) })
  const [notice, setNotice] = useState<string | null>(
    (location.state as { notice?: string } | null)?.notice ?? null,
  )

  if (user.isPending) return <LoadingState label="Loading account…" />
  if (user.isError) {
    return (
      <div className="page">
        <Breadcrumb />
        <QueryErrorState error={user.error} what="this account" />
      </div>
    )
  }

  const status = userStatus(user.data)
  const canManage = can(PERMISSIONS.usersManage)
  const isSelf = me?.id === user.data.id

  return (
    <div className="page">
      <Breadcrumb />
      <PageHeader
        title={user.data.display_name}
        meta={
          <>
            <span className="mono">{user.data.username}</span>{' '}
            <StatusBadge tone={status.tone} label={status.label} />
          </>
        }
        actions={
          can(PERMISSIONS.auditView) && (
            <Link
              className="button button--quiet"
              to={`/admin/audit?object_id=${encodeURIComponent(user.data.id)}`}
            >
              View audit history
            </Link>
          )
        }
      />
      {notice && (
        <p className="inline-success" role="status">
          {notice}
        </p>
      )}
      <div className="detail-layout">
        <div className="detail-layout__main">
          {canManage ? (
            <ProfileForm key={user.data.version} user={user.data} isSelf={isSelf} onSaved={setNotice} />
          ) : (
            <ProfileSummary user={user.data} />
          )}
        </div>
        <aside className="detail-layout__side">
          <AccountFacts user={user.data} />
          <SiteAccessPanel key={`sites-${user.data.version}`} user={user.data} canManage={canManage} onSaved={setNotice} />
          {canManage && <EntraBinding key={`entra-${user.data.version}`} user={user.data} onSaved={setNotice} />}
          {canManage && <AccountActions user={user.data} isSelf={isSelf} onDone={setNotice} />}
        </aside>
      </div>
    </div>
  )
}

function EntraBinding({ user, onSaved }: { user: User; onSaved: (notice: string) => void }) {
  const queryClient = useQueryClient()
  const [tenant, setTenant] = useState(user.entra_tenant_id ?? '')
  const [objectId, setObjectId] = useState(user.entra_object_id ?? '')
  const mutation = useMutation({
    mutationFn: () => bindEntra(user.id, user.version, tenant.trim() || null, objectId.trim() || null),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.user(user.id), saved)
      onSaved('Entra sign-in binding saved.')
    },
  })
  const errors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  return (
    <section className="panel" aria-labelledby="entra-heading">
      <h2 className="section-title" id="entra-heading">Microsoft Entra sign-in</h2>
      <p className="section-help">
        Link the exact tenant and user object IDs. Email addresses and token roles do not
        grant access. Changes sign this account out.
      </p>
      <form className="form-stack" onSubmit={(event) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <TextField label="Entra tenant ID" name="tenant_id" value={tenant}
          onChange={(event) => setTenant(event.target.value)} error={errors.tenant_id} />
        <TextField label="Entra user object ID" name="object_id" value={objectId}
          onChange={(event) => setObjectId(event.target.value)} error={errors.object_id} />
        {mutation.error && (
          <ErrorSummary message={mutation.error.message}
            fieldErrors={errors}
            fieldLabels={{ tenant_id: 'Entra tenant ID', object_id: 'Entra user object ID' }} />
        )}
        <Button type="submit" busy={mutation.isPending}>Save sign-in binding</Button>
      </form>
    </section>
  )
}

function Breadcrumb() {
  return (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <Link to="/admin/users">Users &amp; roles</Link>
    </nav>
  )
}

function ProfileSummary({ user }: { user: User }) {
  return (
    <section className="panel" aria-labelledby="profile-heading">
      <h2 className="section-title" id="profile-heading">
        Profile
      </h2>
      <dl className="meta-grid">
        <dt>Display name</dt>
        <dd>{user.display_name}</dd>
        <dt>Email</dt>
        <dd>{user.email || 'Not set'}</dd>
        <dt>Roles</dt>
        <dd>{user.roles.map((role) => role.name).join(', ') || 'No role'}</dd>
      </dl>
    </section>
  )
}

const PROFILE_LABELS: Record<string, string> = {
  display_name: 'Display name',
  email: 'Email',
  roles: 'Roles',
}

function ProfileForm({
  user,
  isSelf,
  onSaved,
}: {
  user: User
  isSelf: boolean
  onSaved: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const roles = useQuery({ queryKey: queryKeys.roles, queryFn: fetchRoles })
  const [displayName, setDisplayName] = useState(user.display_name)
  const [email, setEmail] = useState(user.email)
  const [selectedRoles, setSelectedRoles] = useState(user.roles.map((role) => role.code))
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: () =>
      updateUser(user.id, user.version, {
        display_name: displayName.trim(),
        email: email.trim(),
        roles: selectedRoles,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.user(user.id), updated)
      queryClient.invalidateQueries({ queryKey: ['users', 'list'] })
      queryClient.invalidateQueries({ queryKey: queryKeys.me })
      onSaved('Changes saved.')
    },
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string[]> = {}
    if (!displayName.trim()) errors.display_name = ['Enter a display name.']
    if (selectedRoles.length === 0) errors.roles = ['Select at least one role.']
    setClientErrors(errors)
    if (Object.keys(errors).length === 0) mutation.mutate()
  }

  const conflict = isApiError(mutation.error, 409) && mutation.error.code === 'VERSION_MISMATCH'
  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = Object.keys(clientErrors).length > 0 ? clientErrors : serverErrors

  return (
    <section className="panel" aria-labelledby="profile-heading">
      <h2 className="section-title" id="profile-heading">
        Profile and roles
      </h2>
      {(Object.keys(errors).length > 0 || mutation.error) && (
        <ErrorSummary
          message={
            Object.keys(errors).length > 0
              ? 'Check the highlighted fields.'
              : (mutation.error?.message ?? 'Could not save changes.')
          }
          fieldErrors={errors}
          fieldLabels={PROFILE_LABELS}
        />
      )}
      {conflict && (
        <Button
          variant="secondary"
          onClick={() => {
            mutation.reset()
            queryClient.invalidateQueries({ queryKey: queryKeys.user(user.id) })
          }}
        >
          Reload latest version
        </Button>
      )}
      <form onSubmit={handleSubmit} noValidate className="form-stack">
        <div className="form-grid">
          <TextField
            label={PROFILE_LABELS.display_name}
            name="display_name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            error={errors.display_name}
          />
          <TextField
            label={PROFILE_LABELS.email}
            name="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            error={errors.email}
          />
        </div>
        {roles.isPending && <LoadingState label="Loading roles…" />}
        {roles.isError && <QueryErrorState error={roles.error} what="roles" />}
        {roles.data && (
          <CheckboxGroup
            legend={PROFILE_LABELS.roles}
            name="roles"
            options={roles.data.map((role) => ({
              value: role.code,
              label: role.name,
              description: role.description,
            }))}
            value={selectedRoles}
            onChange={setSelectedRoles}
            error={errors.roles}
          />
        )}
        {isSelf && (
          <p className="field__help">You cannot remove the System Admin role from your own account.</p>
        )}
        <div className="form-actions">
          <Button type="submit" variant="primary" busy={mutation.isPending}>
            Save changes
          </Button>
        </div>
      </form>
    </section>
  )
}

function AccountFacts({ user }: { user: User }) {
  return (
    <section className="panel" aria-labelledby="facts-heading">
      <h2 className="section-title" id="facts-heading">
        Account
      </h2>
      <dl className="meta-grid meta-grid--stacked">
        <dt>Last sign-in</dt>
        <dd>{formatDateTime(user.last_login)}</dd>
        <dt>Password changed</dt>
        <dd>{formatDateTime(user.password_changed_at, 'Not recorded')}</dd>
        {user.is_locked && (
          <>
            <dt>Locked until</dt>
            <dd>{formatDateTime(user.locked_until)}</dd>
          </>
        )}
        <dt>Created</dt>
        <dd>
          {formatDateTime(user.created_at)}
          {user.created_by ? ` by ${user.created_by}` : ' by bootstrap command'}
        </dd>
        {!user.is_active && (
          <>
            <dt>Disabled</dt>
            <dd>
              {formatDateTime(user.disabled_at)}
              {user.disabled_by && ` by ${user.disabled_by}`}
            </dd>
            <dt>Reason</dt>
            <dd>{user.disabled_reason || 'Not recorded'}</dd>
          </>
        )}
        <dt>Record version</dt>
        <dd className="mono">{user.version}</dd>
      </dl>
    </section>
  )
}

function AccountActions({
  user,
  isSelf,
  onDone,
}: {
  user: User
  isSelf: boolean
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [action, setAction] = useState<ActionKind>(null)
  const [reason, setReason] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [clientError, setClientError] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: async (kind: Exclude<ActionKind, null>) => {
      switch (kind) {
        case 'disable':
          return disableUser(user.id, reason.trim())
        case 'enable':
          return enableUser(user.id)
        case 'unlock':
          return unlockUser(user.id)
        case 'reset':
          return resetUserPassword(user.id, password)
      }
    },
    onSuccess: (updated, kind) => {
      queryClient.setQueryData(queryKeys.user(user.id), updated)
      queryClient.invalidateQueries({ queryKey: ['users', 'list'] })
      const messages = {
        disable: `${user.username} disabled. Active sessions were signed out.`,
        enable: `${user.username} enabled.`,
        unlock: `${user.username} unlocked.`,
        reset: `Temporary password set for ${user.username}. Their sessions were signed out.`,
      }
      onDone(messages[kind])
      close()
    },
  })

  function open(kind: Exclude<ActionKind, null>) {
    mutation.reset()
    setReason('')
    setPassword('')
    setConfirm('')
    setClientError({})
    setAction(kind)
  }

  function close() {
    setAction(null)
  }

  function confirmAction() {
    if (!action) return
    const errors: Record<string, string[]> = {}
    if (action === 'disable' && reason.trim().length < 5) {
      errors.reason = ['Enter a reason of at least 5 characters.']
    }
    if (action === 'reset') {
      if (!password) errors.password = ['Enter a temporary password.']
      else if (password !== confirm) errors.confirm = ['The passwords do not match.']
    }
    setClientError(errors)
    if (Object.keys(errors).length === 0) mutation.mutate(action)
  }

  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = { ...serverErrors, ...clientError }
  const summary =
    mutation.error && Object.keys(serverErrors).length === 0 ? mutation.error.message : null

  return (
    <section className="panel" aria-labelledby="actions-heading">
      <h2 className="section-title" id="actions-heading">
        Account actions
      </h2>
      <div className="action-list">
        <Button onClick={() => open('reset')}>Set temporary password</Button>
        {user.is_locked && <Button onClick={() => open('unlock')}>Unlock</Button>}
        {user.is_active ? (
          !isSelf && (
            <Button variant="quiet" className="button--danger-quiet" onClick={() => open('disable')}>
              Disable account
            </Button>
          )
        ) : (
          <Button onClick={() => open('enable')}>Enable account</Button>
        )}
      </div>

      <Dialog
        open={action === 'disable'}
        title={`Disable ${user.username}?`}
        confirmLabel="Disable account"
        confirmVariant="danger"
        busy={mutation.isPending}
        onConfirm={confirmAction}
        onClose={close}
      >
        <p>
          Affects 1 account. Active sessions are signed out immediately and sign-in is blocked.
          Audit history and ownership records are kept; you can enable the account again later.
        </p>
        {summary && <p className="field__error">{summary}</p>}
        <TextField
          label="Reason"
          name="reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          error={errors.reason}
          help="Recorded in the audit log."
          autoFocus
        />
      </Dialog>

      <Dialog
        open={action === 'enable'}
        title={`Enable ${user.username}?`}
        confirmLabel="Enable account"
        busy={mutation.isPending}
        onConfirm={confirmAction}
        onClose={close}
      >
        <p>The user can sign in again with their existing roles.</p>
        {summary && <p className="field__error">{summary}</p>}
      </Dialog>

      <Dialog
        open={action === 'unlock'}
        title={`Unlock ${user.username}?`}
        confirmLabel="Unlock"
        busy={mutation.isPending}
        onConfirm={confirmAction}
        onClose={close}
      >
        <p>Clears the failed sign-in lockout before it expires.</p>
        {summary && <p className="field__error">{summary}</p>}
      </Dialog>

      <Dialog
        open={action === 'reset'}
        title={`Set a temporary password for ${user.username}`}
        confirmLabel="Set password"
        busy={mutation.isPending}
        onConfirm={confirmAction}
        onClose={close}
      >
        <p>
          Signs out the user&apos;s sessions. They must choose a new password at next sign-in.
        </p>
        {summary && <p className="field__error">{summary}</p>}
        <TextField
          label="Temporary password"
          name="temporary_password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
          autoFocus
        />
        <TextField
          label="Confirm temporary password"
          name="confirm_temporary_password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          error={errors.confirm}
        />
      </Dialog>
    </section>
  )
}

function SiteAccessPanel({
  user,
  canManage,
  onSaved,
}: {
  user: User
  canManage: boolean
  onSaved: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites, enabled: canManage })
  const [allSites, setAllSites] = useState(user.all_sites)
  const [selected, setSelected] = useState(user.sites.map((s) => s.id))

  const mutation = useMutation({
    mutationFn: () =>
      updateUser(user.id, user.version, { all_sites: allSites, site_ids: allSites ? [] : selected }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.user(user.id), updated)
      queryClient.invalidateQueries({ queryKey: ['users', 'list'] })
      onSaved("Site access saved. It applies on the user's next request.")
    },
  })

  return (
    <section className="panel" aria-labelledby="sites-heading">
      <h2 className="section-title" id="sites-heading">
        Site access
      </h2>
      {!canManage ? (
        <p>
          {user.all_sites
            ? 'All sites'
            : user.sites.length
              ? user.sites.map((s) => s.code).join(', ')
              : 'No sites. This user cannot see any assets.'}
        </p>
      ) : (
        <form
          className="form-stack"
          onSubmit={(event) => {
            event.preventDefault()
            mutation.mutate()
          }}
        >
          {mutation.error && (
            <p className="field__error" role="alert">
              {mutation.error.message}
            </p>
          )}
          <CheckboxGroup
            legend="Scope"
            name="all_sites"
            options={[
              {
                value: 'all',
                label: 'All sites',
                description: 'Includes sites added later. Use for administrators only.',
              },
            ]}
            value={allSites ? ['all'] : []}
            onChange={(v) => setAllSites(v.includes('all'))}
          />
          {!allSites && (
            <>
              {sites.isPending && <LoadingState label="Loading sites…" />}
              {sites.isError && <QueryErrorState error={sites.error} what="sites" />}
              {sites.data && (
                <CheckboxGroup
                  legend="Granted sites (child sites included)"
                  name="site_ids"
                  options={sites.data.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` }))}
                  value={selected}
                  onChange={setSelected}
                />
              )}
              {selected.length === 0 && (
                <p className="field__help">With no sites, this user cannot see any assets.</p>
              )}
            </>
          )}
          <div className="form-actions">
            <Button type="submit" busy={mutation.isPending}>
              Save site access
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}
