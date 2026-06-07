// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { useState } from 'react';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { InteractionLockOverlay } from '@/components/InteractionLockOverlay';
import { useRedactionPresets } from './hooks/use-redaction-presets';
import { PresetColumn } from './components/preset-column';
import { RedactionBridgeConfig } from './redaction-bridge-config';
import { RedactionPresetDialog } from './redaction-preset-dialog';

export function RedactionList() {
  const t = useT();
  const state = useRedactionPresets();
  const [operationLoading, setOperationLoading] = useState(false);

  const runLocked = async (action: () => void | Promise<void>) => {
    if (operationLoading) return;
    setOperationLoading(true);
    try {
      await action();
    } finally {
      setOperationLoading(false);
    }
  };

  if (state.loading) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
          <Card className="overflow-hidden">
            <CardHeader className="pb-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-80 max-w-full" />
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Skeleton className="h-20 w-full rounded-xl" />
              <div className="grid gap-3 md:grid-cols-2">
                <Skeleton className="h-16 w-full rounded-xl" />
                <Skeleton className="h-16 w-full rounded-xl" />
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Skeleton className="h-[22rem] w-full rounded-xl" />
                <Skeleton className="h-[22rem] w-full rounded-xl" />
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        <div className="page-stack gap-3 overflow-hidden">
          {state.loadError && (
            <Alert variant="destructive">
              <AlertDescription>{state.loadError}</AlertDescription>
            </Alert>
          )}

          <header className="flex flex-none flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <span className="saas-kicker">{t('nav.redactionList.sub')}</span>
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                {t('settings.redaction.configTitle')}
              </h1>
              <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
                {t('settings.redaction.configDesc')}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="whitespace-nowrap"
                onClick={() => state.openNew('text')}
                data-testid="new-text-preset"
              >
                {t('settings.redaction.newText')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="whitespace-nowrap"
                onClick={() => state.openNew('vision')}
                data-testid="new-vision-preset"
              >
                {t('settings.redaction.newVision')}
              </Button>
            </div>
          </header>

          <Card className="page-surface overflow-hidden border-border/70 shadow-[var(--shadow-control)]">
            <CardContent className="page-surface-body flex flex-col gap-3 p-4">
            <RedactionBridgeConfig
              bridgeText={state.bridgeText}
              bridgeVision={state.bridgeVision}
              textPresets={state.textPresets}
              visionPresets={state.visionPresets}
              summaryTextLabel={state.summaryTextLabel}
              summaryVisionLabel={state.summaryVisionLabel}
              setBridgeText={state.setBridgeText}
              setBridgeVision={state.setBridgeVision}
            />

            <div className="grid gap-3 md:grid-cols-2">
              <PresetColumn
                title={t('settings.redaction.textColumn')}
                defaultPreset={state.defaultTextPreset}
                presets={state.textPresets}
                entityTypes={state.effectiveEntityTypes}
                pipelines={state.effectivePipelines}
                expanded={state.expanded}
                setExpanded={state.setExpanded}
                colPrefix="text"
                onEdit={state.openEdit}
                onDelete={(id) =>
                  state.setConfirmState({
                    title: t('common.delete'),
                    message: t('settings.redaction.confirmDelete'),
                    danger: true,
                    onConfirm: () => state.removePreset(id),
                  })
                }
              />
              <PresetColumn
                title={t('settings.redaction.visionColumn')}
                defaultPreset={state.defaultVisionPreset}
                presets={state.visionPresets}
                entityTypes={state.effectiveEntityTypes}
                pipelines={state.effectivePipelines}
                expanded={state.expanded}
                setExpanded={state.setExpanded}
                colPrefix="vision"
                onEdit={state.openEdit}
                onDelete={(id) =>
                  state.setConfirmState({
                    title: t('common.delete'),
                    message: t('settings.redaction.confirmDelete'),
                    danger: true,
                    onConfirm: () => state.removePreset(id),
                  })
                }
              />
            </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <RedactionPresetDialog
        modalOpen={state.modalOpen}
        editingPresetId={state.editingPresetId}
        presetForm={state.presetForm}
        saving={state.saving}
        regexTypes={state.regexTypes}
        semanticTypes={state.semanticTypes}
        effectivePipelines={state.effectivePipelines}
        presetKindLabel={state.presetKindLabel}
        setPresetForm={state.setPresetForm}
        setModalOpen={state.setModalOpen}
        saveModal={state.saveModal}
      />
      {state.confirmState && (
        <ConfirmDialog
          open
          title={state.confirmState.title}
          message={state.confirmState.message}
          danger={state.confirmState.danger}
          onConfirm={() =>
            void runLocked(async () => {
              const action = state.confirmState?.onConfirm;
              state.setConfirmState(null);
              await action?.();
            })
          }
          onCancel={() => state.setConfirmState(null)}
        />
      )}
      <InteractionLockOverlay active={operationLoading || state.saving} />
    </div>
  );
}
