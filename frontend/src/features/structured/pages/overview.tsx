// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { Database, FileSpreadsheet, Layers, Server } from 'lucide-react';
import {
  MetricCard,
  StructuredNextActionCard,
  StructuredPathCard,
  StructuredSourceMixCard,
} from '../components/overview-cards';
import { StructuredFrame } from '../components/structured-frame';
import { useT } from '@/i18n';
import { useConnections, useDatasets } from '../hooks/use-structured-data';
import {
  compareStructuredDatasetsForReview,
  isDatasetDeliveryReady,
  isFileDataset,
} from '../lib/dataset-utils';

export function Structured() {
  return <StructuredOverview />;
}

export function StructuredOverview() {
  const t = useT();
  const datasetsState = useDatasets();
  const connectionsState = useConnections();
  const fileCount = datasetsState.datasets.filter(isFileDataset).length;
  const dbCount = datasetsState.datasets.filter((dataset) => Boolean(dataset.connection_id)).length;
  const latestDataset = datasetsState.datasets[0] ?? null;
  const pendingReviewDatasets = [...datasetsState.datasets]
    .filter((dataset) => !isDatasetDeliveryReady(dataset))
    .sort(compareStructuredDatasetsForReview);
  const deliverableDatasets = [...datasetsState.datasets]
    .filter(isDatasetDeliveryReady)
    .sort(compareStructuredDatasetsForReview);
  const nextActionDataset = pendingReviewDatasets[0] ?? latestDataset;
  const nextDeliveryDataset = deliverableDatasets[0] ?? nextActionDataset;
  const pendingReviewCount = pendingReviewDatasets.length;

  return (
    <StructuredFrame
      eyebrow={t('structured.overview.eyebrow')}
      title={t('structured.overview.title')}
      description={t('structured.overview.description')}
    >
      <div className="grid gap-3 lg:grid-cols-4">
        <MetricCard icon={Layers} label={t('structured.overview.metric.datasets')} value={String(datasetsState.datasets.length)} helper={t('structured.overview.metric.datasetsHelper')} />
        <MetricCard icon={FileSpreadsheet} label={t('structured.overview.metric.fileDatasets')} value={String(fileCount)} helper="CSV / Excel / JSONL / SQLite" />
        <MetricCard icon={Database} label={t('structured.overview.metric.dbDatasets')} value={String(dbCount)} helper="MySQL / PostgreSQL / SQLite" />
        <MetricCard icon={Server} label={t('structured.overview.metric.connections')} value={String(connectionsState.connections.length)} helper={t('structured.overview.metric.connectionsHelper')} />
      </div>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.75fr)_minmax(18rem,0.75fr)]">
        <StructuredPathCard
          datasetCount={datasetsState.datasets.length}
          connectionCount={connectionsState.connections.length}
          deliverableCount={deliverableDatasets.length}
          pendingReviewCount={pendingReviewCount}
        />
        <StructuredNextActionCard
          dataset={nextActionDataset}
          deliveryDataset={nextDeliveryDataset}
          datasetCount={datasetsState.datasets.length}
          deliverableCount={deliverableDatasets.length}
          pendingReviewCount={pendingReviewCount}
        />
        <StructuredSourceMixCard fileCount={fileCount} dbCount={dbCount} connectionCount={connectionsState.connections.length} />
      </section>
    </StructuredFrame>
  );
}
