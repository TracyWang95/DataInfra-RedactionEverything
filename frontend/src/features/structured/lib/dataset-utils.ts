// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { StructuredConnection, StructuredDataset } from '@/services/structuredApi';
import { t } from '@/i18n';

export type DatasetIdentityContext = {
  connectionName?: string;
  duplicateCount: number;
  duplicateIndex: number;
};

export function structuredJobStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: t('structured.jobStatus.queued'),
    pending: t('structured.jobStatus.pending'),
    processing: t('structured.jobStatus.processing'),
    running: t('structured.jobStatus.running'),
    completed: t('structured.jobStatus.completed'),
    failed: t('structured.jobStatus.failed'),
    cancelled: t('structured.jobStatus.cancelled'),
  };
  return labels[status] ?? status;
}

export function buildDatasetIdentityContexts(
  datasets: StructuredDataset[],
  connections: StructuredConnection[],
): Map<string, DatasetIdentityContext> {
  const connectionNameById = new Map(connections.map((connection) => [connection.id, connection.display_name]));
  const duplicateGroups = new Map<string, StructuredDataset[]>();
  datasets.forEach((dataset) => {
    const key = datasetIdentityName(dataset).trim().toLowerCase();
    duplicateGroups.set(key, [...(duplicateGroups.get(key) ?? []), dataset]);
  });

  const contexts = new Map<string, DatasetIdentityContext>();
  duplicateGroups.forEach((group) => {
    group.forEach((dataset, index) => {
      contexts.set(dataset.id, {
        connectionName: dataset.connection_id ? connectionNameById.get(dataset.connection_id) : undefined,
        duplicateCount: group.length,
        duplicateIndex: index + 1,
      });
    });
  });
  return contexts;
}

export function datasetIdentityName(dataset: StructuredDataset): string {
  return dataset.connection_id ? dataset.table_name || dataset.name : dataset.name;
}

export function datasetIdentityContextText(dataset: StructuredDataset, context?: DatasetIdentityContext): string {
  const parts: string[] = [];
  if (dataset.connection_id) {
    if (context?.connectionName) parts.push(context.connectionName);
    if (dataset.schema_name || dataset.table_name) {
      parts.push([dataset.schema_name, dataset.table_name ?? dataset.name].filter(Boolean).join('.'));
    }
  } else if (context && context.duplicateCount > 1) {
    parts.push(
      t('structured.identity.duplicate')
        .replace('{index}', String(context.duplicateIndex))
        .replace('{count}', String(context.duplicateCount)),
    );
    if (dataset.source_id) {
      parts.push(t('structured.identity.source').replace('{id}', shortEntityId(dataset.source_id)));
    }
  }
  parts.push(
    [
      dataset.source_kind.toUpperCase(),
      datasetTypeLabel(dataset),
      t('structured.common.columnCount').replace('{count}', String(dataset.column_count)),
    ].join(' · '),
  );
  return parts.filter(Boolean).join(' · ');
}

export function shortEntityId(value: string): string {
  return value.replace(/-/g, '').slice(0, 8) || value.slice(0, 8);
}

export function matchesDeliveryDatasetQuery(
  dataset: StructuredDataset,
  query: string,
  connections: StructuredConnection[],
): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  const connectionName = dataset.connection_id
    ? connections.find((connection) => connection.id === dataset.connection_id)?.display_name
    : '';
  return [
    dataset.name,
    dataset.table_name,
    dataset.schema_name,
    dataset.source_kind,
    dataset.dataset_type,
    dataset.shape_kind,
    connectionName,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalized));
}

export function toggleSet(set: Set<string>, key: string): Set<string> {
  const next = new Set(set);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

export function sameSetValues(set: Set<string>, values: string[]): boolean {
  if (set.size !== values.length) return false;
  return values.every((value) => set.has(value));
}

export function datasetKey(dataset: StructuredDataset): string {
  return `${dataset.schema_name ?? ''}.${dataset.table_name ?? dataset.name}`;
}

export function datasetSchemaLabel(dataset: StructuredDataset): string {
  return dataset.schema_name || (dataset.source_kind === 'sqlite' ? 'main' : 'default');
}

function datasetReviewScope(dataset: StructuredDataset): string {
  if (dataset.connection_id) return `connection:${dataset.connection_id}`;
  if (dataset.source_id) return `source:${dataset.source_id}`;
  return `dataset:${dataset.id}`;
}

export function isSameDatasetReviewScope(left: StructuredDataset, right: StructuredDataset): boolean {
  return datasetReviewScope(left) === datasetReviewScope(right);
}

export function compareStructuredDatasetsForReview(left: StructuredDataset, right: StructuredDataset): number {
  const leftSchema = datasetSchemaLabel(left);
  const rightSchema = datasetSchemaLabel(right);
  if (leftSchema !== rightSchema) return leftSchema.localeCompare(rightSchema);
  return (left.table_name ?? left.name).localeCompare(right.table_name ?? right.name);
}

export function buildDatasetScopeSummary(
  selectedDataset: StructuredDataset | null,
  datasets: StructuredDataset[],
  connections: StructuredConnection[],
): { eyebrow: string; title: string; badge: string; detail: string } | null {
  if (!selectedDataset) return null;
  const scopeDatasets = datasets.filter((dataset) => isSameDatasetReviewScope(dataset, selectedDataset));
  if (scopeDatasets.length <= 1 && !selectedDataset.connection_id) return null;

  if (selectedDataset.connection_id) {
    const connection = connections.find((item) => item.id === selectedDataset.connection_id) ?? null;
    const schemaCount = new Set(scopeDatasets.map(datasetSchemaLabel)).size;
    const tableCount = scopeDatasets.filter((dataset) => dataset.dataset_type !== 'db_view').length;
    const viewCount = scopeDatasets.filter((dataset) => dataset.dataset_type === 'db_view').length;
    const title =
      connection?.display_name ||
      t('structured.scope.dbConnectionFallback').replace('{kind}', selectedDataset.source_kind.toUpperCase());
    return {
      eyebrow: t('structured.scope.currentConnection'),
      title,
      badge: t('structured.scope.objectCount').replace('{count}', String(scopeDatasets.length)),
      detail: t('structured.scope.connectionDetail')
        .replace('{schemas}', String(schemaCount))
        .replace('{tables}', String(tableCount))
        .replace('{views}', String(viewCount)),
    };
  }

  if (selectedDataset.source_id && scopeDatasets.length > 1) {
    return {
      eyebrow: t('structured.scope.currentBatch'),
      title: selectedDataset.name,
      badge: t('structured.scope.tableCount').replace('{count}', String(scopeDatasets.length)),
      detail: t('structured.scope.sourceDetail').replace(
        '{count}',
        String(scopeDatasets.reduce((sum, dataset) => sum + dataset.column_count, 0)),
      ),
    };
  }

  return null;
}

export function connectionTargetLabel(connection: StructuredConnection): string {
  const metadata = connection.metadata ?? {};
  const target = metadata.target;
  if (typeof target === 'string' && target.trim()) return target;
  if (connection.engine === 'sqlite') {
    const sqlitePath = metadata.sqlite_path;
    return typeof sqlitePath === 'string' && sqlitePath.trim() ? sqlitePath : t('structured.connection.sqliteFallback');
  }
  const host = typeof metadata.host === 'string' ? metadata.host : '';
  const port = typeof metadata.port === 'number' || typeof metadata.port === 'string' ? String(metadata.port) : '';
  const database = typeof metadata.database === 'string' ? metadata.database : '';
  const endpoint = [host, port ? `:${port}` : '', database ? `/${database}` : ''].join('');
  return endpoint || connection.engine.toUpperCase();
}

export function deliveryUrlForDataset(dataset: StructuredDataset | null): string {
  if (!dataset) return '/structured/delivery';
  const params = new URLSearchParams({ datasetId: dataset.id });
  if (dataset.connection_id) {
    params.set('scope', 'connection');
    params.set('connectionId', dataset.connection_id);
  } else if (dataset.source_id) {
    params.set('scope', 'source');
    params.set('sourceId', dataset.source_id);
  }
  return `/structured/delivery?${params.toString()}`;
}

export function policyReviewUrlForDataset(
  dataset: StructuredDataset,
  options: { returnToDelivery?: boolean } = {},
): string {
  const params = new URLSearchParams({ datasetId: dataset.id });
  if (options.returnToDelivery) params.set('returnTo', 'delivery');
  return `/structured/datasets?${params.toString()}`;
}

export function preservePolicyReturnParams(searchParams: URLSearchParams, datasetId: string): Record<string, string> {
  const params: Record<string, string> = { datasetId };
  if (searchParams.get('returnTo') === 'delivery') params.returnTo = 'delivery';
  return params;
}

export function isDatasetDeliveryReady(dataset: StructuredDataset): boolean {
  return Boolean(dataset.policy_reviewed_at);
}

export function datasetTypeLabel(dataset: StructuredDataset): string {
  if (dataset.dataset_type === 'db_view') return t('structured.datasetType.view');
  if (dataset.dataset_type === 'db_table') return t('structured.datasetType.table');
  if (dataset.dataset_type === 'sheet') return 'Sheet';
  return t('structured.datasetType.file');
}

export function shapeKindLabel(shape: StructuredDataset['shape_kind']): string {
  const labels: Record<StructuredDataset['shape_kind'], string> = {
    flat_table: t('structured.shapeKind.flatTable'),
    relational_multi_table: t('structured.shapeKind.relationalMultiTable'),
    event_log: t('structured.shapeKind.eventLog'),
    wide_feature_table: t('structured.shapeKind.wideFeatureTable'),
    json_kv_table: 'JSON/KV',
  };
  return labels[shape] ?? shape;
}

export function displayValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function isFileDataset(dataset: StructuredDataset): boolean {
  return Boolean(dataset.source_id) || !dataset.connection_id;
}
