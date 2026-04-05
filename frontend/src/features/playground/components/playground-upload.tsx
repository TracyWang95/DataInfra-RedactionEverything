/**
 * Playground upload stage: intake plus recognition configuration.
 */
import { type FC } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useServiceHealth } from '@/hooks/use-service-health';
import { getEntityTypeName } from '@/config/entityTypes';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { getSelectionToneClasses, type SelectionTone } from '@/ui/selectionPalette';
import type { usePlayground } from '../hooks/use-playground';

type PlaygroundCtx = ReturnType<typeof usePlayground>;
type RecognitionCtx = PlaygroundCtx['recognition'];
const DEFAULT_PRESET_VALUE = '__default__';

interface PlaygroundUploadProps {
  ctx: PlaygroundCtx;
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const t = useT();
  const { health } = useServiceHealth();
  const { dropzone, recognition: rec } = ctx;
  const { getRootProps, getInputProps, isDragActive } = dropzone;
  const backendUnavailable = !health;

  return (
    <div
      className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-hidden p-3 lg:flex-row lg:gap-5 lg:p-5"
      data-testid="playground-upload"
    >
      <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center">
        <div className="w-full max-w-xl">
          <div className="mb-4 space-y-2">
            <span className="saas-kicker">{t('playground.upload.kicker')}</span>
            <div>
              <h2 className="text-2xl font-semibold tracking-[-0.04em] text-foreground">
                {t('playground.upload.title')}
              </h2>
              <p className="mt-2 text-sm leading-7 text-muted-foreground">
                {t('playground.upload.desc')}
              </p>
            </div>
          </div>

          <div
            {...getRootProps()}
            className={cn(
              'saas-hero group relative cursor-pointer border-2 border-dashed p-12 text-center transition-all duration-300 ease-out',
              isDragActive
                ? 'border-primary bg-primary/[0.04] ring-4 ring-primary/10'
                : 'border-border hover:border-foreground/15 hover:shadow-lg',
            )}
            data-testid="playground-dropzone"
          >
            <input {...getInputProps()} className="hidden" />
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  'mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[20px] bg-foreground text-background transition-transform duration-300 group-hover:scale-110',
                  isDragActive && 'scale-110 animate-pulse',
                )}
              >
                <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
              </div>
              <p className="mb-1.5 text-lg font-semibold tracking-[-0.02em]">
                {t('playground.dropHere')}
              </p>
              <p className="mb-5 text-sm text-muted-foreground">
                {t('playground.supportedFormats')}
              </p>
              <div className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card px-4 py-2 text-xs font-medium text-foreground">
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                {t('playground.clickToUpload')}
              </div>
            </div>
          </div>
        </div>
      </div>

      <Card
        className="flex w-full shrink-0 overflow-hidden border-border/70 bg-card lg:w-[min(100%,420px)] lg:self-stretch xl:w-[440px]"
        data-testid="playground-type-panel"
      >
        <Tabs
          value={rec.typeTab}
          onValueChange={(value) => rec.setTypeTab(value as 'text' | 'vision')}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="space-y-3 border-b border-border/70 px-4 py-4">
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
                <TabsTrigger value="text" className="rounded-full px-3 py-1 text-xs">
                  {t('playground.text')}
                </TabsTrigger>
                <TabsTrigger value="vision" className="rounded-full px-3 py-1 text-xs">
                  {t('playground.vision')}
                </TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors rec={rec} disabledText={rec.textConfigState !== 'ready'} disabledVision={rec.visionConfigState !== 'ready'} />
            {backendUnavailable && (
              <div className="rounded-2xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2 text-xs text-[var(--warning-foreground)]">
                {t('playground.upload.offlineHint')}
              </div>
            )}
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <TabsContent value="text" className="mt-0 space-y-3 p-3">
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent value="vision" className="mt-0 space-y-3 p-3">
              <VisionPipelines rec={rec} />
            </TabsContent>
          </ScrollArea>

          <div className="shrink-0 border-t border-border/70 px-4 py-2">
            <p className="text-center text-xs text-muted-foreground" data-testid="playground-type-summary">
              {rec.typeTab === 'vision'
                ? `${t('playground.ocrShort')} ${rec.selectedOcrHasTypes.length} / ${t('playground.imageShort')} ${rec.selectedHasImageTypes.length}`
                : `${rec.selectedTypes.length} / ${rec.entityTypes.length} ${t('playground.selected')}`}
            </p>
          </div>
        </Tabs>
      </Card>
    </div>
  );
};

const PresetSelectors: FC<{
  rec: RecognitionCtx;
  disabledText: boolean;
  disabledVision: boolean;
}> = ({ rec, disabledText, disabledVision }) => {
  const t = useT();

  return (
    <div className="flex flex-col gap-2.5">
      <PresetRow
        label={t('playground.textPresetLabel')}
        presets={rec.textPresetsPg}
        activeId={rec.playgroundPresetTextId}
        onSelect={rec.selectPlaygroundTextPresetById}
        onSave={rec.saveTextPresetFromPlayground}
        saveLabel={t('playground.saveAsTextPreset')}
        disabled={disabledText}
      />
      <PresetRow
        label={t('playground.visionPresetLabel')}
        presets={rec.visionPresetsPg}
        activeId={rec.playgroundPresetVisionId}
        onSelect={rec.selectPlaygroundVisionPresetById}
        onSave={rec.saveVisionPresetFromPlayground}
        saveLabel={t('playground.saveAsVisionPreset')}
        disabled={disabledVision}
      />
    </div>
  );
};

const PresetRow: FC<{
  label: string;
  presets: { id: string; name: string; kind?: string }[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onSave: () => void;
  saveLabel: string;
  disabled: boolean;
}> = ({ label, presets, activeId, onSelect, onSave, saveLabel, disabled }) => {
  const t = useT();

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-2">
        <Select
          value={activeId ?? DEFAULT_PRESET_VALUE}
          onValueChange={(value) => onSelect(value === DEFAULT_PRESET_VALUE ? '' : value)}
          disabled={disabled}
        >
          <SelectTrigger
            className="h-9 min-w-0 flex-1 rounded-xl border-border/70 px-3 text-xs"
            data-testid="playground-preset-select"
          >
            <SelectValue placeholder={t('playground.defaultPreset')} />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value={DEFAULT_PRESET_VALUE}>{t('playground.defaultPreset')}</SelectItem>
              {presets.map((preset) => (
                <SelectItem key={preset.id} value={preset.id}>
                  {preset.name}
                  {preset.kind === 'full' ? ` (${t('playground.fullPreset')})` : ''}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          className="h-9 shrink-0 rounded-xl px-3 text-xs"
          onClick={() => void onSave()}
          disabled={disabled}
        >
          {saveLabel}
        </Button>
      </div>
    </div>
  );
};

const TextTypeGroups: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();

  if (rec.textConfigState === 'loading') {
    return <p className="py-10 text-center text-sm text-muted-foreground">{t('playground.loading')}</p>;
  }

  if (rec.textConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.textConfigUnavailableTitle')}
        description={t('playground.textConfigUnavailableDesc')}
      />
    );
  }

  if (rec.textConfigState === 'empty' || rec.playgroundTextGroups.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.textConfigEmptyTitle')}
        description={t('playground.textConfigEmptyDesc')}
      />
    );
  }

  return (
    <>
      {rec.playgroundTextGroups.map((group) => {
        const ids = group.types.map((type) => type.id);
        const allOn = ids.length > 0 && ids.every((id) => rec.selectedTypes.includes(id));
        const toneClasses = getSelectionToneClasses(group.tone);

        return (
          <section
            key={group.key}
            className="overflow-hidden rounded-[22px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-text-group-${group.key}`}
          >
            <div className={cn('flex items-center justify-between gap-3 border-b px-3.5 py-3', toneClasses.headerSurface)}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span className={cn('truncate text-xs font-semibold tracking-[0.02em]', toneClasses.titleText)}>
                  {group.label}
                </span>
                <Badge
                  variant="secondary"
                  className={cn('rounded-full border bg-background/85 text-[10px] shadow-none', toneClasses.badgeText)}
                >
                  {group.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 rounded-full px-2.5 text-[11px]"
                onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}
              >
                {allOn ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className="grid gap-2 p-3 sm:grid-cols-2">
              {group.types.map((type) => {
                const checked = rec.selectedTypes.includes(type.id);
                const typeName = resolveTextTypeName(type.id, type.name);
                return (
                  <label
                    key={`${group.key}-${type.id}`}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-start gap-2 rounded-2xl border px-3 py-2.5 text-xs leading-5 transition-colors',
                      checked
                        ? toneClasses.cardSelectedCompact
                        : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                    )}
                    title={type.description || typeName}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => {
                        rec.clearPlaygroundTextPresetTracking();
                        rec.setSelectedTypes((previous: string[]) =>
                          checked ? previous.filter((id) => id !== type.id) : [...previous, type.id],
                        );
                      }}
                      className="mt-0.5 h-4 w-4"
                    />
                    <span className="min-w-0 break-words font-medium">{typeName}</span>
                  </label>
                );
              })}
            </div>
          </section>
        );
      })}
    </>
  );
};

const VisionPipelines: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();

  if (rec.visionConfigState === 'loading') {
    return <p className="py-10 text-center text-sm text-muted-foreground">{t('playground.loading')}</p>;
  }

  if (rec.visionConfigState === 'unavailable') {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigUnavailableTitle')}
        description={t('playground.visionConfigUnavailableDesc')}
      />
    );
  }

  if (rec.visionConfigState === 'empty' || rec.pipelines.length === 0) {
    return (
      <ConfigEmptyState
        title={t('playground.visionConfigEmptyTitle')}
        description={t('playground.visionConfigEmptyDesc')}
      />
    );
  }

  return (
    <>
      {rec.pipelines.map((pipeline) => {
        const isHasImage = pipeline.mode === 'has_image';
        const selectedSet = isHasImage ? rec.selectedHasImageTypes : rec.selectedOcrHasTypes;
        const allSelected = pipeline.types.length > 0 && pipeline.types.every((type) => selectedSet.includes(type.id));
        const tone: SelectionTone = isHasImage ? 'visual' : 'semantic';
        const toneClasses = getSelectionToneClasses(tone);

        return (
          <section
            key={pipeline.mode}
            className="overflow-hidden rounded-[22px] border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
            data-testid={`playground-pipeline-${pipeline.mode}`}
          >
            <div className={cn('flex items-center justify-between gap-3 border-b px-3.5 py-3', toneClasses.headerSurface)}>
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('size-2 rounded-full', toneClasses.dot)} />
                <span className={cn('truncate text-xs font-semibold tracking-[0.02em]', toneClasses.titleText)}>
                  {isHasImage ? t('playground.imageFeatures') : t('playground.ocrText')}
                </span>
                <Badge
                  variant="secondary"
                  className={cn('rounded-full border bg-background/85 text-[10px] shadow-none', toneClasses.badgeText)}
                >
                  {pipeline.types.length}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 rounded-full px-2.5 text-[11px]"
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  const ids = pipeline.types.map((type) => type.id);
                  if (allSelected) {
                    isHasImage ? rec.updateHasImageTypes([]) : rec.updateOcrHasTypes([]);
                  } else {
                    isHasImage ? rec.updateHasImageTypes(ids) : rec.updateOcrHasTypes(ids);
                  }
                }}
              >
                {allSelected ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className="grid gap-2 p-3 sm:grid-cols-2">
              {pipeline.types.map((type) => {
                const checked = selectedSet.includes(type.id);
                return (
                  <label
                    key={type.id}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-start gap-2 rounded-2xl border px-3 py-2.5 text-xs leading-5 transition-colors',
                      checked
                        ? toneClasses.cardSelectedCompact
                        : 'border-border/70 bg-background hover:border-border hover:bg-accent/35',
                    )}
                    title={type.description || type.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => rec.toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                      className="mt-0.5 h-4 w-4"
                    />
                    <span className="min-w-0 break-words font-medium">{type.name}</span>
                  </label>
                );
              })}
            </div>
          </section>
        );
      })}
    </>
  );
};

function ConfigEmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-[22px] border border-dashed border-border/70 bg-muted/20 px-5 py-8 text-center">
      <p className="text-sm font-semibold tracking-[-0.02em] text-foreground">{title}</p>
      <p className="mt-2 text-xs leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

function resolveTextTypeName(typeId: string, fallbackName?: string) {
  return fallbackName?.trim() || getEntityTypeName(typeId);
}
