import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuditLogPage } from '../features/admin-audit/AuditLogPage'
import { CategoriesPage } from '../features/admin-categories/CategoriesPage'
import { IntegrationDetailPage } from '../features/admin-integrations/IntegrationDetailPage'
import { IntegrationsPage } from '../features/admin-integrations/IntegrationsPage'
import { CandidatePage } from '../features/discovery/CandidatePage'
import { LicensesPage } from '../features/licenses/LicensesPage'
import { SubscriptionPage } from '../features/licenses/SubscriptionPage'
import { DiscoveryPage } from '../features/discovery/DiscoveryPage'
import { SitesPage } from '../features/admin-sites/SitesPage'
import { AssetDetailPage } from '../features/assets/AssetDetailPage'
import { AssetFormPage } from '../features/assets/AssetFormPage'
import { AssetsListPage } from '../features/assets/AssetsListPage'
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
        path="/assets"
        element={
          <Protected permission={PERMISSIONS.assetsView} what="assets">
            <AssetsListPage />
          </Protected>
        }
      />
      <Route
        path="/assets/new"
        element={
          <Protected permission={PERMISSIONS.assetsCreate} what="asset registration">
            <AssetFormPage />
          </Protected>
        }
      />
      <Route
        path="/assets/:id"
        element={
          <Protected permission={PERMISSIONS.assetsView} what="assets">
            <AssetDetailPage />
          </Protected>
        }
      />
      <Route
        path="/assets/:id/edit"
        element={
          <Protected permission={PERMISSIONS.assetsEdit} what="asset editing">
            <AssetFormPage />
          </Protected>
        }
      />
      <Route
        path="/discovery"
        element={
          <Protected permission={PERMISSIONS.discoveryView} what="discovery">
            <DiscoveryPage />
          </Protected>
        }
      />
      <Route
        path="/discovery/candidates/:id"
        element={
          <Protected permission={PERMISSIONS.discoveryView} what="discovery">
            <CandidatePage />
          </Protected>
        }
      />
      <Route
        path="/licenses"
        element={
          <Protected permission={PERMISSIONS.licensesView} what="licenses">
            <LicensesPage />
          </Protected>
        }
      />
      <Route
        path="/licenses/subscriptions/:id"
        element={
          <Protected permission={PERMISSIONS.licensesView} what="licenses">
            <SubscriptionPage />
          </Protected>
        }
      />
      <Route
        path="/admin/integrations"
        element={
          <Protected permission={PERMISSIONS.integrationsManage} what="integration administration">
            <IntegrationsPage />
          </Protected>
        }
      />
      <Route
        path="/admin/integrations/:id"
        element={
          <Protected permission={PERMISSIONS.integrationsManage} what="integration administration">
            <IntegrationDetailPage />
          </Protected>
        }
      />
      <Route
        path="/admin/sites"
        element={
          <Protected permission={PERMISSIONS.sitesManage} what="site administration">
            <SitesPage />
          </Protected>
        }
      />
      <Route
        path="/admin/categories"
        element={
          <Protected permission={PERMISSIONS.categoriesManage} what="category administration">
            <CategoriesPage />
          </Protected>
        }
      />
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
