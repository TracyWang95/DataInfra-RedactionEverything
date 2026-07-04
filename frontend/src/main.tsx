// Copyright 2026 DataInfra-RedactionEverything Contributors

import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { queryClient } from '@/lib/query-client';
import { AuthProvider } from '@/features/auth/auth-context';
import { router } from './router';
import { ErrorBoundary } from './components/ErrorBoundary';
import { applyBrand } from '@/config/brand';
import './index.css';

applyBrand();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
