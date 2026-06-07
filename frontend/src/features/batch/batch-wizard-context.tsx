// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { createContext, useContext } from 'react';
import type { useBatchWizard } from './hooks/use-batch-wizard';

export type BatchWizardState = ReturnType<typeof useBatchWizard>;

const BatchWizardContext = createContext<BatchWizardState | null>(null);

export function BatchWizardProvider({
  value,
  children,
}: {
  value: BatchWizardState;
  children: React.ReactNode;
}) {
  return <BatchWizardContext.Provider value={value}>{children}</BatchWizardContext.Provider>;
}

export function useBatchWizardContext(): BatchWizardState {
  const ctx = useContext(BatchWizardContext);
  if (!ctx) {
    throw new Error('useBatchWizardContext must be used within BatchWizardProvider');
  }
  return ctx;
}
