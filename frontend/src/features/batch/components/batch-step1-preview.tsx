// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo } from 'react';

import { Eye } from 'lucide-react';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import type { BatchWizardMode } from '@/services/batchPipeline';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export interface PreviewGroup {
  title: string;
  items: string[];
  emptyLabel: string;
}

export interface PreviewDialogConfig {
  title: string;
  presetName: string;
  presetLabel: string;
  groups: PreviewGroup[];
  summaryPills: string[];
}

export interface BatchStep1PreviewCardsProps {
  mode: BatchWizardMode;
  textPreviewGroups: PreviewGroup[];
  imagePreviewGroups: PreviewGroup[];
  textPresetName: string;
  visionPresetName: string;
  textModeLabel: string;
  imageDetailPills: string[];
  previewDialog: 'text' | 'image' | null;
  setPreviewDialog: (v: 'text' | 'image' | null) => void;
}

function BatchStep1PreviewCardsInner({
  mode,
  textPreviewGroups,
  imagePreviewGroups,
  textPresetName,
  visionPresetName,
  textModeLabel,
  imageDetailPills,
  previewDialog,
  setPreviewDialog,
}: BatchStep1PreviewCardsProps) {
  const t = useT();
  const showTextPreview = mode !== 'image';
  const showImagePreview = mode !== 'text';

  const previewDialogConfig: PreviewDialogConfig | null =
    previewDialog === 'text'
      ? {
          title: t('batchWizard.step1.textSummary'),
          presetName: textPresetName,
          presetLabel: t('batchWizard.step1.activePreset'),
          groups: textPreviewGroups,
          summaryPills: [`${t('batchWizard.step1.currentTextMethod')}${textModeLabel}`],
        }
      : previewDialog === 'image'
        ? {
            title: t('batchWizard.step1.imageSummary'),
            presetName: visionPresetName,
            presetLabel: t('batchWizard.step1.activePreset'),
            groups: imagePreviewGroups,
            summaryPills: imageDetailPills,
          }
        : null;

  return (
    <>
      <div className="grid shrink-0 gap-2 xl:grid-cols-2">
        {showTextPreview && (
          <SelectionPreviewSummaryCard
            title={t('batchWizard.step1.textSummary')}
            presetName={textPresetName}
            presetLabel={t('batchWizard.step1.activePreset')}
            groups={textPreviewGroups}
            summaryPills={[`${t('batchWizard.step1.currentTextMethod')}${textModeLabel}`]}
            onViewDetails={() => setPreviewDialog('text')}
            viewLabel={t('batchWizard.step1.viewSelection')}
          />
        )}
        {showImagePreview && (
          <SelectionPreviewSummaryCard
            title={t('batchWizard.step1.imageSummary')}
            presetName={visionPresetName}
            presetLabel={t('batchWizard.step1.activePreset')}
            groups={imagePreviewGroups}
            summaryPills={imageDetailPills}
            onViewDetails={() => setPreviewDialog('image')}
            viewLabel={t('batchWizard.step1.viewSelection')}
            testId="step1-image-summary-card"
          />
        )}
      </div>

      <Dialog
        open={previewDialog !== null}
        onOpenChange={(open) => !open && setPreviewDialog(null)}
      >
        {previewDialogConfig ? (
          <DialogContent className="max-h-[82vh] max-w-5xl gap-0 overflow-hidden border-border/70 bg-[var(--surface-overlay)] p-0">
            <DialogHeader className="border-b border-border/70 px-5 pb-3 pt-5">
              <DialogTitle>{previewDialogConfig.title}</DialogTitle>
              <DialogDescription className="truncate text-sm leading-relaxed">
                {previewDialogConfig.presetLabel}
                <span className="ml-1 font-medium text-foreground">
                  {previewDialogConfig.presetName}
                </span>
              </DialogDescription>
            </DialogHeader>

            <div className="flex min-h-0 flex-col gap-4 overflow-hidden px-5 py-4">
              {previewDialogConfig.summaryPills.length > 0 ? (
                <div className="flex flex-nowrap gap-2 overflow-hidden">
                  {previewDialogConfig.summaryPills.map((pill) => (
                    <span
                      key={pill}
                      className="max-w-[18rem] truncate rounded-full border border-border/70 bg-white px-3 py-1.5 text-xs font-medium text-foreground"
                      title={pill}
                    >
                      {pill}
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="grid min-h-0 gap-4 xl:grid-cols-2">
                {previewDialogConfig.groups.map((group) => (
                  <div
                    key={group.title}
                    className="surface-subtle flex min-h-0 flex-col gap-3 px-4 py-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 space-y-1">
                        <p
                          className="truncate text-sm font-semibold text-foreground"
                          title={group.title}
                        >
                          {group.title}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {t('batchWizard.step1.selectedTotal').replace(
                            '{n}',
                            String(group.items.length),
                          )}
                        </p>
                      </div>
                    </div>

                    {group.items.length > 0 ? (
                      <div className="grid max-h-[15rem] grid-cols-2 gap-2 overflow-y-auto pr-1 sm:grid-cols-3">
                        {group.items.map((item) => (
                          <span
                            key={`${group.title}-${item}`}
                            className="flex h-8 items-center rounded-xl border border-border/70 bg-background px-3 text-xs font-medium text-foreground"
                            title={item}
                          >
                            <span className="truncate">{item}</span>
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-border/70 bg-background/80 px-4 text-center text-sm text-muted-foreground">
                        {group.emptyLabel}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}

export const BatchStep1PreviewCards = memo(BatchStep1PreviewCardsInner);

function SelectionPreviewSummaryCard({
  title,
  presetLabel,
  presetName,
  groups,
  summaryPills = [],
  onViewDetails,
  viewLabel,
  testId,
}: {
  title: string;
  presetLabel: string;
  presetName: string;
  groups: Array<{ title: string; items: string[]; emptyLabel: string }>;
  summaryPills?: string[];
  onViewDetails: () => void;
  viewLabel: string;
  testId?: string;
}) {
  const t = useT();
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const visibleGroups = groups.filter(Boolean);

  return (
    <div
      className="min-h-[7.75rem] rounded-xl border border-border/70 bg-white text-card-foreground shadow-[var(--shadow-sm)]"
      style={{ backgroundColor: '#fff' }}
      data-testid={testId}
    >
      <div className="flex h-full flex-col gap-1.5 p-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 space-y-0.5">
            <p
              className="truncate text-sm font-semibold tracking-[-0.02em] text-foreground"
              title={title}
            >
              {title}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {presetLabel}
              <span className="ml-1 font-medium text-foreground">{presetName}</span>
            </p>
            {summaryPills.length > 0 && (
              <div className="flex flex-nowrap gap-1 overflow-hidden pt-0.5">
                {summaryPills.map((pill) => (
                  <span
                    key={pill}
                    className="max-w-[12rem] truncate rounded-full border border-border/70 !bg-white px-2 py-0.5 text-[11px] font-medium text-foreground"
                    title={pill}
                  >
                    {pill}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="rounded-full border border-border/70 bg-white px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {total}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 shrink-0 rounded-full px-2.5 whitespace-nowrap"
              onClick={onViewDetails}
            >
              <Eye data-icon="inline-start" />
              {viewLabel}
            </Button>
          </div>
        </div>

        <div className="grid flex-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {visibleGroups.map((group) => (
            <div
              key={group.title}
              className="flex min-w-0 items-center justify-between gap-2 rounded-xl border border-border/70 !bg-white px-2.5 py-2"
            >
              <div className="min-w-0 space-y-0.5">
                <p className="truncate text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {group.title}
                </p>
                <p className="truncate text-[11px] leading-4 text-muted-foreground">
                  {group.items.length > 0
                    ? `${group!.items.slice(0, 3).join(' · ')}${t('batchWizard.step1.summaryEtc')}`
                    : group.emptyLabel}
                </p>
              </div>
              <span className="shrink-0 rounded-full border border-border/70 !bg-white px-2 py-0.5 text-[11px] font-medium text-foreground">
                {group.items.length}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
