// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { Eye } from 'lucide-react';
import { useT } from '@/i18n';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
  textPreviewGroups: PreviewGroup[];
  imagePreviewGroups: PreviewGroup[];
  textPresetName: string;
  visionPresetName: string;
  textModeLabel: string;
  imageDetailPills: string[];
  previewDialog: 'text' | 'image' | null;
  setPreviewDialog: (v: 'text' | 'image' | null) => void;
}

export const BatchStep1PreviewCards: FC<BatchStep1PreviewCardsProps> = ({
  textPreviewGroups,
  imagePreviewGroups,
  textPresetName,
  visionPresetName,
  textModeLabel,
  imageDetailPills,
  previewDialog,
  setPreviewDialog,
}) => {
  const t = useT();

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
      <div className="grid flex-1 gap-2 xl:grid-cols-2">
        <SelectionPreviewSummaryCard
          title={t('batchWizard.step1.textSummary')}
          presetName={textPresetName}
          presetLabel={t('batchWizard.step1.activePreset')}
          groups={textPreviewGroups}
          summaryPills={[`${t('batchWizard.step1.currentTextMethod')}${textModeLabel}`]}
          onViewDetails={() => setPreviewDialog('text')}
          viewLabel={t('batchWizard.step1.viewSelection')}
        />
        <SelectionPreviewSummaryCard
          title={t('batchWizard.step1.imageSummary')}
          presetName={visionPresetName}
          presetLabel={t('batchWizard.step1.activePreset')}
          groups={imagePreviewGroups}
          summaryPills={imageDetailPills}
          onViewDetails={() => setPreviewDialog('image')}
          viewLabel={t('batchWizard.step1.viewSelection')}
        />
      </div>

      <Dialog open={previewDialog !== null} onOpenChange={(open) => !open && setPreviewDialog(null)}>
        {previewDialogConfig ? (
          <DialogContent className="max-w-5xl gap-0 overflow-hidden border-border/70 bg-[var(--surface-overlay)] p-0">
            <DialogHeader className="border-b border-border/70 px-6 pb-4 pt-6">
              <DialogTitle>{previewDialogConfig.title}</DialogTitle>
              <DialogDescription className="text-sm leading-relaxed">
                {previewDialogConfig.presetLabel}
                <span className="ml-1 font-medium text-foreground">{previewDialogConfig.presetName}</span>
              </DialogDescription>
            </DialogHeader>

            <div className="flex max-h-[72vh] flex-col gap-5 overflow-y-auto px-6 py-5">
              {previewDialogConfig.summaryPills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {previewDialogConfig.summaryPills.map((pill) => (
                    <span
                      key={pill}
                      className="rounded-full border border-border/70 bg-background px-3 py-1.5 text-xs font-medium text-foreground"
                    >
                      {pill}
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="grid gap-4 xl:grid-cols-2">
                {previewDialogConfig.groups.map((group) => (
                  <div
                    key={group.title}
                    className="surface-subtle flex min-h-[16rem] flex-col gap-3 px-4 py-4"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="space-y-1">
                        <p className="text-sm font-semibold text-foreground">{group.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {t('batchWizard.step1.selectedTotal').replace('{n}', String(group.items.length))}
                        </p>
                      </div>
                    </div>

                    {group.items.length > 0 ? (
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {group.items.map((item) => (
                          <span
                            key={`${group.title}-${item}`}
                            className="flex h-9 items-center rounded-2xl border border-border/70 bg-background px-3 text-xs font-medium text-foreground"
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
};

function SelectionPreviewSummaryCard({
  title,
  presetLabel,
  presetName,
  groups,
  summaryPills = [],
  onViewDetails,
  viewLabel,
}: {
  title: string;
  presetLabel: string;
  presetName: string;
  groups: Array<{ title: string; items: string[]; emptyLabel: string }>;
  summaryPills?: string[];
  onViewDetails: () => void;
  viewLabel: string;
}) {
  const t = useT();
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const firstGroup = groups[0];
  const secondGroup = groups[1];

  return (
    <Card className="rounded-[20px] border-border/70 bg-card/90 shadow-[var(--shadow-sm)]">
      <CardContent className="flex h-full flex-col gap-1.5 p-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-0.5">
            <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{title}</p>
            <p className="text-xs text-muted-foreground">
              {presetLabel}
              <span className="ml-1 font-medium text-foreground">{presetName}</span>
            </p>
            {summaryPills.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-0.5">
                {summaryPills.map((pill) => (
                  <span
                    key={pill}
                    className="rounded-full border border-border/70 bg-background px-2 py-0.5 text-[11px] font-medium text-foreground"
                  >
                    {pill}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="rounded-full border border-border/70 bg-muted/35 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
              {total}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 rounded-full px-2.5"
              onClick={onViewDetails}
            >
              <Eye data-icon="inline-start" />
              {viewLabel}
            </Button>
          </div>
        </div>

        <div className="grid flex-1 gap-2 sm:grid-cols-2">
          {[firstGroup, secondGroup].filter(Boolean).map((group) => (
            <div key={group!.title} className="surface-subtle flex items-center justify-between gap-2 px-2.5 py-2">
              <div className="space-y-0.5">
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {group!.title}
                </p>
                <p className="text-[11px] leading-4 text-muted-foreground">
                  {group!.items.length > 0
                    ? `${group!.items.slice(0, 3).join(' · ')}${t('batchWizard.step1.summaryEtc')}`
                    : group!.emptyLabel}
                </p>
              </div>
              <span className="rounded-full border border-border/70 bg-background px-2 py-0.5 text-[11px] font-medium text-foreground">
                {group!.items.length}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
