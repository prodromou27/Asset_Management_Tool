import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuditLogPage } from '../features/admin-audit/AuditLogPage'
import { SecuritySettingsPage } from '../features/admin-security/SecuritySettingsPage'
import { UserCreatePage } from '../features/admin-users/UserCreatePage'
import { UserDetailPage } from '../features/admin-users/UserDetailPage'
import { UsersListPage } from '../features/admin-users/UsersListPage'
import { ChangePasswordPage } from '../features/auth/ChangePasswordPage'
import { LoginPage } from '../features/auth/LoginPage'
import { SystemHealthPage } from '../features/system-health/SystemHealthPage'
import { PERMISSIONS } from '../shared/api/types'
import { EmptyState } from '../shared/ui/States'
import { AppShell } from './AppShell'
import { createQueryClient } from './queryClient'
import { RequireAuth, RequirePermission } from './session'

function Protected({
  children,
  permission,
  what,
}: {
  children: ReactNode
  permission?: string
  what?: string
}) {
  return (
    <RequireAuth>
      <AppShell>
        {permission ? (
          <RequirePermission permission={permission} what={what ?? 'this page'}>
            {children}
          </RequirePermission>
        ) : (
          children
        )}
      </AppShell>
    </RequireAuth>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<Protected><SystemHealthPage /></Protected>} />
      <Route path="/account/password" element={<Protected><ChangePasswordPage /></Protected>} />
      <Route
        path="/admin/users"
        element={
          <Protected permission={PERMISSIONS.usersView} what="user accounts">
            <UsersListPage />
          </Protected>
        }
      />
      <Route
        path="/admin/users/new"
        element={
          <Protected permission={PERMISSIONS.usersManage} what="account creation">
            <UserCreatePage />
          </Protected>
        }
      />
      <Route
        path="/admin/users/:id"
        element={
          <Protected permission={PERMISSIONS.usersView} what="user accounts">
            <UserDetailPage />
          </Protected>
        }
      />
      <Route
        path="/admin/audit"
        element={
          <Protected permission={PERMISSIONS.auditView} what="the audit log">
            <AuditLogPage />
          </Protected>
        }
      />
      <Route
        path="/admin/security"
        element={
          <Protected permission={PERMISSIONS.securityView} what="security settings">
            <SecuritySettingsPage />
          </Protected>
        }
      />
      <Route
        path="*"
        element={
          <Protected>
            <EmptyState title="Page not found.">Check the address or use the navigation.</EmptyState>
          </Protected>
        }
      />
    </Routes>
  )
}

export function App({ client }: { client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? createQueryClient())
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
