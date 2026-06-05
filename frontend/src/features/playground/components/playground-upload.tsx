// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useServiceHealth, type ServicesHealth } from '@/hooks/use-service-health';
import { useT } from '@/i18n';
import type { usePlayground } from '../hooks/use-playground';
import { PlaygroundUploadDropzone } from './playground-upload-dropzone';
import { TextTypeGroups, VisionPipelines } from './playground-upload-config';
import { PresetSelectors, PresetSaveDialog } from './playground-upload-presets';

interface PlaygroundUploadProps {
  ctx: ReturnType<typeof usePlayground>;
}

type Service = NonNullable<ServicesHealth['services'][keyof ServicesHealth['services']]>;
type ServiceStatus = Service['status'];
type Translate = (key: string) => string;

const blockedServiceStatuses = new Set<ServiceStatus>(['offline', 'degraded']);

function serviceStatusLabel(status: ServiceStatus, t: Translate) {
  return t(`health.${status}`);
}

function serviceDisplayName(service: Service, t: Translate) {
  const rawName = service.name.toLowerCase();
  if (rawName.includes('paddle')) return t('health.service.paddle_ocr');
  if (rawName.includes('has text') || rawName.includes('has_')) return t('health.service.has_ner');
  if (rawName.includes('visual') || rawName.includes('locate')) return t('health.service.visual_features');
  return service.name;
}

function serviceSummary(services: Service[], t: Translate) {
  return services
    .map((service) => `${serviceDisplayName(service, t)}: ${serviceStatusLabel(service.status, t)}`)
    .join(', ');
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const t = useT();
  const { health, checking } = useServiceHealth();
  const { dropzone, uploadIssue, recognition: rec } = ctx;
  const visualTypeCount =
    rec.pipelines.find((pipeline) => pipeline.mode === 'visual_features')?.types.length ?? 0;
  const selectedVisualTypeCount = rec.selectedVisualFeatureTypes.length;
  const services = health
    ? (['paddle_ocr', 'has_ner', 'visual_features'] as const)
        .map((key) => health.services[key])
        .filter((service): service is Service => Boolean(service))
    : [];
  const blockedServices = services.filter((service) => blockedServiceStatuses.has(service.status));
  const backendChecking = !health && checking;
  const backendUnavailable = !health && !checking;
  const modelServicesBlocked = blockedServices.length > 0;
  const serviceHintKey = backendUnavailable
    ? 'playground.upload.offlineHint'
    : backendChecking
      ? 'playground.upload.checkingHint'
      : 'playground.upload.modelOfflineHint';
  const serviceActionKey = backendUnavailable
    ? 'playground.upload.offlineAction'
    : backendChecking
      ? 'playground.upload.checkingAction'
      : 'playground.upload.modelOfflineAction';
  const attentionSummary = serviceSummary(blockedServices, t);
  const uploadBlocked = backendUnavailable;
  const disabledReason = uploadBlocked
    ? attentionSummary
      ? `${t(serviceHintKey)} ${attentionSummary}`
      : t(serviceHintKey)
    : undefined;

  return (
    <div
      className="grid h-full min-h-0 min-w-0 flex-1 grid-cols-1 gap-3 overflow-hidden lg:grid-cols-[minmax(0,1fr)_minmax(28rem,30rem)] lg:items-stretch xl:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)] 2xl:grid-cols-[minmax(0,1fr)_minmax(32rem,34rem)]"
      data-testid="playground-upload"
    >
      <PlaygroundUploadDropzone
        dropzone={dropzone}
        disabled={uploadBlocked}
        disabledReason={disabledReason}
        uploadIssue={uploadIssue}
      />

      <Card
        className="page-surface min-h-0 w-full shrink-0 overflow-hidden border-border/70 bg-card lg:h-full lg:max-h-full lg:self-stretch"
        data-testid="playground-type-panel"
      >
        <Tabs
          value={rec.typeTab}
          onValueChange={(value) => rec.setTypeTab(value as 'text' | 'vision')}
          className="flex h-full min-h-0 flex-col"
        >
          <div className="shrink-0 space-y-1.5 border-b border-border/70 px-3 py-2.5">
            <div className="flex items-start justify-between gap-2.5">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  {t('playground.recognitionTypes')}
                </h3>
                <p
                  className="mt-0.5 truncate text-xs leading-4 text-muted-foreground"
                  title={t('playground.upload.configDesc')}
                >
                  {t('playground.upload.configDesc')}
                </p>
              </div>
              <TabsList className="h-8 shrink-0 rounded-full border border-border/70 bg-muted/35 p-1">
                <TabsTrigger
                  value="text"
                  className="whitespace-nowrap rounded-full px-3 py-1 text-xs"
                  data-testid="playground-tab-text"
                >
                  {t('playground.text')}
                  <span className="ml-1 tabular-nums text-[10px] text-muted-foreground">
                    {rec.entityTypes.length}
                  </span>
                </TabsTrigger>
                <TabsTrigger
                  value="vision"
                  className="whitespace-nowrap rounded-full px-3 py-1 text-xs"
                  data-testid="playground-tab-vision"
                >
                  {t('playground.vision')}
                  <span className="ml-1 tabular-nums text-[10px] text-muted-foreground">
                    {rec.visionTypes.length}
                  </span>
                </TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors
              rec={rec}
              disabledText={rec.textConfigState !== 'ready'}
              disabledVision={rec.visionConfigState !== 'ready'}
            />
            {(backendUnavailable ||
              backendChecking ||
              modelServicesBlocked) && (
              <div
                className="max-h-[4.75rem] space-y-1 overflow-hidden rounded-xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-2.5 py-1.5 text-[11px] leading-4 text-[var(--warning-foreground)]"
                data-testid="playground-offline-hint"
              >
                <p className="truncate" title={t(serviceHintKey)}>
                  {t(serviceHintKey)}
                </p>
                {attentionSummary && (
                  <p className="truncate" title={attentionSummary}>
                    <span className="font-medium">{t('playground.upload.affectedServices')}</span>{' '}
                    <span data-testid="playground-affected-services">{attentionSummary}</span>
                  </p>
                )}
                <p className="truncate" title={t(serviceActionKey)}>
                  <span className="font-medium">{t('playground.upload.nextAction')}</span>{' '}
                  {t(serviceActionKey)}
                </p>
              </div>
            )}
          </div>

          <div className="page-surface-body flex min-h-0 flex-1 flex-col overflow-hidden">
            <TabsContent
              value="text"
              className="mt-0 h-full min-h-0 flex-col gap-2 p-2 pb-0 data-[state=active]:flex"
            >
              <div className="flex shrink-0 items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/20 px-3 py-2">
                <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                  {t('playground.text')}
                </p>
                <p className="shrink-0 whitespace-nowrap text-xs leading-4 text-muted-foreground">
                  {rec.selectedTypes.length} / {rec.entityTypes.length} {t('playground.selected')}
                </p>
              </div>
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent
              value="vision"
              className="mt-0 h-full min-h-0 flex-col gap-2 p-2 pb-0 data-[state=active]:flex"
            >
              <div className="flex shrink-0 items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/20 px-3 py-2">
                <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                  {t('playground.vision')}
                </p>
                <p className="min-w-0 shrink truncate text-right text-xs leading-4 text-muted-foreground">
                  {t('playground.ocrShort')} {rec.selectedOcrHasTypes.length} /{' '}
                  {rec.pipelines.find((pipeline) => pipeline.mode === 'ocr_has')?.types.length ?? 0}
                  <span className="mx-2 text-border">|</span>
                  {t('playground.visualFeatureShort')} {selectedVisualTypeCount} / {visualTypeCount}
                </p>
              </div>
              <VisionPipelines rec={rec} />
            </TabsContent>
          </div>

          <div
            className="page-surface-footer !bg-transparent !backdrop-blur-none"
            style={{ padding: '0.125rem 1rem 0.25rem' }}
          >
            <p
              className="text-center text-xs leading-none text-muted-foreground"
              data-testid="playground-type-summary"
            >
              {rec.typeTab === 'vision'
                ? `${t('playground.ocrShort')} ${rec.selectedOcrHasTypes.length} / ${t('playground.visualFeatureShort')} ${selectedVisualTypeCount}`
                : `${rec.selectedTypes.length} / ${rec.entityTypes.length} ${t('playground.selected')}`}
            </p>
          </div>
        </Tabs>
      </Card>
      <PresetSaveDialog rec={rec} />
    </div>
  );
};
