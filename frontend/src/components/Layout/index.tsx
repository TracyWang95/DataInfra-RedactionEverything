// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { Outlet, useLocation } from 'react-router-dom';

import { ToastContainer } from '@/components/Toast';
import { OfflineBanner } from '@/components/OfflineBanner';
import { OnboardingGuide } from '@/components/OnboardingGuide';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';

import { AppSidebar } from './app-sidebar';
import { AppHeader } from './app-header';

export function Layout() {
  const location = useLocation();

  return (
    <SidebarProvider>
      <OfflineBanner />
      <AppSidebar />
      <SidebarInset className="h-dvh overflow-hidden">
        <AppHeader />
        {}
        <main
          key={location.pathname}
          className="flex min-h-0 flex-1 flex-col overflow-hidden animate-fade-in"
        >
          <Outlet />
        </main>
      </SidebarInset>

      <ToastContainer />
      <OnboardingGuide />
    </SidebarProvider>
  );
}

export default Layout;
