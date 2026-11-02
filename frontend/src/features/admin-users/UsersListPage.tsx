import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { fetchRoles, fetchUsers, queryKeys, type UserFilters } from '../../shared/api/accounts'
import { PERMISSIONS } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { userStatus } from './userStatus'

const STATUS_OPTIONS = [
  { value: '', label: 'Any status' },
  { value: 'active', label: 'Active' },
  { value: 'disabled', label: 'Disabled' },
  { value: 'locked', label: 'Locked' },
]

export function UsersListPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const filters: UserFilters = {
    q: params.get('q') ?? undefined,
    status: params.get('status') ?? undefined,
    role: params.get('role') ?? undefined,
  }
  const [search, setSearch] = useState(filters.q ?? '')

  const roles = useQuery({
    queryKey: queryKeys.roles,
    queryFn: fetchRoles,
    enabled: can(PERMISSIONS.rolesView),
  })
  const users = useInfiniteQuery({
    queryKey: queryKeys.users(filters),
    queryFn: ({ pageParam }) => fetchUsers(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })

  function update(next: Partial<UserFilters>) {
    const merged = { ...filters, ...next }
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(merged)) if (value) search.set(key, value)
    setParams(search, { replace: true })
  }

  function handleSearch(event: FormEvent) {
    event.preventDefault()
    update({ q: search.trim() || undefined })
  }

  const items = users.data?.pages.flatMap((page) => page.items) ?? []
  const total = users.data?.pages[0]?.count
  const filtered = Boolean(filters.q || filters.status || filters.role)

  return (
    <div className="page">
      <PageHeader
        title="Users & roles"
        meta={
          total === undefined
            ? 'Local accounts and their role assignments'
            : `${total} ${total === 1 ? 'account' : 'accounts'}`
        }
        actions={
          can(PERMISSIONS.usersManage) && (
            <Link className="button button--primary" to="/admin/users/new">
              Add user
            </Link>
          )
        }
      />

      <form className="toolbar" role="search" onSubmit={handleSearch}>
        <TextField
          label="Search"
          name="q"
          type="search"
          placeholder="Username, name or email"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <SelectField
          label="Status"
          name="status"
          options={STATUS_OPTIONS}
          value={filters.status ?? ''}
          onChange={(event) => update({ status: event.target.value || undefined })}
        />
        {roles.data && (
          <SelectField
            label="Role"
            name="role"
            options={[
              { value: '', label: 'Any role' },
              ...roles.data.map((role) => ({ value: role.code, label: role.name })),
            ]}
            value={filters.role ?? ''}
            onChange={(event) => update({ role: event.target.value || undefined })}
          />
        )}
        <div className="toolbar__actions">
          <Button type="submit">Apply</Button>
          {filtered && (
            <Button
              variant="quiet"
              onClick={() => {
                setSearch('')
                setParams(new URLSearchParams(), { replace: true })
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      </form>

      <section className="panel panel--flush" aria-live="polite">
        {users.isPending && <LoadingState label="Loading users…" />}
        {users.isError && <QueryErrorState error={users.error} what="user accounts" />}
        {users.isSuccess && items.length === 0 && (
          <EmptyState title={filtered ? 'No users match these filters.' : 'No user accounts yet.'}>
            {filtered
              ? 'Change or clear the filters.'
              : 'Create the first named admin with the bootstrap_admin command.'}
          </EmptyState>
        )}
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">User accounts</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Roles</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col">Created</th>
                </tr>
              </thead>
              <tbody>
                {items.map((user) => {
                  const status = userStatus(user)
                  return (
                    <tr key={user.id}>
                      <td>
                        <Link className="table-link" to={`/admin/users/${user.id}`}>
                          {user.display_name}
                        </Link>
                        <span className="cell-secondary mono">{user.username}</span>
                      </td>
                      <td>{user.email || <span className="cell-muted">Not set</span>}</td>
                      <td>
                        {user.roles.map((role) => role.name).join(', ') || (
                          <span className="cell-muted">No role</span>
                        )}
                      </td>
                      <td>
                        <StatusBadge tone={status.tone} label={status.label} />
                      </td>
                      <td className="nowrap">{formatDateTime(user.last_login)}</td>
                      <td className="nowrap">{formatDateTime(user.created_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {users.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => users.fetchNextPage()} busy={users.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}
