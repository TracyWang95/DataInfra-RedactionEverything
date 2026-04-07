// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useServiceHealth } from '@/hooks/use-service-health';
import { useT } from '@/i18n';
import type { usePlayground } from '../hooks/use-playground';
import { PlaygroundUploadDropzone } from './playground-upload-dropzone';
import { TextTypeGroups, VisionPipelines } from './playground-upload-config';
import { PresetSelectors, PresetSaveDialog } from './playground-upload-presets';

interface PlaygroundUploadProps {
  ctx: ReturnType<typeof usePlayground>;
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const t = useT();
  const { health } = useServiceHealth();
  const { dropzone, recognition: rec } = ctx;
  const backendUnavailable = !health;

  return (
    <div
      className="grid h-full min-h-0 min-w-0 flex-1 grid-cols-1 gap-3 overflow-hidden lg:h-[calc(100vh-7.5rem)] lg:grid-cols-[minmax(0,1.08fr)_minmax(21.5rem,25.5rem)] lg:items-stretch lg:gap-4 xl:h-[calc(100vh-7.75rem)] xl:grid-cols-[minmax(0,1.14fr)_minmax(22.5rem,27rem)] 2xl:h-[calc(100vh-8rem)] 2xl:grid-cols-[minmax(0,1.2fr)_minmax(23.5rem,28.5rem)]"
      data-testid="playground-upload"
    >
      <PlaygroundUploadDropzone dropzone={dropzone} />

      <Card
        className="page-surface w-full shrink-0 overflow-hidden border-border/70 bg-card lg:h-full lg:max-h-full lg:self-stretch"
        data-testid="playground-type-panel"
      >
        <Tabs
          value={rec.typeTab}
          onValueChange={(value) => rec.setTypeTab(value as 'text' | 'vision')}
          className="flex h-full min-h-0 flex-col"
        >
          <div className="space-y-2 border-b border-border/70 px-3.5 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  {t('playground.recognitionTypes')}
                </h3>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('playground.upload.configDesc')}
                </p>
              </div>
              <TabsList className="h-8 rounded-full border border-border/70 bg-muted/35 p-1">
                <TabsTrigger
                  value="text"
                  className="rounded-full px-3 py-1 text-xs"
                  data-testid="playground-tab-text"
                >
                  {t('playground.text')}
                  <span className="ml-1 tabular-nums text-[10px] text-muted-foreground">
                    {rec.entityTypes.length}
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="vision"
                  className="rounded-full px-3 py-1 text-xs"
                  data-testid="playground-tab-vision"
                >
                  {t('playground.vision')}
                  <span className="ml-1 tabular-nums text-[10px] text-muted-foreground">
                    {rec.visionTypes.length}
                  </span>
                </TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors rec={rec} disabledText={rec.textConfigState !== 'ready'} disabledVision={rec.visionConfigState !== 'ready'} />
            {backendUnavailable && (
              <div
                className="rounded-2xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2 text-xs text-[var(--warning-foreground)]"
                data-testid="playground-offline-hint"
              >
                {t('playground.upload.offlineHint')}
              </div>
            )}
          </div>

          <div className="page-surface-body flex min-h-0 flex-1 flex-col overflow-hidden">
            <TabsContent value="text" className="mt-0 min-h-full flex-col gap-2 p-2 pb-0 data-[state=active]:flex 2xl:p-2.5 2xl:pb-0">
              <div className="rounded-[18px] border border-border/70 bg-muted/20 px-3 py-2">
                <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                  {t('playground.text')}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {rec.selectedTypes.length} / {rec.entityTypes.length} {t('playground.selected')}
                </p>
              </div>
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent value="vision" className="mt-0 min-h-full flex-col gap-2 p-2 pb-0 data-[state=active]:flex 2xl:p-2.5 2xl:pb-0">
              <div className="rounded-[18px] border border-border/70 bg-muted/20 px-3 py-2">
                <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                  {t('playground.vision')}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('playground.ocrShort')} {rec.selectedOcrHasTypes.length} / {rec.pipelines.find((pipeline) => pipeline.mode === 'ocr_has')?.types.length ?? 0}
                  <span className="mx-2 text-border">·</span>
                  {t('playground.imageShort')} {rec.selectedHasImageTypes.length} / {rec.pipelines.find((pipeline) => pipeline.mode === 'has_image')?.types.length ?? 0}
                </p>
              </div>
              <VisionPipelines rec={rec} />
            </TabsContent>
          </div>

          <div className="page-surface-footer !bg-transparent !backdrop-blur-none" style={{ padding: '0.125rem 1rem 0.25rem' }}>
            <p className="text-center text-xs leading-none text-muted-foreground" data-testid="playground-type-summary">
              {rec.typeTab === 'vision'
                ? `${t('playground.ocrShort')} ${rec.selectedOcrHasTypes.length} / ${t('playground.imageShort')} ${rec.selectedHasImageTypes.length}`
                : `${rec.selectedTypes.length} / ${rec.entityTypes.length} ${t('playground.selected')}`}
            </p>
          </div>
        </Tabs>
      </Card>
      <PresetSaveDialog rec={rec} />
    </div>
  );
};
