// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { ArrowLeft, ArrowRight, Search, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
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
  StructuredColumnPolicy,
  StructuredColumnProfile,
  StructuredDataset,
  StructuredPolicyAction,
  StructuredProfile,
} from '@/services/structuredApi';
import { getActionOptions, EMPTY_STRUCTURED_COLUMNS, FIELD_POLICY_PAGE_SIZE } from '../lib/constants';
import { displayValue } from '../lib/dataset-utils';
import {
  defaultEnabledPolicyAction,
  isPolicyAdjusted,
  matchesPolicyColumnQuery,
  orderColumnsForPolicyReview,
  profileToPolicy,
  updatePolicy,
} from '../lib/policy-utils';
import { EmptyState } from './shared';

export function ProfilePolicyCard({
  dataset,
  profile,
  policy,
  fieldPage,
  currentPageReviewed,
  reviewedPageCount,
  pageCount,
  onFieldPageChange,
  onPolicyChange,
}: {
  dataset: StructuredDataset | null;
  profile: StructuredProfile | null;
  policy: StructuredColumnPolicy[];
  fieldPage: number;
  currentPageReviewed: boolean;
  reviewedPageCount: number;
  pageCount: number;
  onFieldPageChange: (page: number) => void;
  onPolicyChange: (policy: StructuredColumnPolicy[]) => void;
}) {
  const t = useT();
  const actionOptions = getActionOptions();
  const [fieldQuery, setFieldQuery] = React.useState('');
  const profileColumns = profile?.columns ?? EMPTY_STRUCTURED_COLUMNS;
  const policyByColumn = new Map(policy.map((item) => [item.column, item]));
  const reviewColumns = React.useMemo(() => orderColumnsForPolicyReview(profileColumns), [profileColumns]);
  const normalizedFieldQuery = fieldQuery.trim().toLowerCase();
  const matchedColumnIndexes = React.useMemo(
    () =>
      normalizedFieldQuery
        ? reviewColumns
            .map((column, index) => ({ column, index }))
            .filter(({ column }) => matchesPolicyColumnQuery(column, normalizedFieldQuery))
            .map(({ index }) => index)
        : [],
    [normalizedFieldQuery, reviewColumns],
  );
  const pageSize = FIELD_POLICY_PAGE_SIZE;
  const safePage = Math.min(fieldPage, pageCount - 1);
  const visibleColumns = reviewColumns.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const visibleMatchedCount = normalizedFieldQuery
    ? visibleColumns.filter((column) => matchesPolicyColumnQuery(column, normalizedFieldQuery)).length
    : 0;
  const visiblePolicyRows = visibleColumns.map((column) => ({
    column,
    current: policyByColumn.get(column.name) ?? profileToPolicy(column),
  }));
  const visibleRedactedCount = visiblePolicyRows.filter(
    ({ current }) => current.enabled && current.action !== 'keep',
  ).length;
  const visibleHighRiskRows = visiblePolicyRows.filter(({ column }) =>
    ['high', 'critical'].includes(column.risk_level),
  );
  const visibleHighRiskTotal = visibleHighRiskRows.length;
  const visibleHighRiskRedacted = visibleHighRiskRows.filter(
    ({ current }) => current.enabled && current.action !== 'keep',
  ).length;
  const visibleRangeStart = profileColumns.length === 0 ? 0 : safePage * pageSize + 1;
  const visibleRangeEnd = Math.min(profileColumns.length, safePage * pageSize + visibleColumns.length);
  const matchIndexSignature = matchedColumnIndexes.join('|');
  const autoJumpSignature = `${profile?.dataset_id ?? ''}:${normalizedFieldQuery}:${matchIndexSignature}`;
  const lastAutoJumpSignatureRef = React.useRef('');

  React.useEffect(() => {
    setFieldQuery('');
    lastAutoJumpSignatureRef.current = '';
  }, [profile?.dataset_id]);

  React.useEffect(() => {
    if (!normalizedFieldQuery || matchedColumnIndexes.length === 0) {
      lastAutoJumpSignatureRef.current = '';
      return;
    }
    if (lastAutoJumpSignatureRef.current === autoJumpSignature) return;
    lastAutoJumpSignatureRef.current = autoJumpSignature;
    const targetPage = Math.floor(matchedColumnIndexes[0] / pageSize);
    if (targetPage !== safePage) onFieldPageChange(targetPage);
  }, [autoJumpSignature, matchedColumnIndexes, normalizedFieldQuery, onFieldPageChange, pageSize, safePage]);

  function goToFieldMatch(direction: -1 | 1) {
    if (matchedColumnIndexes.length === 0) return;
    const pageStart = safePage * pageSize;
    const pageEnd = pageStart + pageSize;
    const currentMatchIndex = matchedColumnIndexes.findIndex((index) => index >= pageStart && index < pageEnd);
    const baseIndex = currentMatchIndex >= 0 ? currentMatchIndex : direction > 0 ? -1 : 0;
    const nextMatchIndex = (baseIndex + direction + matchedColumnIndexes.length) % matchedColumnIndexes.length;
    onFieldPageChange(Math.floor(matchedColumnIndexes[nextMatchIndex] / pageSize));
  }

  return (
    <Card className="page-surface flex min-h-0 flex-col border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="flex-row items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <CardTitle className="truncate text-sm">{dataset ? dataset.name : t('structured.policy.title')}</CardTitle>
          {profile?.semantic_inference ? <SemanticInferenceSummary info={profile.semantic_inference} /> : null}
        </div>
        {profileColumns.length > 0 ? (
          <div className="flex min-w-[18rem] max-w-[28rem] flex-1 items-center justify-end gap-1.5">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={fieldQuery}
                onChange={(event) => setFieldQuery(event.target.value)}
                placeholder={t('structured.policy.searchPlaceholder')}
                className="h-8 pl-7 pr-2 text-xs"
                data-testid="policy-field-search"
              />
            </div>
            <span
              className="min-w-16 shrink-0 text-right text-[11px] text-muted-foreground"
              data-testid="policy-field-search-count"
            >
              {normalizedFieldQuery
                ? matchedColumnIndexes.length > 0
                  ? t('structured.policy.matched').replace('{count}', String(matchedColumnIndexes.length))
                  : t('structured.policy.noMatch')
                : t('structured.policy.locate')}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="size-8 shrink-0 p-0"
              disabled={matchedColumnIndexes.length === 0}
              onClick={() => goToFieldMatch(-1)}
              aria-label={t('structured.policy.prevMatch')}
            >
              <ArrowLeft className="size-3.5" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="size-8 shrink-0 p-0"
              disabled={matchedColumnIndexes.length === 0}
              onClick={() => goToFieldMatch(1)}
              aria-label={t('structured.policy.nextMatch')}
            >
              <ArrowRight className="size-3.5" />
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)_auto] gap-1 px-4 pb-3 pt-0">
        {profileColumns.length > 0 ? <PolicySummaryStrip columns={profileColumns} policy={policy} /> : null}
        <div className="min-h-0 overflow-hidden rounded-xl border border-border" data-testid="policy-table-frame">
          {profileColumns.length === 0 ? (
            <EmptyState
              icon={ShieldCheck}
              text={dataset ? t('structured.policy.emptyWithDataset') : t('structured.policy.emptyNoDataset')}
            />
          ) : (
            <table className="w-full table-fixed text-xs" data-testid="policy-table">
              <thead className="sticky top-0 bg-muted text-xs text-muted-foreground">
                <tr>
                  <th className="w-[31%] px-2 py-1 text-left">{t('structured.policy.th.field')}</th>
                  <th className="w-[15%] px-2 py-1 text-left">{t('structured.policy.th.entity')}</th>
                  <th className="w-[12%] px-2 py-1 text-left">{t('structured.policy.th.risk')}</th>
                  <th className="w-[12%] px-2 py-1 text-left">{t('structured.policy.th.confidence')}</th>
                  <th className="w-[23%] px-2 py-1 text-left">{t('structured.policy.th.action')}</th>
                  <th className="w-[7%] px-2 py-1 text-left">{t('structured.policy.th.enabled')}</th>
                </tr>
              </thead>
              <tbody>
                {visiblePolicyRows.map(({ column, current }) => {
                  const adjusted = isPolicyAdjusted(column, current);
                  const matchesSearch = Boolean(
                    normalizedFieldQuery && matchesPolicyColumnQuery(column, normalizedFieldQuery),
                  );
                  return (
                    <tr
                      key={column.name}
                      className={cn(
                        'border-t border-border',
                        matchesSearch && 'bg-[var(--success-surface)]',
                        adjusted && 'bg-[var(--warning-surface)]',
                      )}
                      data-testid="policy-row"
                      data-policy-column={column.name}
                      data-policy-adjusted={adjusted ? 'true' : 'false'}
                      data-policy-search-match={matchesSearch ? 'true' : 'false'}
                    >
                      <td className="max-w-56 px-2 py-1">
                        <span className="flex min-w-0 items-center gap-1.5 leading-tight" title={column.name}>
                          <span className="min-w-0 truncate font-medium">{column.name}</span>
                          {adjusted ? (
                            <span className="shrink-0 rounded-full bg-background px-1.5 py-0.5 text-[9.5px] font-medium text-[var(--warning-foreground)]">
                              {t('structured.policy.adjusted')}
                            </span>
                          ) : null}
                        </span>
                        <span
                          className="block truncate text-[10px] leading-[1.05] text-muted-foreground"
                          title={column.sample_values.map(displayValue).join(' / ')}
                        >
                          {column.sample_values.map(displayValue).join(' / ')}
                        </span>
                      </td>
                      <td className="px-2 py-1">{column.entity_type}</td>
                      <td className="px-2 py-1">
                        <RiskBadge risk={column.risk_level} />
                      </td>
                      <td className="px-2 py-1">{Math.round(column.confidence * 100)}%</td>
                      <td className="px-2 py-1">
                        <span className="flex min-w-0 items-center gap-1.5">
                          <Select
                            value={current.action}
                            onValueChange={(action) => {
                              const nextAction = action as StructuredPolicyAction;
                              onPolicyChange(
                                updatePolicy(policy, column, {
                                  action: nextAction,
                                  enabled: nextAction !== 'keep',
                                }),
                              );
                            }}
                          >
                            <SelectTrigger className="h-6 min-w-[4.75rem] flex-1 justify-between px-2 text-[11px]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {actionOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {adjusted ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-6 shrink-0 px-2 text-[11px]"
                              data-testid="policy-reset-recommendation"
                              onClick={() => onPolicyChange(updatePolicy(policy, column, profileToPolicy(column)))}
                            >
                              {t('structured.policy.restore')}
                            </Button>
                          ) : null}
                        </span>
                      </td>
                      <td className="px-2 py-1">
                        <Checkbox
                          checked={current.enabled && current.action !== 'keep'}
                          onCheckedChange={(checked) => {
                            const enabled = checked === true;
                            onPolicyChange(
                              updatePolicy(policy, column, {
                                enabled,
                                action: enabled ? defaultEnabledPolicyAction(column, current) : 'keep',
                              }),
                            );
                          }}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex min-h-8 items-center justify-between gap-3 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5 text-xs text-muted-foreground">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="min-w-0 truncate">
              {profileColumns.length === 0
                ? t('structured.policy.footer.empty')
                : t('structured.policy.footer.range')
                    .replace('{start}', String(visibleRangeStart))
                    .replace('{end}', String(visibleRangeEnd))
                    .replace('{total}', String(profileColumns.length))
                    .replace('{page}', String(safePage + 1))
                    .replace('{pageCount}', String(pageCount))
                    .replace('{reviewed}', String(reviewedPageCount))
                    .replace('{pages}', String(pageCount))}
            </span>
            {profileColumns.length > 0 ? (
              <span className="hidden shrink-0 text-[10px] text-muted-foreground lg:inline">
                {t('structured.policy.footer.riskSort')}
              </span>
            ) : null}
            {profileColumns.length > 0 ? (
              <span
                className="shrink-0 rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-muted-foreground"
                data-testid="policy-page-summary"
              >
                {t('structured.policy.footer.pageStats')
                  .replace('{enabled}', String(visibleRedactedCount))
                  .replace('{visible}', String(visibleColumns.length))
                  .replace(
                    '{highRisk}',
                    visibleHighRiskTotal > 0
                      ? `${visibleHighRiskRedacted}/${visibleHighRiskTotal}`
                      : t('structured.common.none'),
                  )}
                {normalizedFieldQuery
                  ? ` · ${t('structured.policy.footer.matchedRatio')
                      .replace('{matched}', String(visibleMatchedCount))
                      .replace('{total}', String(matchedColumnIndexes.length))}`
                  : ''}
              </span>
            ) : null}
            {profileColumns.length > 0 ? (
              <Badge
                variant="outline"
                className={cn(
                  'shrink-0 rounded-full',
                  currentPageReviewed
                    ? 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]'
                    : 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                )}
              >
                {currentPageReviewed ? t('structured.policy.pageConfirmed') : t('structured.policy.pagePending')}
              </Badge>
            ) : null}
          </span>
          {profileColumns.length > pageSize ? (
            <span className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={safePage <= 0}
                onClick={() => onFieldPageChange(safePage - 1)}
              >
                {t('structured.common.prevGroup')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={safePage >= pageCount - 1}
                onClick={() => onFieldPageChange(safePage + 1)}
              >
                {t('structured.common.nextGroup')}
              </Button>
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function PolicySummaryStrip({
  columns,
  policy,
}: {
  columns: StructuredColumnProfile[];
  policy: StructuredColumnPolicy[];
}) {
  const t = useT();
  const policyByColumn = new Map(policy.map((item) => [item.column, item]));
  const policyRows = columns.map((column) => ({
    column,
    current: policyByColumn.get(column.name) ?? profileToPolicy(column),
  }));
  const redactedRows = policyRows.filter(({ current }) => current.enabled && current.action !== 'keep');
  const highRiskRows = policyRows.filter(({ column }) => ['high', 'critical'].includes(column.risk_level));
  const redacted = redactedRows.length;
  const retained = columns.length - redacted;
  const highRiskTotal = highRiskRows.length;
  const highRiskRedacted = highRiskRows.filter(({ current }) => current.enabled && current.action !== 'keep').length;
  const semanticRows = policyRows.filter(({ column }) =>
    (column.reasons ?? []).some((reason) => String(reason).includes('semantic')),
  );
  const semanticRedacted = redactedRows.filter(({ column }) =>
    (column.reasons ?? []).some((reason) => String(reason).includes('semantic')),
  ).length;
  const semanticTotal = semanticRows.length;
  const adjustedCount = policyRows.filter(({ column, current }) => isPolicyAdjusted(column, current)).length;
  const total = Math.max(columns.length, 1);
  const redactedPct = (redacted / total) * 100;
  const retainedPct = (retained / total) * 100;
  const riskPct = highRiskTotal > 0 ? (highRiskRedacted / highRiskTotal) * 100 : 0;
  const highRiskRetained = Math.max(highRiskTotal - highRiskRedacted, 0);
  const formatPct = (value: number) => {
    const rounded = Math.round(value * 10) / 10;
    return Number.isInteger(rounded) ? `${rounded}%` : `${rounded.toFixed(1)}%`;
  };
  const highRiskCoverage = highRiskTotal > 0 ? `${highRiskRedacted}/${highRiskTotal}` : t('structured.common.none');
  const highRiskTone =
    highRiskTotal === 0
      ? 'bg-muted text-foreground'
      : highRiskRetained === 0
        ? 'bg-[var(--success-surface)] text-[var(--success-foreground)]'
        : 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]';

  const items = [
    { label: t('structured.policySummary.totalFields'), value: columns.length, tone: 'bg-muted text-foreground' },
    { label: t('structured.policySummary.redactedEnabled'), value: redacted, tone: 'bg-foreground text-background' },
    { label: t('structured.policySummary.retained'), value: retained, tone: 'bg-muted text-foreground' },
    { label: t('structured.policySummary.highRiskHandled'), value: highRiskCoverage, tone: highRiskTone },
    {
      label: t('structured.policySummary.semanticHits'),
      value: semanticTotal,
      tone: 'bg-[var(--success-surface)] text-[var(--success-foreground)]',
    },
    { label: t('structured.policySummary.semanticRedacted'), value: semanticRedacted, tone: 'bg-muted text-foreground' },
    {
      label: t('structured.policySummary.manualAdjusted'),
      value: adjustedCount,
      tone: adjustedCount > 0 ? 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]' : 'bg-muted text-foreground',
    },
  ];

  return (
    <div className="grid gap-1 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5" data-testid="policy-summary">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        {items.map((item) => (
          <span key={item.label} className="inline-flex items-center gap-1 text-[10.5px] text-muted-foreground">
            <span>{item.label}</span>
            <span className={cn('rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold', item.tone)}>
              {item.value}
            </span>
          </span>
        ))}
      </div>
      <div
        className="flex h-2 overflow-hidden rounded-full bg-muted"
        aria-label={t('structured.policySummary.distributionAria')
          .replace('{redacted}', String(redacted))
          .replace('{retained}', String(retained))}
        data-testid="policy-distribution"
      >
        <span className="bg-foreground" style={{ width: `${redactedPct}%` }} />
        <span className="bg-muted-foreground/25" style={{ width: `${retainedPct}%` }} />
      </div>
      <div className="hidden flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground 2xl:flex">
        <span>
          {t('structured.policySummary.formula')
            .replace('{total}', String(columns.length))
            .replace('{redacted}', String(redacted))
            .replace('{retained}', String(retained))}
        </span>
        <span>
          {t('structured.policySummary.redactedRatio')
            .replace('{redacted}', String(redacted))
            .replace('{total}', String(columns.length))
            .replace('{pct}', formatPct(redactedPct))}
        </span>
        <span>
          {t('structured.policySummary.retainedRatio')
            .replace('{retained}', String(retained))
            .replace('{total}', String(columns.length))
            .replace('{pct}', formatPct(retainedPct))}
        </span>
        <span>
          {t('structured.policySummary.highRiskCoverage').replace('{coverage}', highRiskCoverage)}
          {highRiskTotal > 0 ? t('structured.policySummary.highRiskPct').replace('{pct}', formatPct(riskPct)) : ''}
          {highRiskRetained > 0
            ? t('structured.policySummary.highRiskRetained').replace('{count}', String(highRiskRetained))
            : ''}
        </span>
        <span>
          {t('structured.policySummary.semanticSummary')
            .replace('{total}', String(semanticTotal))
            .replace('{redacted}', String(semanticRedacted))}
        </span>
        <span>{t('structured.policySummary.adjustedSummary').replace('{count}', String(adjustedCount))}</span>
      </div>
    </div>
  );
}

function RiskBadge({ risk }: { risk: StructuredColumnProfile['risk_level'] }) {
  const t = useT();
  const meta = {
    low: { label: t('structured.risk.low'), tone: 'border-border text-muted-foreground' },
    medium: { label: t('structured.risk.medium'), tone: 'border-[var(--warning-foreground)] text-[var(--warning-foreground)]' },
    high: { label: t('structured.risk.high'), tone: 'border-[var(--error-foreground)] text-[var(--error-foreground)]' },
    critical: {
      label: t('structured.risk.critical'),
      tone: 'border-[var(--error-foreground)] bg-[var(--error-surface)] text-[var(--error-foreground)]',
    },
  }[risk];
  return (
    <Badge variant="outline" className={cn(meta.tone)} title={risk}>
      {meta.label}
    </Badge>
  );
}

function SemanticInferenceSummary({
  info,
}: {
  info: NonNullable<StructuredProfile['semantic_inference']>;
}) {
  const t = useT();
  const status = info.status ?? 'unknown';
  const matched = typeof info.matched_columns === 'number' ? info.matched_columns : 0;
  const duration = typeof info.duration_ms === 'number' ? info.duration_ms : 0;
  const meta = semanticInferenceStatusMeta(status, matched, t);
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
      <Badge variant={meta.variant}>
        {meta.label}
      </Badge>
      <span>{meta.detail}</span>
      {meta.showMatched ? (
        <span>{t('structured.semantic.matchedFields').replace('{count}', String(matched))}</span>
      ) : null}
      {duration > 0 ? <span>{duration} ms</span> : null}
    </div>
  );
}

function semanticInferenceStatusMeta(
  status: string,
  matched: number,
  t: (key: string) => string,
): {
  label: string;
  detail: string;
  showMatched: boolean;
  variant: React.ComponentProps<typeof Badge>['variant'];
} {
  if (status === 'used') {
    return {
      label: t('structured.semantic.used.label'),
      detail: t('structured.semantic.used.detail'),
      showMatched: true,
      variant: 'default',
    };
  }
  if (status === 'used_no_matches') {
    return {
      label: t('structured.semantic.usedNoMatches.label'),
      detail: matched > 0 ? t('structured.semantic.usedNoMatches.detailMerged') : t('structured.semantic.usedNoMatches.detailLocal'),
      showMatched: true,
      variant: 'outline',
    };
  }
  if (status === 'skipped_no_candidates') {
    return {
      label: t('structured.semantic.skippedNoCandidates.label'),
      detail: t('structured.semantic.skippedNoCandidates.detail'),
      showMatched: false,
      variant: 'outline',
    };
  }
  if (status === 'skipped_empty') {
    return {
      label: t('structured.semantic.skippedEmpty.label'),
      detail: t('structured.semantic.skippedEmpty.detail'),
      showMatched: false,
      variant: 'outline',
    };
  }
  if (status === 'unavailable') {
    return {
      label: t('structured.semantic.unavailable.label'),
      detail: t('structured.semantic.unavailable.detail'),
      showMatched: false,
      variant: 'outline',
    };
  }
  if (status === 'failed') {
    return {
      label: t('structured.semantic.failed.label'),
      detail: t('structured.semantic.failed.detail'),
      showMatched: false,
      variant: 'outline',
    };
  }
  return {
    label: t('structured.semantic.unknown.label'),
    detail: t('structured.semantic.unknown.detail'),
    showMatched: false,
    variant: 'outline',
  };
}
