// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CheckCircle2, Database, Eye, Layers, Save, Server, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type {
  StructuredConnection,
  StructuredConnectionPayload,
  StructuredDataset,
} from '@/services/structuredApi';
import { DATABASE_DISCOVERY_PAGE_SIZE } from '../lib/constants';
import {
  connectionTargetLabel,
  datasetKey,
  datasetSchemaLabel,
  datasetTypeLabel,
  shapeKindLabel,
} from '../lib/dataset-utils';
import { EmptyState, Field, ListPager } from './shared';

export function DatabaseConnectionCard({
  payload,
  connections,
  activeConnection,
  activeConnectionId,
  busy,
  onPayloadChange,
  onSelectConnection,
  onTest,
  onSave,
  onDeleteConnection,
  onDiscover,
}: {
  payload: StructuredConnectionPayload;
  connections: StructuredConnection[];
  activeConnection: StructuredConnection | null;
  activeConnectionId: string;
  busy: string;
  onPayloadChange: (payload: StructuredConnectionPayload) => void;
  onSelectConnection: (id: string) => void;
  onTest: () => void;
  onSave: () => void;
  onDeleteConnection: (id: string) => void;
  onDiscover: () => void;
}) {
  const t = useT();
  const isSqlite = payload.engine === 'sqlite';
  const activeTarget = activeConnection ? connectionTargetLabel(activeConnection) : '';
  const activeDatasetCount = activeConnection ? Number(activeConnection.metadata?.dataset_count ?? 0) : 0;

  const [touched, setTouched] = React.useState<Record<string, boolean>>({});
  const [portText, setPortText] = React.useState(payload.port == null ? '' : String(payload.port));
  React.useEffect(() => {
    setPortText(payload.port == null ? '' : String(payload.port));
  }, [payload.port]);
  const markTouched = (field: string) => setTouched((current) => ({ ...current, [field]: true }));

  const hostMissing = !isSqlite && !(payload.host ?? '').trim();
  const databaseMissing = !isSqlite && !(payload.database ?? '').trim();
  const usernameMissing = !isSqlite && !(payload.username ?? '').trim();
  const trimmedPort = portText.trim();
  const portInvalid =
    !isSqlite &&
    trimmedPort !== '' &&
    (!/^\d+$/.test(trimmedPort) || Number(trimmedPort) < 1 || Number(trimmedPort) > 65535);
  const formInvalid = hostMissing || databaseMissing || usernameMissing || portInvalid;

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{t('structured.database.form.title')}</CardTitle>
        <CardDescription>{t('structured.database.form.description')}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (Boolean(busy) || formInvalid) return;
            onSave();
          }}
        >
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label={t('structured.database.form.engine')}>
            <Select
              value={payload.engine}
              onValueChange={(engine) =>
                onPayloadChange({
                  ...payload,
                  engine: engine as StructuredConnectionPayload['engine'],
                  port: engine === 'postgres' ? 5432 : engine === 'mysql' ? 3306 : payload.port,
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sqlite">SQLite</SelectItem>
                <SelectItem value="mysql">MySQL</SelectItem>
                <SelectItem value="postgres">PostgreSQL</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label={t('structured.database.form.name')}>
            <Input
              value={payload.display_name ?? ''}
              onChange={(event) => onPayloadChange({ ...payload, display_name: event.target.value })}
              placeholder={t('structured.database.form.namePlaceholder')}
            />
          </Field>
          {isSqlite ? (
            <Field label={t('structured.database.form.sqlitePath')}>
              <Input
                value={payload.sqlite_path ?? ''}
                onChange={(event) => onPayloadChange({ ...payload, sqlite_path: event.target.value })}
                placeholder="D:\data\source.sqlite"
              />
            </Field>
          ) : (
            <>
              <Field label={t('structured.database.form.host')}>
                <Input
                  value={payload.host ?? ''}
                  className={cn(touched.host && hostMissing && 'border-destructive')}
                  onBlur={() => markTouched('host')}
                  onChange={(event) => onPayloadChange({ ...payload, host: event.target.value })}
                />
                {touched.host && hostMissing ? (
                  <p className="text-xs text-destructive">{t('structured.database.form.required')}</p>
                ) : null}
              </Field>
              <Field label={t('structured.database.form.port')}>
                <Input
                  value={portText}
                  inputMode="numeric"
                  className={cn(portInvalid && 'border-destructive')}
                  onChange={(event) => {
                    const text = event.target.value;
                    setPortText(text);
                    const trimmed = text.trim();
                    if (!trimmed) {
                      onPayloadChange({ ...payload, port: undefined });
                      return;
                    }
                    const parsed = Number(trimmed);
                    if (/^\d+$/.test(trimmed) && parsed >= 1 && parsed <= 65535) {
                      onPayloadChange({ ...payload, port: parsed });
                    }
                  }}
                />
                {portInvalid ? (
                  <p className="text-xs text-destructive">{t('structured.database.form.portRange')}</p>
                ) : null}
              </Field>
              <Field label={t('structured.database.form.database')}>
                <Input
                  value={payload.database ?? ''}
                  className={cn(touched.database && databaseMissing && 'border-destructive')}
                  onBlur={() => markTouched('database')}
                  onChange={(event) => onPayloadChange({ ...payload, database: event.target.value })}
                />
                {touched.database && databaseMissing ? (
                  <p className="text-xs text-destructive">{t('structured.database.form.required')}</p>
                ) : null}
              </Field>
              <Field label={t('structured.database.form.username')}>
                <Input
                  value={payload.username ?? ''}
                  className={cn(touched.username && usernameMissing && 'border-destructive')}
                  onBlur={() => markTouched('username')}
                  onChange={(event) => onPayloadChange({ ...payload, username: event.target.value })}
                />
                {touched.username && usernameMissing ? (
                  <p className="text-xs text-destructive">{t('structured.database.form.required')}</p>
                ) : null}
              </Field>
              <Field label={t('structured.database.form.password')}>
                <Input
                  type="password"
                  value={payload.password ?? ''}
                  onChange={(event) => onPayloadChange({ ...payload, password: event.target.value })}
                />
              </Field>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8"
            onClick={onTest}
            disabled={Boolean(busy) || formInvalid}
          >
            <Server className="size-4" />
            {busy === 'testConnection' ? t('common.testing') : t('structured.database.form.test')}
          </Button>
          <Button type="submit" size="sm" className="h-8" disabled={Boolean(busy) || formInvalid}>
            <Save className="size-4" />
            {busy === 'saveConnection' ? t('common.saving') : t('structured.database.form.save')}
          </Button>
        </div>
        </form>
        <div className="grid gap-1.5">
          <Label>{t('structured.database.savedConnections')}</Label>
          <div className="flex flex-wrap gap-2">
            {connections.map((connection) => (
              <Button
                key={connection.id}
                variant={activeConnectionId === connection.id ? 'default' : 'outline'}
                size="sm"
                className="h-8"
                onClick={() => onSelectConnection(connection.id)}
              >
                {connection.display_name}
              </Button>
            ))}
            {connections.length === 0 ? (
              <span className="text-sm text-muted-foreground">{t('structured.database.noConnections')}</span>
            ) : null}
          </div>
        </div>
        {activeConnection ? (
          <div
            className="grid gap-1.5 rounded-xl border border-[var(--success-border)] bg-[var(--success-surface)] px-3 py-2"
            data-testid="db-active-connection-card"
          >
            <div className="flex items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[var(--success-foreground)]">
                  {t('structured.database.activeTarget')}
                </span>
                <span className="mt-0.5 block truncate text-sm font-semibold" title={activeConnection.display_name}>
                  {activeConnection.display_name}
                </span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={activeTarget}>
                  {activeTarget || activeConnection.engine.toUpperCase()}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <span className="rounded-full bg-background px-2 py-1 text-xs font-semibold">
                  {t('structured.database.objectCount').replace('{count}', String(activeDatasetCount))}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 rounded-lg text-muted-foreground hover:bg-background hover:text-destructive"
                  title={t('structured.database.removeConnection')}
                  aria-label={t('structured.database.removeCurrentConnection')}
                  data-testid="db-delete-active-connection"
                  onClick={() => onDeleteConnection(activeConnection.id)}
                  disabled={Boolean(busy)}
                >
                  <Trash2 className="size-4" />
                </Button>
              </span>
            </div>
            <span className="hidden text-xs leading-5 text-muted-foreground 2xl:block">
              {t('structured.database.credentialHint')}
            </span>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border px-3 py-2.5 text-sm text-muted-foreground">
            {t('structured.database.selectConnectionFirst')}
          </div>
        )}
        <Button
          variant="outline"
          size="sm"
          className="h-8"
          onClick={onDiscover}
          disabled={!activeConnectionId || Boolean(busy)}
        >
          <Eye className="size-4" />
          {busy === 'discover' ? t('structured.database.discovering') : t('structured.database.discover')}
        </Button>
      </CardContent>
    </Card>
  );
}

export function DiscoveredTablesCard({
  datasets,
  selected,
  mode,
  activeConnectionId,
  hasActiveConnection,
  busy,
  onToggle,
  onSelectAll,
  onSelectKeys,
  onClear,
  onRegister,
}: {
  datasets: StructuredDataset[];
  selected: Set<string>;
  mode: 'registered' | 'live';
  activeConnectionId: string;
  hasActiveConnection: boolean;
  busy: string;
  onToggle: (key: string) => void;
  onSelectAll: () => void;
  onSelectKeys: (keys: string[]) => void;
  onClear: () => void;
  onRegister: () => void;
}) {
  const t = useT();
  const isRegisteredMode = mode === 'registered';
  const hasDatasets = datasets.length > 0;
  const [query, setQuery] = React.useState('');
  const [schemaFilter, setSchemaFilter] = React.useState('__all__');
  const [page, setPage] = React.useState(0);
  const discoverySignature = React.useMemo(() => datasets.map(datasetKey).join('|'), [datasets]);
  const sortedDatasets = React.useMemo(
    () =>
      [...datasets].sort((left, right) => {
        const leftSchema = datasetSchemaLabel(left);
        const rightSchema = datasetSchemaLabel(right);
        if (leftSchema !== rightSchema) return leftSchema.localeCompare(rightSchema);
        return (left.table_name ?? left.name).localeCompare(right.table_name ?? right.name);
      }),
    [datasets],
  );
  const normalizedQuery = query.trim().toLowerCase();
  const schemaSummaries = React.useMemo(() => {
    const groups = new Map<string, { label: string; total: number; selected: number; tables: number; views: number }>();
    sortedDatasets.forEach((dataset) => {
      const label = datasetSchemaLabel(dataset);
      const current = groups.get(label) ?? { label, total: 0, selected: 0, tables: 0, views: 0 };
      current.total += 1;
      if (selected.has(datasetKey(dataset))) current.selected += 1;
      if (dataset.dataset_type === 'db_view') current.views += 1;
      else current.tables += 1;
      groups.set(label, current);
    });
    return Array.from(groups.values());
  }, [selected, sortedDatasets]);
  const tableCount = sortedDatasets.filter((dataset) => dataset.dataset_type !== 'db_view').length;
  const viewCount = sortedDatasets.length - tableCount;
  const schemaFilteredDatasets =
    schemaFilter === '__all__'
      ? sortedDatasets
      : sortedDatasets.filter((dataset) => datasetSchemaLabel(dataset) === schemaFilter);
  const filteredDatasets = normalizedQuery
    ? schemaFilteredDatasets.filter((dataset) =>
        [
          dataset.name,
          dataset.schema_name,
          dataset.table_name,
          dataset.dataset_type,
          dataset.source_kind,
          ...dataset.schema.map((column) => column.name),
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(normalizedQuery)),
      )
    : schemaFilteredDatasets;
  const pageSize = DATABASE_DISCOVERY_PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(filteredDatasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = filteredDatasets.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const selectedInFilter = filteredDatasets.filter((dataset) => selected.has(datasetKey(dataset))).length;
  const schemaSummaryMap = React.useMemo(
    () => new Map(schemaSummaries.map((schema) => [schema.label, schema])),
    [schemaSummaries],
  );
  const visibleGroups = React.useMemo(() => {
    const groups = new Map<string, StructuredDataset[]>();
    visibleDatasets.forEach((dataset) => {
      const label = datasetSchemaLabel(dataset);
      groups.set(label, [...(groups.get(label) ?? []), dataset]);
    });
    return Array.from(groups, ([label, items]) => ({
      label,
      items,
      summary: schemaSummaryMap.get(label),
    }));
  }, [schemaSummaryMap, visibleDatasets]);
  const showSchemaGroupHeaders = schemaFilter === '__all__' && schemaSummaries.length > 1;

  React.useEffect(() => {
    setPage(0);
  }, [datasets.length, normalizedQuery, schemaFilter]);

  React.useEffect(() => {
    setQuery('');
    setSchemaFilter('__all__');
    setPage(0);
  }, [discoverySignature, mode]);

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]" data-testid="db-discovery-card">
      <CardHeader className="flex-row items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">
            {isRegisteredMode ? t('structured.database.registeredObjects') : t('structured.database.discoveryResult')}
          </CardTitle>
          <CardDescription>
            {isRegisteredMode
              ? t('structured.database.registeredDescription')
              : t('structured.database.liveDescription')}
          </CardDescription>
        </div>
        <Badge variant="outline" className="shrink-0 rounded-full">
          {isRegisteredMode
            ? t('structured.database.registeredBadge').replace('{count}', String(datasets.length))
            : t('structured.database.objectCount').replace('{count}', String(datasets.length))}
        </Badge>
      </CardHeader>
      <CardContent className="px-4 pb-4 pt-0">
        <div className="mb-2 grid gap-1.5 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5" data-testid="db-discovery-summary">
          <div className="grid gap-2 sm:grid-cols-4">
            <DiscoveryMetric label="Schema" value={schemaSummaries.length} />
            <DiscoveryMetric label={t('structured.database.metric.tables')} value={tableCount} />
            <DiscoveryMetric label={t('structured.database.metric.views')} value={viewCount} />
            <DiscoveryMetric
              label={isRegisteredMode ? t('structured.database.metric.registered') : t('structured.database.metric.selected')}
              value={isRegisteredMode ? datasets.length : selected.size}
              tone="strong"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('structured.database.searchPlaceholder')}
              className="h-8 min-w-44 flex-1"
              data-testid="db-discovery-search"
            />
            {isRegisteredMode ? (
              activeConnectionId && hasDatasets ? (
                <Button asChild size="sm" className="h-8 px-2.5 text-xs">
                  <Link to={`/structured/delivery?scope=connection&connectionId=${encodeURIComponent(activeConnectionId)}`}>
                    {t('structured.database.deliverConnection')}
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
              ) : null
            ) : (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={() => onSelectKeys(filteredDatasets.map(datasetKey))}
                  disabled={!hasDatasets || filteredDatasets.length === 0 || Boolean(busy)}
                >
                  {t('structured.database.selectFiltered').replace('{count}', String(filteredDatasets.length))}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={onSelectAll}
                  disabled={!hasDatasets || Boolean(busy)}
                >
                  {t('structured.database.selectAll')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={onClear}
                  disabled={!hasDatasets || selected.size === 0 || Boolean(busy)}
                >
                  {t('structured.common.clear')}
                </Button>
                <Button
                  onClick={onRegister}
                  disabled={selected.size === 0 || Boolean(busy)}
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                >
                  {busy === 'register'
                    ? t('structured.database.registering')
                    : t('structured.database.registerSelected').replace('{count}', String(selected.size))}
                </Button>
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5" data-testid="db-schema-filter">
            <button
              type="button"
              onClick={() => setSchemaFilter('__all__')}
              aria-pressed={schemaFilter === '__all__'}
              className={cn(
                'rounded-full border px-2.5 py-0.5 text-xs transition hover:bg-background',
                schemaFilter === '__all__' ? 'border-foreground bg-background text-foreground' : 'border-border text-muted-foreground',
              )}
            >
              {t('structured.database.filterAll').replace('{count}', String(datasets.length))}
            </button>
            {schemaSummaries.map((schema) => (
              <button
                key={schema.label}
                type="button"
                onClick={() => setSchemaFilter(schema.label)}
                aria-pressed={schemaFilter === schema.label}
                className={cn(
                  'rounded-full border px-2.5 py-0.5 text-xs transition hover:bg-background',
                  schemaFilter === schema.label
                    ? 'border-foreground bg-background text-foreground'
                    : 'border-border text-muted-foreground',
                )}
                title={t('structured.database.schemaTooltip')
                  .replace('{tables}', String(schema.tables))
                  .replace('{views}', String(schema.views))}
              >
                {schema.label} {schema.total}
                {schema.selected ? (
                  <span className="ml-1 text-[var(--success-foreground)]">
                    {t('structured.common.selectedCount').replace('{count}', String(schema.selected))}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
          {schemaFilter !== '__all__' || normalizedQuery ? (
            <div className="text-xs text-muted-foreground">
              {isRegisteredMode
                ? t('structured.database.filterSummary').replace('{count}', String(filteredDatasets.length))
                : t('structured.database.filterSummarySelected')
                    .replace('{count}', String(filteredDatasets.length))
                    .replace('{selected}', String(selectedInFilter))}
            </div>
          ) : null}
        </div>
        <div className="overflow-hidden rounded-xl border border-border" data-testid="db-discovery-list">
          {datasets.length === 0 ? (
            <EmptyState
              icon={Database}
              text={
                hasActiveConnection
                  ? isRegisteredMode
                    ? t('structured.database.emptyRegistered')
                    : t('structured.database.emptyLive')
                  : t('structured.database.emptyNoConnection')
              }
            />
          ) : filteredDatasets.length === 0 ? (
            <EmptyState icon={Database} text={t('structured.database.emptyFiltered')} />
          ) : (
            <table className="w-full table-fixed text-xs">
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th className="w-10 px-2 py-1.5 text-left">
                    {isRegisteredMode ? t('structured.database.th.status') : t('structured.database.th.select')}
                  </th>
                  <th className="w-[18%] px-2 py-1.5 text-left">Schema</th>
                  <th className="w-[28%] px-2 py-1.5 text-left">{t('structured.database.tablesViews')}</th>
                  <th className="w-[12%] px-2 py-1.5 text-left">{t('structured.database.th.type')}</th>
                  <th className="w-[18%] px-2 py-1.5 text-left">{t('structured.database.th.scale')}</th>
                  <th className="w-[14%] px-2 py-1.5 text-left">{t('structured.database.th.source')}</th>
                  {isRegisteredMode ? (
                    <th className="w-[10%] px-2 py-1.5 text-right">{t('structured.database.th.actions')}</th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {visibleGroups.map((group) => (
                  <React.Fragment key={group.label}>
                    {showSchemaGroupHeaders ? (
                      <tr className="border-t border-border bg-muted/25" data-testid="db-schema-group-header">
                        <td colSpan={isRegisteredMode ? 7 : 6} className="px-2 py-0.5">
                          <span className="flex min-w-0 items-center justify-between gap-3 text-[11px] text-muted-foreground">
                            <span className="flex min-w-0 items-center gap-2 font-medium text-foreground">
                              <Layers className="size-3.5 shrink-0 text-muted-foreground" />
                              <span className="truncate" title={group.label}>
                                {group.label}
                              </span>
                            </span>
                            <span className="shrink-0">
                              {t('structured.database.groupSummary')
                                .replace('{tables}', String(group.summary?.tables ?? 0))
                                .replace('{views}', String(group.summary?.views ?? 0))}
                              {group.summary?.selected
                                ? ` · ${t('structured.common.selectedCount').replace('{count}', String(group.summary.selected))}`
                                : ''}
                            </span>
                          </span>
                        </td>
                      </tr>
                    ) : null}
                    {group.items.map((dataset) => {
                      const key = datasetKey(dataset);
                      const rowsText =
                        dataset.row_count_estimate == null
                          ? t('structured.common.rowsPending')
                          : t('structured.common.rowCount').replace('{count}', String(dataset.row_count_estimate));
                      return (
                        <tr key={key} className="border-t border-border" data-testid="db-discovery-row">
                          <td className="px-2 py-1">
                            {isRegisteredMode ? (
                              <CheckCircle2 className="size-4 text-[var(--success-foreground)]" />
                            ) : (
                              <Checkbox checked={selected.has(key)} onCheckedChange={() => onToggle(key)} />
                            )}
                          </td>
                          <td className="px-2 py-1">
                            <span className="block truncate" title={datasetSchemaLabel(dataset)}>
                              {datasetSchemaLabel(dataset)}
                            </span>
                          </td>
                          <td className="px-2 py-1">
                            <span className="block truncate font-medium" title={dataset.name}>
                              {dataset.table_name ?? dataset.name}
                            </span>
                            <span className="block truncate text-[10px] text-muted-foreground" title={shapeKindLabel(dataset.shape_kind)}>
                              {shapeKindLabel(dataset.shape_kind)}
                            </span>
                          </td>
                          <td className="px-2 py-1">
                            <Badge variant="outline">
                              {datasetTypeLabel(dataset)}
                            </Badge>
                          </td>
                          <td className="px-2 py-1 text-muted-foreground">
                            <span className="block truncate">
                              {t('structured.common.columnCount').replace('{count}', String(dataset.column_count))}
                            </span>
                            <span className="block truncate text-[10px]">{rowsText}</span>
                          </td>
                          <td className="px-2 py-1">
                            <Badge variant="outline">
                              {dataset.source_kind.toUpperCase()}
                            </Badge>
                          </td>
                          {isRegisteredMode ? (
                            <td className="px-2 py-1 text-right">
                              <Button asChild variant="outline" size="sm" className="h-8 px-2">
                                <Link to={`/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}`}>
                                  {t('structured.common.goToPolicy')}
                                </Link>
                              </Button>
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {filteredDatasets.length > pageSize ? (
          <div className="mt-1.5">
            <ListPager
              label={t('structured.database.tablesViews')}
              page={safePage}
              pageCount={pageCount}
              total={filteredDatasets.length}
              pageSize={pageSize}
              visibleCount={visibleDatasets.length}
              onPageChange={setPage}
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function DiscoveryMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'strong';
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-background px-2.5 py-1.5 text-sm">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn('font-semibold', tone === 'strong' && 'text-[var(--success-foreground)]')}>{value}</span>
    </div>
  );
}
