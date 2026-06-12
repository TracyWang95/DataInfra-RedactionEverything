// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  PackageCheck,
  Save,
  ShieldCheck,
  TableProperties,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { StructuredDataset, StructuredPreview, StructuredProfile } from '@/services/structuredApi';
import { deliveryUrlForDataset } from '../lib/dataset-utils';
import type { FieldReviewProgress } from '../lib/policy-utils';

export function PolicyCanvas({
  dataset,
  profile,
  fieldReview,
  policyConfirmed,
  policySaved,
  preview,
  nextDatasetToReview,
  remainingDatasetReviewCount,
  busy,
  onConfirmChange,
  onAdvanceFieldReview,
  onProfile,
  onSave,
  onPreview,
  onNextDataset,
  returnDeliveryUrl,
}: {
  dataset: StructuredDataset | null;
  profile: StructuredProfile | null;
  fieldReview: FieldReviewProgress;
  policyConfirmed: boolean;
  policySaved: boolean;
  preview: StructuredPreview | null;
  nextDatasetToReview: StructuredDataset | null;
  remainingDatasetReviewCount: number;
  busy: string;
  onConfirmChange: (checked: boolean) => void;
  onAdvanceFieldReview: () => void;
  onProfile: () => void;
  onSave: () => void;
  onPreview: () => void;
  onNextDataset: () => void;
  returnDeliveryUrl: string;
}) {
  const t = useT();
  const canConfirmPolicy = Boolean(profile && fieldReview.allReviewed);
  const nextReviewLabel = dataset?.connection_id ? t('structured.canvas.nextTable') : t('structured.canvas.nextDataset');
  const reviewScopeNoun = dataset?.connection_id
    ? t('structured.canvas.scopeConnectionNoun')
    : t('structured.canvas.scopeSourceNoun');
  const nodes = [
    {
      key: 'dataset',
      title: t('structured.canvas.step.dataset'),
      desc: dataset ? dataset.name : t('structured.canvas.step.datasetTodo'),
      done: Boolean(dataset),
      active: !dataset,
    },
    {
      key: 'profile',
      title: t('structured.canvas.step.profile'),
      desc: profile
        ? t('structured.canvas.step.profileDone').replace('{count}', String(profile.columns.length))
        : t('structured.canvas.step.profileTodo'),
      done: Boolean(profile),
      active: Boolean(dataset && !profile),
    },
    {
      key: 'confirm',
      title: t('structured.canvas.step.confirm'),
      desc: policyConfirmed
        ? t('structured.canvas.step.confirmDone')
        : profile && !fieldReview.allReviewed
          ? t('structured.canvas.confirmedPages')
              .replace('{reviewed}', String(fieldReview.reviewedPages))
              .replace('{total}', String(fieldReview.totalPages))
          : t('structured.canvas.step.confirmTodo'),
      done: policyConfirmed,
      active: Boolean(profile && !policyConfirmed),
      confirmable: true,
    },
    {
      key: 'save',
      title: t('structured.canvas.step.save'),
      desc: policySaved ? t('structured.canvas.step.saveDone') : t('structured.canvas.step.saveTodo'),
      done: policySaved,
      active: Boolean(policyConfirmed && !policySaved),
    },
    {
      key: 'preview',
      title: t('structured.canvas.step.preview'),
      desc: preview
        ? t('structured.canvas.step.previewDone')
        : returnDeliveryUrl && policySaved
          ? t('structured.canvas.step.previewReturn')
          : t('structured.canvas.step.previewTodo'),
      done: Boolean(preview || (returnDeliveryUrl && policySaved)),
      active: Boolean(policySaved && !preview && !returnDeliveryUrl),
    },
  ];
  const currentAction = !dataset
    ? {
        label: t('structured.canvas.action.selectDataset'),
        detail: t('structured.canvas.action.selectDatasetDetail'),
        Icon: TableProperties,
        disabled: true,
      }
    : !profile
      ? {
          label: t('structured.canvas.action.generateProfile'),
          detail: t('structured.canvas.action.generateProfileDetail'),
          Icon: ShieldCheck,
          onClick: onProfile,
        }
      : !fieldReview.allReviewed
        ? {
            label: fieldReview.currentPageReviewed
              ? t('structured.canvas.action.continueReview')
              : t('structured.canvas.action.confirmPage')
                  .replace('{page}', String(fieldReview.currentPage))
                  .replace('{total}', String(fieldReview.totalPages)),
            detail: fieldReview.currentPageReviewed
              ? t('structured.canvas.action.continueReviewDetail')
                  .replace('{reviewed}', String(fieldReview.reviewedPages))
                  .replace('{total}', String(fieldReview.totalPages))
              : t('structured.canvas.action.confirmPageDetail'),
            Icon: fieldReview.currentPageReviewed ? Eye : CheckCircle2,
            onClick: onAdvanceFieldReview,
          }
      : !policyConfirmed
        ? {
            label: t('structured.canvas.action.confirmPolicy'),
            detail: t('structured.canvas.action.confirmPolicyDetail'),
            Icon: CheckCircle2,
            onClick: () => onConfirmChange(true),
          }
        : !policySaved
          ? {
              label: t('structured.canvas.action.saveAndPreview'),
              detail: t('structured.canvas.action.saveAndPreviewDetail'),
              Icon: Save,
              onClick: onSave,
            }
          : returnDeliveryUrl
            ? {
                label: t('structured.canvas.action.returnDelivery'),
                detail: t('structured.canvas.action.returnDeliveryDetail'),
                Icon: PackageCheck,
                to: returnDeliveryUrl,
              }
          : !preview
            ? {
                label: t('structured.canvas.action.generatePreview'),
                detail: t('structured.canvas.action.generatePreviewDetail'),
                Icon: Eye,
                onClick: onPreview,
              }
            : {
                ...(nextDatasetToReview
                  ? {
                      label: nextReviewLabel,
                      detail: t('structured.canvas.action.nextDatasetDetail')
                        .replace('{count}', String(remainingDatasetReviewCount))
                        .replace('{scope}', reviewScopeNoun),
                      Icon: ArrowRight,
                      onClick: onNextDataset,
                    }
                  : {
                      label: t('structured.canvas.action.enterDelivery'),
                      detail: t('structured.canvas.action.enterDeliveryDetail'),
                      Icon: PackageCheck,
                      to: deliveryUrlForDataset(dataset),
                    }),
              };
  const CurrentIcon = currentAction.Icon;
  const currentActionTo = 'to' in currentAction ? currentAction.to : null;

  return (
    <Card
      className="page-surface border-border/70 shadow-[var(--shadow-control)]"
      data-testid="structured-policy-canvas"
    >
      <CardContent className="grid gap-1.5 p-1.5 xl:grid-cols-[17rem_minmax(0,1fr)_15rem]">
        <div className="grid min-h-16 content-center rounded-xl border border-border bg-muted/25 px-3 py-1.5">
          <span className="text-xs font-semibold text-muted-foreground">{t('structured.canvas.currentDataset')}</span>
          <span className="truncate text-sm font-semibold" title={dataset?.name}>
            {dataset?.name ?? t('structured.canvas.noSelection')}
          </span>
          <span className="truncate text-xs text-muted-foreground">
            {dataset
              ? t('structured.common.datasetMeta')
                  .replace('{kind}', dataset.dataset_type.toUpperCase())
                  .replace('{columns}', String(dataset.column_count))
                  .replace('{rows}', String(dataset.row_count_estimate ?? 0))
              : t('structured.canvas.selectFromLeft')}
          </span>
        </div>
        <div className="relative rounded-xl border border-border bg-background px-3 py-1.5">
          <div className="pointer-events-none absolute left-12 right-12 top-6 hidden h-px bg-border lg:block" />
          <div className="relative z-10 grid h-full gap-1 lg:grid-cols-5">
            {nodes.map((node, index) => (
              <div
                key={node.key}
                data-testid={`policy-step-${node.key}`}
                className={cn(
                  'grid min-h-14 grid-rows-[auto_auto_auto] justify-items-center gap-0.5 rounded-lg px-2 py-0.5 text-center transition',
                  node.active && 'bg-muted/40',
                )}
              >
                <span
                  className={cn(
                    'grid size-7 place-items-center rounded-full border bg-card shadow-[var(--shadow-sm)]',
                    node.done
                      ? 'border-[var(--success-border)] bg-[var(--success-surface)]'
                      : node.active
                        ? 'border-foreground bg-background'
                        : 'border-border bg-card',
                  )}
                >
                  {node.confirmable ? (
                    <Checkbox
                      data-testid="policy-confirm-checkbox"
                      checked={policyConfirmed}
                      disabled={!canConfirmPolicy || Boolean(busy)}
                      onCheckedChange={(checked) => onConfirmChange(checked === true)}
                    />
                  ) : node.done ? (
                    <CheckCircle2 className="size-3.5 text-[var(--success-foreground)]" />
                  ) : (
                    <span className="text-xs font-semibold text-muted-foreground">{index + 1}</span>
                  )}
                </span>
                <span className="block max-w-full truncate text-[13px] font-semibold">{node.title}</span>
                <span className="block max-w-full truncate text-[11px] text-muted-foreground">{node.desc}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="grid min-h-16 grid-rows-[auto_1fr_auto] rounded-xl border border-foreground bg-foreground p-2 text-background">
          <span className="flex items-center gap-2 text-xs font-semibold text-background/70">
            <CurrentIcon className="size-4" />
            {t('structured.canvas.currentAction')}
          </span>
          <span className="min-w-0 self-center">
            <span className="block truncate text-sm font-semibold">{currentAction.label}</span>
            <span className="block truncate text-xs text-background/65">{currentAction.detail}</span>
          </span>
          {currentActionTo ? (
            <Button asChild size="sm" className="h-8 w-full bg-background text-foreground hover:bg-background/90">
              <Link to={currentActionTo} data-testid="policy-current-action">
                {currentAction.label}
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              className="h-8 w-full bg-background text-foreground hover:bg-background/90"
              data-testid="policy-current-action"
              onClick={'onClick' in currentAction ? currentAction.onClick : undefined}
              disabled={('disabled' in currentAction && currentAction.disabled) || Boolean(busy)}
            >
              {currentAction.label}
              <ArrowRight className="size-4" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
