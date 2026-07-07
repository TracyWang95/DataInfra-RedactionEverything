// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import {
  listStructuredConnections,
  listStructuredDatasets,
  type StructuredConnection,
  type StructuredDataset,
} from '@/services/structuredApi';

export function useDatasets() {
  const [datasets, setDatasets] = React.useState<StructuredDataset[]>([]);
  const [loading, setLoading] = React.useState(true);
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const response = await listStructuredDatasets();
      setDatasets(response.datasets);
      return response.datasets;
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { datasets, loading, refresh };
}

export function useConnections() {
  const [connections, setConnections] = React.useState<StructuredConnection[]>([]);
  const [loading, setLoading] = React.useState(true);
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const nextConnections = await listStructuredConnections();
      setConnections(nextConnections);
      return nextConnections;
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { connections, loading, refresh };
}
