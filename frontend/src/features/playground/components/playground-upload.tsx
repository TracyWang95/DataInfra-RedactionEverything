/**
 * Playground upload stage: drop zone plus recognition configuration.
 */
import { type FC } from 'react';
import { Button } from '@/components/ui/button';
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
import { getEntityTypeName } from '@/config/entityTypes';
import { cn } from '@/lib/utils';
import { useT } from '@/i18n';
import type { usePlayground } from '../hooks/use-playground';

type PlaygroundCtx = ReturnType<typeof usePlayground>;
type RecognitionCtx = PlaygroundCtx['recognition'];
const DEFAULT_PRESET_VALUE = '__default__';

interface PlaygroundUploadProps {
  ctx: PlaygroundCtx;
}

export const PlaygroundUpload: FC<PlaygroundUploadProps> = ({ ctx }) => {
  const t = useT();
  const { dropzone, recognition: rec } = ctx;
  const { getRootProps, getInputProps, isDragActive } = dropzone;

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
        className="w-full shrink-0 overflow-hidden lg:w-[min(100%,400px)] lg:self-stretch xl:w-[420px] 2xl:w-[460px]"
        data-testid="playground-type-panel"
      >
        <Tabs value={rec.typeTab} onValueChange={(value) => rec.setTypeTab(value as 'text' | 'vision')} className="flex min-h-0 flex-1 flex-col">
          <div className="space-y-1.5 border-b px-3 py-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold tracking-tight">
                {t('playground.recognitionTypes')}
              </h3>
              <TabsList className="h-7">
                <TabsTrigger value="text" className="px-2.5 py-1 text-xs">
                  {t('playground.text')}
                </TabsTrigger>
                <TabsTrigger value="vision" className="px-2.5 py-1 text-xs">
                  {t('playground.vision')}
                </TabsTrigger>
              </TabsList>
            </div>
            <PresetSelectors rec={rec} />
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <TabsContent value="text" className="mt-0 space-y-3 p-2">
              <TextTypeGroups rec={rec} />
            </TabsContent>
            <TabsContent value="vision" className="mt-0 space-y-3 p-2">
              <VisionPipelines rec={rec} />
            </TabsContent>
          </ScrollArea>

          <div className="shrink-0 border-t px-3 py-1.5">
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

function getTextGroupLabel(key: string, fallback: string, t: (key: string) => string) {
  const map: Record<string, string> = {
    regex: t('playground.group.regex'),
    llm: t('playground.group.llm'),
    other: t('playground.group.other'),
  };
  return map[key] || fallback;
}

const PresetSelectors: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();

  return (
    <div className="flex flex-col gap-2">
      <PresetRow
        label={t('playground.textPresetLabel')}
        presets={rec.textPresetsPg}
        activeId={rec.playgroundPresetTextId}
        onSelect={rec.selectPlaygroundTextPresetById}
        onSave={rec.saveTextPresetFromPlayground}
        saveLabel={t('playground.saveAsTextPreset')}
      />
      <PresetRow
        label={t('playground.visionPresetLabel')}
        presets={rec.visionPresetsPg}
        activeId={rec.playgroundPresetVisionId}
        onSelect={rec.selectPlaygroundVisionPresetById}
        onSave={rec.saveVisionPresetFromPlayground}
        saveLabel={t('playground.saveAsVisionPreset')}
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
}> = ({ label, presets, activeId, onSelect, onSave, saveLabel }) => {
  const t = useT();

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-medium text-muted-foreground">{label}</span>
      <div className="flex min-w-0 items-center gap-1.5">
        <Select
          value={activeId ?? DEFAULT_PRESET_VALUE}
          onValueChange={(value) => onSelect(value === DEFAULT_PRESET_VALUE ? '' : value)}
        >
          <SelectTrigger
            className="h-7 min-w-0 flex-1 rounded-lg px-2 text-xs"
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
          className="h-7 shrink-0 rounded-lg px-2.5 text-[10px]"
          onClick={() => void onSave()}
        >
          {saveLabel}
        </Button>
      </div>
    </div>
  );
};

const TextTypeGroups: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();

  if (rec.sortedEntityTypes.length === 0) {
    return <p className="py-8 text-center text-xs text-muted-foreground">{t('playground.loading')}</p>;
  }

  return (
    <>
      {rec.playgroundTextGroups.map((group) => {
        const ids = group.types.map((type) => type.id);
        const allOn = ids.length > 0 && ids.every((id) => rec.selectedTypes.includes(id));
        const borderColor = group.key === 'regex'
          ? 'border-[var(--selection-regex-accent)]'
          : group.key === 'llm'
            ? 'border-primary'
            : 'border-[var(--selection-yolo-accent)]';

        return (
          <div key={group.key} data-testid={`playground-text-group-${group.key}`}>
            <div className="mb-1.5 flex items-center justify-between border-b pb-1">
              <span className={cn('border-l-[3px] pl-2 text-[10px] font-semibold', borderColor)}>
                {getTextGroupLabel(group.key, group.label, t)}
              </span>
              <Button variant="ghost" size="sm" className="h-5 px-1 text-[10px]" onClick={() => rec.setPlaygroundTextTypeGroupSelection(ids, !allOn)}>
                {allOn ? t('playground.clear') : t('playground.selectAll')}
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 lg:grid-cols-3">
              {group.types.map((type) => {
                const checked = rec.selectedTypes.includes(type.id);
                return (
                  <label
                    key={`${group.key}-${type.id}`}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-center gap-1 rounded-lg border px-1.5 py-1 text-[10px] leading-tight transition-colors',
                      checked ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent',
                    )}
                    title={type.description || getEntityTypeName(type.id)}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => {
                        rec.clearPlaygroundTextPresetTracking();
                        rec.setSelectedTypes((previous: string[]) => (checked ? previous.filter((id) => id !== type.id) : [...previous, type.id]));
                      }}
                      className="h-3 w-3"
                    />
                    <span className="min-w-0 break-words">{getEntityTypeName(type.id)}</span>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </>
  );
};

const VisionPipelines: FC<{ rec: RecognitionCtx }> = ({ rec }) => {
  const t = useT();

  if (rec.pipelines.length === 0) {
    return <p className="py-8 text-center text-xs text-muted-foreground">{t('playground.loading')}</p>;
  }

  return (
    <>
      {rec.pipelines.map((pipeline) => {
        const isHasImage = pipeline.mode === 'has_image';
        const types = pipeline.types.filter((type) => type.enabled);
        const selectedSet = isHasImage ? rec.selectedHasImageTypes : rec.selectedOcrHasTypes;
        const allSelected = types.length > 0 && types.every((type) => selectedSet.includes(type.id));
        const borderColor = isHasImage ? 'border-[var(--selection-yolo-accent)]' : 'border-primary';

        return (
          <div key={pipeline.mode} data-testid={`playground-pipeline-${pipeline.mode}`}>
            <div className="mb-1.5 flex items-center justify-between border-b pb-1">
              <span className={cn('border-l-[3px] pl-2 text-[10px] font-semibold', borderColor)}>
                {isHasImage ? t('playground.imageFeatures') : t('playground.ocrText')}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 px-1 text-[10px]"
                onClick={() => {
                  rec.clearPlaygroundVisionPresetTracking();
                  const ids = types.map((type) => type.id);
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
            <div className="grid grid-cols-2 gap-1.5 lg:grid-cols-3">
              {types.map((type) => {
                const checked = selectedSet.includes(type.id);
                return (
                  <label
                    key={type.id}
                    className={cn(
                      'flex min-w-0 cursor-pointer items-center gap-1 rounded-lg border px-1.5 py-1 text-[10px] leading-tight transition-colors',
                      checked ? 'border-primary/40 bg-primary/5' : 'border-transparent hover:bg-accent',
                    )}
                    title={type.description || type.name}
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={() => rec.toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                      className="h-3 w-3"
                    />
                    <span className="min-w-0 break-words">{type.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
    </>
  );
};
