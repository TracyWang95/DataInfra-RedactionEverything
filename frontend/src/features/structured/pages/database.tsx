// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useT } from '@/i18n';
import {
  createStructuredConnection,
  deleteStructuredConnection,
  discoverStructuredConnectionDatasets,
  registerStructuredConnectionDatasets,
  testStructuredConnection,
  type StructuredConnectionPayload,
  type StructuredDataset,
} from '@/services/structuredApi';
import { DatabaseConnectionCard, DiscoveredTablesCard } from '../components/database-cards';
import { StructuredFrame } from '../components/structured-frame';
import { useNotice } from '../hooks/use-notice';
import { useConnections, useDatasets } from '../hooks/use-structured-data';
import { emptyConnection } from '../lib/constants';
import { compareStructuredDatasetsForReview, datasetKey, toggleSet } from '../lib/dataset-utils';

export function StructuredDatabase() {
  const t = useT();
  const navigate = useNavigate();
  const connectionsState = useConnections();
  const datasetsState = useDatasets();
  const notice = useNotice();
  const [payload, setPayload] = React.useState<StructuredConnectionPayload>(emptyConnection);
  const [activeConnectionId, setActiveConnectionId] = React.useState('');
  const [liveDiscovered, setLiveDiscovered] = React.useState<StructuredDataset[]>([]);
  const [discoveryMode, setDiscoveryMode] = React.useState<'registered' | 'live'>('registered');
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [pendingDeleteConnectionId, setPendingDeleteConnectionId] = React.useState('');
  const activeConnection =
    connectionsState.connections.find((connection) => connection.id === activeConnectionId) ?? null;
  const registeredConnectionDatasets = React.useMemo(
    () =>
      datasetsState.datasets
        .filter((dataset) => dataset.connection_id === activeConnectionId)
        .sort(compareStructuredDatasetsForReview),
    [activeConnectionId, datasetsState.datasets],
  );
  const discoveryDatasets = discoveryMode === 'live' ? liveDiscovered : registeredConnectionDatasets;

  React.useEffect(() => {
    setActiveConnectionId((current) => current || connectionsState.connections[0]?.id || '');
  }, [connectionsState.connections]);

  function resetDiscovery(message?: string) {
    setLiveDiscovered([]);
    setDiscoveryMode('registered');
    setSelected(new Set());
    if (message) notice.setMessage(message);
  }

  function selectConnection(connectionId: string) {
    if (connectionId === activeConnectionId) return;
    setActiveConnectionId(connectionId);
    resetDiscovery(t('structured.database.notice.switched'));
  }

  async function handleTestConnection() {
    await notice.run('testConnection', async () => {
      const result = await testStructuredConnection(payload);
      if (!result.ok) throw new Error(result.message);
      notice.setMessage(t('structured.database.notice.testOk').replace('{count}', String(result.dataset_count)));
    });
  }

  async function handleSaveConnection() {
    await notice.run('saveConnection', async () => {
      const connection = await createStructuredConnection(payload);
      await connectionsState.refresh();
      setActiveConnectionId(connection.id);
      resetDiscovery();
      notice.setMessage(t('structured.database.notice.saved'));
    });
  }

  function handleDeleteConnection(connectionId: string) {
    if (!connectionId) return;
    setPendingDeleteConnectionId(connectionId);
  }

  async function confirmDeleteConnection() {
    const connectionId = pendingDeleteConnectionId;
    setPendingDeleteConnectionId('');
    if (!connectionId) return;
    await notice.run('deleteConnection', async () => {
      await deleteStructuredConnection(connectionId);
      const nextConnections = await connectionsState.refresh();
      await datasetsState.refresh();
      setLiveDiscovered([]);
      setDiscoveryMode('registered');
      setSelected(new Set());
      setActiveConnectionId(nextConnections[0]?.id ?? '');
      notice.setMessage(t('structured.database.notice.removed'));
    });
  }

  async function handleDiscover() {
    if (!activeConnectionId) return;
    await notice.run('discover', async () => {
      const response = await discoverStructuredConnectionDatasets(activeConnectionId);
      setLiveDiscovered(response.datasets);
      setDiscoveryMode('live');
      setSelected(new Set());
      notice.setMessage(t('structured.database.notice.discovered').replace('{count}', String(response.datasets.length)));
    });
  }

  async function handleRegister() {
    if (!activeConnectionId || selected.size === 0) return;
    await notice.run('register', async () => {
      const selections = liveDiscovered
        .filter((dataset) => selected.has(datasetKey(dataset)))
        .map((dataset) => ({
          schema_name: dataset.schema_name,
          table_name: dataset.table_name,
          name: dataset.name,
        }));
      const response = await registerStructuredConnectionDatasets(activeConnectionId, selections);
      notice.setMessage(t('structured.database.notice.registered').replace('{count}', String(response.datasets.length)));
      if (response.datasets[0]) {
        navigate(
          `/structured/datasets?datasetId=${encodeURIComponent(response.datasets[0].id)}&source=database&registered=${response.datasets.length}`,
        );
      }
    });
  }

  return (
    <StructuredFrame
      eyebrow={t('structured.database.eyebrow')}
      title={t('structured.database.title')}
      description={t('structured.database.description')}
      notices={notice}
      actions={
        <Button variant="outline" size="sm" onClick={() => void connectionsState.refresh()}>
          <RefreshCw className="size-4" />
          {t('structured.database.refreshConnections')}
        </Button>
      }
    >
      <section className="grid gap-3 xl:grid-cols-[minmax(23rem,0.78fr)_minmax(0,1.22fr)]">
        <DatabaseConnectionCard
          payload={payload}
          connections={connectionsState.connections}
          activeConnection={activeConnection}
          activeConnectionId={activeConnectionId}
          busy={notice.busy}
          onPayloadChange={setPayload}
          onSelectConnection={selectConnection}
          onTest={() => void handleTestConnection()}
          onSave={() => void handleSaveConnection()}
          onDeleteConnection={handleDeleteConnection}
          onDiscover={() => void handleDiscover()}
        />
        <DiscoveredTablesCard
          datasets={discoveryDatasets}
          selected={selected}
          mode={discoveryMode}
          activeConnectionId={activeConnectionId}
          hasActiveConnection={Boolean(activeConnectionId)}
          busy={notice.busy}
          onToggle={(key) => setSelected(toggleSet(selected, key))}
          onSelectAll={() => setSelected(new Set(discoveryDatasets.map(datasetKey)))}
          onSelectKeys={(keys) => setSelected(new Set([...selected, ...keys]))}
          onClear={() => setSelected(new Set())}
          onRegister={() => void handleRegister()}
        />
      </section>
      <ConfirmDialog
        open={Boolean(pendingDeleteConnectionId)}
        title={t('structured.database.removeConnection')}
        message={t('structured.database.confirmDelete.message')}
        danger
        onConfirm={() => void confirmDeleteConnection()}
        onCancel={() => setPendingDeleteConnectionId('')}
      />
    </StructuredFrame>
  );
}
