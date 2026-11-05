import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { BackupsPage } from '../features/backups/BackupsPage'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { AuditLogPage } from '../features/admin-audit/AuditLogPage'
import { CategoriesPage } from '../features/admin-categories/CategoriesPage'
import { IntegrationDetailPage } from '../features/admin-integrations/IntegrationDetailPage'
import { IntegrationsPage } from '../features/admin-integrations/IntegrationsPage'
import { CandidatePage } from '../features/discovery/CandidatePage'
import { ExportsPage } from '../features/exports/ExportsPage'
import { CataloguePage } from '../features/lifecycle/CataloguePage'
import { LifecyclePage } from '../features/lifecycle/LifecyclePage'
import { ProductPage } from '../features/lifecycle/ProductPage'
import { SoftwarePage } from '../features/software/SoftwarePage'
import { SoftwareProductPage } from '../features/software/SoftwareProductPage'
import { GroupDetailPage } from '../features/groups/GroupDetailPage'
import { GroupsPage } from '../features/groups/GroupsPage'
import { ImportJobPage } from '../features/imports/ImportJobPage'
import { ImportsPage } from '../features/imports/ImportsPage'
import { LicenseProductPage } from '../features/licenses/LicenseProductPage'
import { CertificatePage } from '../features/domains/CertificatePage'
import { DomainsPage } from '../features/domains/DomainsPage'
import { SmtpPage } from '../features/admin-smtp/SmtpPage'
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
      <Route path="/admin/backups" element={<Protected permission={PERMISSIONS.backupsView} what="backups and recovery"><BackupsPage /></Protected>} />
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
        path="/groups"
        element={
          <Protected permission={PERMISSIONS.groupsView} what="groups">
            <GroupsPage />
          </Protected>
        }
      />
      <Route
        path="/groups/:id"
        element={
          <Protected permission={PERMISSIONS.groupsView} what="groups">
            <GroupDetailPage />
          </Protected>
        }
      />
      <Route
        path="/software"
        element={
          <Protected what="software and licenses">
            <SoftwarePage />
          </Protected>
        }
      />
      <Route
        path="/software/products/:id"
        element={
          <Protected permission={PERMISSIONS.assetsView} what="software">
            <SoftwareProductPage />
          </Protected>
        }
      />
      <Route
        path="/lifecycle"
        element={
          <Protected permission={PERMISSIONS.lifecycleView} what="lifecycle">
            <LifecyclePage />
          </Protected>
        }
      />
      <Route
        path="/lifecycle/catalogue"
        element={
          <Protected permission={PERMISSIONS.lifecycleView} what="the lifecycle catalogue">
            <CataloguePage />
          </Protected>
        }
      />
      <Route
        path="/lifecycle/catalogue/:id"
        element={
          <Protected permission={PERMISSIONS.lifecycleView} what="the lifecycle catalogue">
            <ProductPage />
          </Protected>
        }
      />
      <Route
        path="/exports"
        element={
          <Protected permission={PERMISSIONS.exportsRun} what="exports">
            <ExportsPage />
          </Protected>
        }
      />
      <Route
        path="/imports"
        element={
          <Protected permission={PERMISSIONS.importsRun} what="imports">
            <ImportsPage />
          </Protected>
        }
      />
      <Route
        path="/imports/new"
        element={
          <Protected permission={PERMISSIONS.importsRun} what="imports">
            <ImportJobPage />
          </Protected>
        }
      />
      <Route
        path="/imports/:id"
        element={
          <Protected permission={PERMISSIONS.importsRun} what="imports">
            <ImportJobPage />
          </Protected>
        }
      />
      <Route
        path="/admin/smtp"
        element={
          <Protected permission={PERMISSIONS.notificationsView} what="SMTP and notifications">
            <SmtpPage />
          </Protected>
        }
      />
      <Route
        path="/domains"
        element={
          <Protected permission={PERMISSIONS.certificatesView} what="domains and certificates">
            <DomainsPage />
          </Protected>
        }
      />
      <Route
        path="/certificates/:id"
        element={
          <Protected permission={PERMISSIONS.certificatesView} what="certificates">
            <CertificatePage />
          </Protected>
        }
      />
      <Route path="/licenses" element={<Navigate to="/software?tab=m365" replace />} />
      <Route path="/licenses/subscriptions/:id" element={<SubscriptionRedirect />} />
      <Route
        path="/software/m365/:id"
        element={
          <Protected permission={PERMISSIONS.licensesView} what="licenses">
            <SubscriptionPage />
          </Protected>
        }
      />
      <Route
        path="/software/licenses/:id"
        element={
          <Protected permission={PERMISSIONS.licensesView} what="licenses">
            <LicenseProductPage />
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

/** Old Microsoft 365 subscription links (before Software & Licenses, Task 016b). */
function SubscriptionRedirect() {
  const { id = '' } = useParams()
  return <Navigate to={`/software/m365/${id}`} replace />
}
