import { useCallback, useEffect, useMemo, useState } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { showToast } from '@/components/Toast';
import {
  createPreset,
  deletePreset,
  updatePreset,
  type PresetKind,
  type PresetPayload,
  type RecognitionPreset,
  presetAppliesText,
  presetAppliesVision,
} from '@/services/presetsApi';
import { buildDefaultPipelineTypeIds, buildDefaultTextTypeIds } from '@/services/defaultRedactionPreset';
import {
  getActivePresetTextId,
  getActivePresetVisionId,
  setActivePresetTextId,
  setActivePresetVisionId,
} from '@/services/activePresetBridge';
import {
  selectableCardClass,
  selectableCheckboxClass,
  type SelectionVariant,
} from '@/ui/selectionClasses';
import { getSelectionToneClasses } from '@/ui/selectionPalette';
import { localizeErrorMessage } from '@/utils/localizeError';
import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
  fetchRecognitionPresets,
} from '@/services/recognition-config';
import type { EntityTypeConfig, PipelineConfig } from './hooks/use-entity-types';

const DEFAULT_PRESET_OPTION = '__default__';
const presetMetaPillClass =
  'inline-flex h-7 items-center rounded-full border border-border/70 bg-muted/45 px-2.5 text-[11px] font-medium leading-none text-muted-foreground';
const presetActionButtonClass =
  'h-7 rounded-full border-border/80 bg-background px-3 text-[11px] font-medium leading-none';
const presetDangerButtonClass =
  'h-7 rounded-full border-destructive/25 bg-background px-3 text-[11px] font-medium leading-none text-destructive hover:bg-destructive/8';
const presetPreviewChipClass =
  'inline-flex h-7 w-full items-center rounded-[14px] border border-border/70 bg-background px-2 text-[11px] font-medium leading-none';
const presetPreviewChipGridClass = 'grid grid-cols-3 gap-1.5 xl:grid-cols-4 2xl:grid-cols-5';

function sortPresets(presets: RecognitionPreset[]): RecognitionPreset[] {
  return [...presets].sort((left, right) => {
    const leftTime = left.created_at ? Date.parse(left.created_at) : Number.MAX_SAFE_INTEGER;
    const rightTime = right.created_at ? Date.parse(right.created_at) : Number.MAX_SAFE_INTEGER;
    return (Number.isFinite(leftTime) ? leftTime : Number.MAX_SAFE_INTEGER)
      - (Number.isFinite(rightTime) ? rightTime : Number.MAX_SAFE_INTEGER);
  });
}

export function RedactionList() {
  const t = useT();
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [presets, setPresets] = useState<RecognitionPreset[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingPresetId, setEditingPresetId] = useState<string | null>(null);
  const [presetForm, setPresetForm] = useState<PresetPayload>({
    name: '',
    kind: 'full',
    selectedEntityTypeIds: [],
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
  });
  const [saving, setSaving] = useState(false);
  const [bridgeText, setBridgeText] = useState(() => getActivePresetTextId() ?? '');
  const [bridgeVision, setBridgeVision] = useState(() => getActivePresetVisionId() ?? '');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);

  const presetKindLabel = useCallback((kind?: PresetKind) => {
    if (kind === 'text') return t('settings.redaction.kind.text');
    if (kind === 'vision') return t('settings.redaction.kind.vision');
    return t('settings.redaction.kind.full');
  }, [t]);

  const reloadPresets = useCallback(async () => {
    try {
      setPresets(await fetchRecognitionPresets());
    } catch {
      setPresets([]);
      setLoadError((current) => current ?? t('settings.loadFailed'));
    }
  }, [t]);

  const fetchEntityTypes = useCallback(async () => {
    try {
      setLoading(true);
      setLoadError(null);
      setEntityTypes(await fetchRecognitionEntityTypes(false, 3_500) as EntityTypeConfig[]);
    } catch {
      setEntityTypes([]);
      setLoadError(t('settings.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const fetchPipelines = useCallback(async () => {
    try {
      setLoadError(null);
      setPipelines((await fetchRecognitionPipelines(3_500) as PipelineConfig[]).map((pipeline: PipelineConfig) =>
        pipeline.mode === 'has_image'
          ? { ...pipeline, name: t('settings.pipelineDisplayName.image') }
          : pipeline));
    } catch {
      setPipelines([]);
      setLoadError((current) => current ?? t('settings.loadFailed'));
    }
  }, [t]);

  useEffect(() => {
    void fetchEntityTypes();
    void fetchPipelines();
    void reloadPresets();
  }, [fetchEntityTypes, fetchPipelines, reloadPresets]);

  // Refresh when entity types are changed in the settings entity-type editor
  useEffect(() => {
    const handler = () => { void fetchEntityTypes(); };
    window.addEventListener('entity-types-changed', handler);
    return () => window.removeEventListener('entity-types-changed', handler);
  }, [fetchEntityTypes]);

  const effectiveEntityTypes = entityTypes;
  const effectivePipelines = pipelines;
  const effectivePresets = presets;

  useEffect(() => {
    const syncActivePreset = () => {
      setBridgeText(getActivePresetTextId() ?? '');
      setBridgeVision(getActivePresetVisionId() ?? '');
    };
    window.addEventListener('datainfra-redaction-active-preset', syncActivePreset);
    return () => window.removeEventListener('datainfra-redaction-active-preset', syncActivePreset);
  }, []);

  const textPresets = useMemo(() => sortPresets(effectivePresets.filter(presetAppliesText)), [effectivePresets]);
  const visionPresets = useMemo(() => sortPresets(effectivePresets.filter(presetAppliesVision)), [effectivePresets]);
  const regexTypes = useMemo(
    () => effectiveEntityTypes.filter(type => type.enabled !== false && type.regex_pattern),
    [effectiveEntityTypes],
  );
  const semanticTypes = useMemo(
    () => effectiveEntityTypes.filter(type => type.enabled !== false && type.use_llm && !type.regex_pattern),
    [effectiveEntityTypes],
  );

  const defaultTextPreset = useMemo<RecognitionPreset>(() => ({
    id: '__default_text__',
    name: t('settings.redaction.defaultNameText'),
    kind: 'text',
    selectedEntityTypeIds: buildDefaultTextTypeIds(effectiveEntityTypes),
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
    created_at: '',
    updated_at: '',
  }), [effectiveEntityTypes, t]);

  const defaultVisionPreset = useMemo<RecognitionPreset>(() => ({
    id: '__default_vision__',
    name: t('settings.redaction.defaultNameVision'),
    kind: 'vision',
    selectedEntityTypeIds: [],
    ocrHasTypes: buildDefaultPipelineTypeIds(effectivePipelines, 'ocr_has'),
    hasImageTypes: buildDefaultPipelineTypeIds(effectivePipelines, 'has_image'),
    replacementMode: 'structured',
    created_at: '',
    updated_at: '',
  }), [effectivePipelines, t]);

  const summaryTextLabel = useMemo(() => {
    if (!bridgeText) return t('settings.redaction.defaultShort');
    return textPresets.find(preset => preset.id === bridgeText)?.name ?? t('settings.redaction.defaultShort');
  }, [bridgeText, textPresets, t]);

  const summaryVisionLabel = useMemo(() => {
    if (!bridgeVision) return t('settings.redaction.defaultShort');
    return visionPresets.find(preset => preset.id === bridgeVision)?.name ?? t('settings.redaction.defaultShort');
  }, [bridgeVision, t, visionPresets]);

  useEffect(() => {
    if (bridgeText && !textPresets.some(preset => preset.id === bridgeText)) {
      setBridgeText('');
      setActivePresetTextId(null);
    }
  }, [bridgeText, textPresets]);

  useEffect(() => {
    if (bridgeVision && !visionPresets.some(preset => preset.id === bridgeVision)) {
      setBridgeVision('');
      setActivePresetVisionId(null);
    }
  }, [bridgeVision, visionPresets]);

  const buildDefaultForm = useCallback((kind: PresetKind = 'full'): PresetPayload => {
    const textIds = buildDefaultTextTypeIds(effectiveEntityTypes);
    const ocrIds = buildDefaultPipelineTypeIds(effectivePipelines, 'ocr_has');
    const imageIds = buildDefaultPipelineTypeIds(effectivePipelines, 'has_image');

    if (kind === 'text') {
      return {
        name: '',
        kind: 'text',
        selectedEntityTypeIds: textIds,
        ocrHasTypes: [],
        hasImageTypes: [],
        replacementMode: 'structured',
      };
    }

    if (kind === 'vision') {
      return {
        name: '',
        kind: 'vision',
        selectedEntityTypeIds: [],
        ocrHasTypes: ocrIds,
        hasImageTypes: imageIds,
        replacementMode: 'structured',
      };
    }

    return {
      name: '',
      kind: 'full',
      selectedEntityTypeIds: textIds,
      ocrHasTypes: ocrIds,
      hasImageTypes: imageIds,
      replacementMode: 'structured',
    };
  }, [effectiveEntityTypes, effectivePipelines]);

  const openNew = (kind: PresetKind) => {
    setExpanded(null);
    setEditingPresetId(null);
    setPresetForm(buildDefaultForm(kind));
    setModalOpen(true);
  };

  const openEdit = (preset: RecognitionPreset) => {
    setExpanded(null);
    setEditingPresetId(preset.id);
    setPresetForm({
      name: preset.name,
      kind: preset.kind ?? 'full',
      selectedEntityTypeIds: [...preset.selectedEntityTypeIds],
      ocrHasTypes: [...preset.ocrHasTypes],
      hasImageTypes: [...preset.hasImageTypes],
      replacementMode: preset.replacementMode,
    });
    setModalOpen(true);
  };

  const saveModal = async () => {
    if (!presetForm.name.trim()) {
      showToast(t('settings.redaction.nameRequired'), 'error');
      return;
    }

    const normalized: PresetPayload = presetForm.kind === 'text'
      ? { ...presetForm, ocrHasTypes: [], hasImageTypes: [], replacementMode: 'structured' }
      : presetForm.kind === 'vision'
        ? { ...presetForm, selectedEntityTypeIds: [], replacementMode: 'structured' }
        : presetForm;

    setSaving(true);
    try {
      if (editingPresetId) {
        await updatePreset(editingPresetId, normalized);
      } else {
        const created = await createPreset(normalized);
        if (normalized.kind === 'text' || normalized.kind === 'full') {
          setActivePresetTextId(created.id);
          setBridgeText(created.id);
        }
        if (normalized.kind === 'vision' || normalized.kind === 'full') {
          setActivePresetVisionId(created.id);
          setBridgeVision(created.id);
        }
      }
      setModalOpen(false);
      await reloadPresets();
    } catch (error) {
      showToast(localizeErrorMessage(error, 'settings.redaction.saveFailed'), 'error');
    } finally {
      setSaving(false);
    }
  };

  const removePreset = async (id: string) => {
    try {
      await deletePreset(id);
      setExpanded(current => (current === `text:${id}` || current === `vision:${id}` ? null : current));
      await reloadPresets();
      if (bridgeText === id) {
        setBridgeText('');
        setActivePresetTextId(null);
      }
      if (bridgeVision === id) {
        setBridgeVision('');
        setActivePresetVisionId(null);
      }
    } catch (error) {
      showToast(localizeErrorMessage(error, 'settings.deleteTypeFailed'), 'error');
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
          <Card className="overflow-hidden">
            <CardHeader className="pb-3">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-80 max-w-full" />
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <Skeleton className="h-20 w-full rounded-xl" />
              <div className="grid gap-2 md:grid-cols-2">
                <Skeleton className="h-16 w-full rounded-xl" />
                <Skeleton className="h-16 w-full rounded-xl" />
              </div>
              <div className="grid gap-2 md:grid-cols-2">
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
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,1920px)] !px-3 !py-2 sm:!px-4 sm:!py-3">
        {loadError && (
          <Alert variant="destructive">
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        )}

        <Card className="page-surface overflow-hidden">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="text-sm">{t('settings.redaction.configTitle')}</CardTitle>
                <CardDescription className="mt-0.5 text-xs">
                  {t('settings.redaction.configDesc')}
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" onClick={() => openNew('text')} data-testid="new-text-preset">
                  {t('settings.redaction.newText')}
                </Button>
                <Button size="sm" variant="outline" onClick={() => openNew('vision')} data-testid="new-vision-preset">
                  {t('settings.redaction.newVision')}
                </Button>
              </div>
            </div>
          </CardHeader>

          <CardContent className="page-surface-body flex flex-col gap-4 p-6">
            <div className="rounded-lg border bg-muted/30 px-3 py-2 text-xs">
              <p className="mb-1 text-[0.65rem] font-semibold uppercase tracking-wide text-muted-foreground">
                {t('settings.redaction.currentSelection')}
              </p>
              <p>
                <span className="text-muted-foreground">{t('settings.redaction.currentText')}</span>
                <span className="font-medium">{summaryTextLabel}</span>
              </p>
              <p className="mt-0.5">
                <span className="text-muted-foreground">{t('settings.redaction.currentVision')}</span>
                <span className="font-medium">{summaryVisionLabel}</span>
              </p>
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs">{t('settings.redaction.linkText')}</Label>
                <Select
                  value={bridgeText || DEFAULT_PRESET_OPTION}
                  onValueChange={(value) => {
                    const nextValue = value === DEFAULT_PRESET_OPTION ? '' : value;
                    setBridgeText(nextValue);
                    setActivePresetTextId(nextValue || null);
                  }}
                >
                  <SelectTrigger className="h-8 rounded-lg text-xs" data-testid="bridge-text-select">
                    <SelectValue placeholder={t('settings.redaction.defaultOption')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value={DEFAULT_PRESET_OPTION}>{t('settings.redaction.defaultOption')}</SelectItem>
                      {textPresets.map((preset) => (
                        <SelectItem key={preset.id} value={preset.id}>
                          {preset.name}
                          {preset.kind === 'full' ? ` (${t('settings.redaction.kind.full')})` : ''}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <Label className="text-xs">{t('settings.redaction.linkVision')}</Label>
                <Select
                  value={bridgeVision || DEFAULT_PRESET_OPTION}
                  onValueChange={(value) => {
                    const nextValue = value === DEFAULT_PRESET_OPTION ? '' : value;
                    setBridgeVision(nextValue);
                    setActivePresetVisionId(nextValue || null);
                  }}
                >
                  <SelectTrigger className="h-8 rounded-lg text-xs" data-testid="bridge-vision-select">
                    <SelectValue placeholder={t('settings.redaction.defaultOption')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value={DEFAULT_PRESET_OPTION}>{t('settings.redaction.defaultOption')}</SelectItem>
                      {visionPresets.map((preset) => (
                        <SelectItem key={preset.id} value={preset.id}>
                          {preset.name}
                          {preset.kind === 'full' ? ` (${t('settings.redaction.kind.full')})` : ''}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              <PresetColumn
                title={t('settings.redaction.textColumn')}
                defaultPreset={defaultTextPreset}
                presets={textPresets}
                entityTypes={effectiveEntityTypes}
                pipelines={effectivePipelines}
                expanded={expanded}
                setExpanded={setExpanded}
                colPrefix="text"
                onEdit={openEdit}
                    onDelete={(id) => setConfirmState({
                      title: t('common.delete'),
                      message: t('settings.redaction.confirmDelete'),
                      danger: true,
                      onConfirm: () => void removePreset(id),
                    })}
              />
              <PresetColumn
                title={t('settings.redaction.visionColumn')}
                defaultPreset={defaultVisionPreset}
                presets={visionPresets}
                entityTypes={effectiveEntityTypes}
                pipelines={effectivePipelines}
                expanded={expanded}
                setExpanded={setExpanded}
                colPrefix="vision"
                onEdit={openEdit}
                    onDelete={(id) => setConfirmState({
                      title: t('common.delete'),
                      message: t('settings.redaction.confirmDelete'),
                      danger: true,
                      onConfirm: () => void removePreset(id),
                    })}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {modalOpen && (
        <Dialog open={modalOpen} onOpenChange={setModalOpen}>
          <DialogContent className="flex max-h-[90vh] w-[90vw] max-w-3xl flex-col overflow-hidden">
            <DialogHeader>
              <DialogTitle>
                {editingPresetId
                  ? t('settings.redaction.editTitle').replace('{kind}', presetKindLabel(presetForm.kind))
                  : t('settings.redaction.createTitle').replace('{kind}', presetKindLabel(presetForm.kind))}
              </DialogTitle>
              <DialogDescription>{t('settings.redaction.dialogDesc')}</DialogDescription>
            </DialogHeader>

            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="space-y-5 py-2">
                <div className="max-w-sm space-y-1.5">
                  <Label>{t('settings.redaction.nameLabel')} *</Label>
                  <Input
                    value={presetForm.name}
                    onChange={e => setPresetForm(current => ({ ...current, name: e.target.value }))}
                    placeholder={t('settings.redaction.namePlaceholder')}
                    data-testid="preset-name"
                  />
                </div>

                {(presetForm.kind === 'text' || presetForm.kind === 'full') && (
                  <>
                    <TypeCheckboxGrid
                      title={t('settings.redaction.regexGroup')}
                      types={regexTypes}
                      selectedIds={presetForm.selectedEntityTypeIds}
                      onToggle={id => setPresetForm(current => ({
                        ...current,
                        selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                          ? current.selectedEntityTypeIds.filter(item => item !== id)
                          : [...current.selectedEntityTypeIds, id],
                      }))}
                      variant="regex"
                    />
                    <TypeCheckboxGrid
                      title={t('settings.redaction.semanticGroup')}
                      types={semanticTypes}
                      selectedIds={presetForm.selectedEntityTypeIds}
                      onToggle={id => setPresetForm(current => ({
                        ...current,
                        selectedEntityTypeIds: current.selectedEntityTypeIds.includes(id)
                          ? current.selectedEntityTypeIds.filter(item => item !== id)
                          : [...current.selectedEntityTypeIds, id],
                      }))}
                      variant="semantic"
                    />
                  </>
                )}

                {(presetForm.kind === 'vision' || presetForm.kind === 'full') &&
                  effectivePipelines.filter(pipeline => pipeline.enabled).map(pipeline => (
                    <PipelineCheckboxGrid
                      key={pipeline.mode}
                      pipeline={pipeline}
                      selectedOcr={presetForm.ocrHasTypes}
                      selectedImg={presetForm.hasImageTypes}
                      onToggle={(mode, id) => setPresetForm(current => {
                        if (mode === 'ocr_has') {
                          const next = current.ocrHasTypes.includes(id)
                            ? current.ocrHasTypes.filter(item => item !== id)
                            : [...current.ocrHasTypes, id];
                          return { ...current, ocrHasTypes: next };
                        }

                        const next = current.hasImageTypes.includes(id)
                          ? current.hasImageTypes.filter(item => item !== id)
                          : [...current.hasImageTypes, id];
                        return { ...current, hasImageTypes: next };
                      })}
                    />
                  ))}
              </div>
            </div>

            <DialogFooter className="border-t pt-4">
              <Button variant="outline" onClick={() => setModalOpen(false)} data-testid="preset-cancel">
                {t('settings.cancel')}
              </Button>
              <Button disabled={saving} onClick={() => void saveModal()} data-testid="preset-save">
                {saving ? t('settings.redaction.processing') : (editingPresetId ? t('settings.save') : t('settings.create'))}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {confirmState && (
        <ConfirmDialog
          open
          title={confirmState.title}
          message={confirmState.message}
          danger={confirmState.danger}
          onConfirm={() => {
            confirmState.onConfirm();
            setConfirmState(null);
          }}
          onCancel={() => setConfirmState(null)}
        />
      )}
    </div>
  );
}

function PresetColumn({
  title,
  defaultPreset,
  presets,
  entityTypes,
  pipelines,
  expanded,
  setExpanded,
  colPrefix,
  onEdit,
  onDelete,
}: {
  title: string;
  defaultPreset: RecognitionPreset;
  presets: RecognitionPreset[];
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
  expanded: string | null;
  setExpanded: React.Dispatch<React.SetStateAction<string | null>>;
  colPrefix: string;
  onEdit: (preset: RecognitionPreset) => void;
  onDelete: (id: string) => void;
}) {
  const t = useT();
  const defaultKey = `${colPrefix}:__default__`;

  return (
    <div className="flex min-h-0 flex-col">
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <ul className="max-h-[min(55vh,520px)] divide-y divide-border overflow-y-auto rounded-md border text-xs">
        <li className="bg-muted/30">
          <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{defaultPreset.name}</span>
              <Badge variant="secondary" className={presetMetaPillClass}>
                {t('settings.redaction.systemDefault')}
              </Badge>
            </div>
            <Button
              size="sm"
              variant="outline"
              className={presetActionButtonClass}
              onClick={() => setExpanded(current => current === defaultKey ? null : defaultKey)}
            >
              {expanded === defaultKey ? t('settings.redaction.collapse') : t('settings.redaction.preview')}
            </Button>
          </div>
          {expanded === defaultKey && (
            <PresetPreview preset={defaultPreset} entityTypes={entityTypes} pipelines={pipelines} />
          )}
        </li>

        {presets.map(preset => {
          const rowKey = `${colPrefix}:${preset.id}`;
          return (
            <li key={preset.id} className="bg-muted/30">
              <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1.5">
                <span className="font-medium">{preset.name}</span>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className={presetActionButtonClass}
                    onClick={() => setExpanded(current => current === rowKey ? null : rowKey)}
                  >
                    {expanded === rowKey ? t('settings.redaction.collapse') : t('settings.redaction.preview')}
                  </Button>
                  <Button size="sm" variant="outline" className={presetActionButtonClass} onClick={() => onEdit(preset)}>
                    {t('settings.redaction.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className={presetDangerButtonClass}
                    onClick={() => void onDelete(preset.id)}
                  >
                    {t('settings.redaction.delete')}
                  </Button>
                </div>
              </div>
              {expanded === rowKey && (
                <PresetPreview preset={preset} entityTypes={entityTypes} pipelines={pipelines} />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function PresetPreview({
  preset,
  entityTypes,
  pipelines,
}: {
  preset: RecognitionPreset;
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
}) {
  const t = useT();
  const ocrPipeline = pipelines.find(pipeline => pipeline.mode === 'ocr_has');
  const imagePipeline = pipelines.find(pipeline => pipeline.mode === 'has_image');

  const selectedRegexTypes = useMemo(
    () => preset.selectedEntityTypeIds.filter(id => entityTypes.find(type => type.id === id)?.regex_pattern),
    [preset.selectedEntityTypeIds, entityTypes],
  );
  const selectedSemanticTypes = useMemo(
    () => preset.selectedEntityTypeIds.filter(id => {
      const et = entityTypes.find(type => type.id === id);
      return et && et.use_llm && !et.regex_pattern;
    }),
    [preset.selectedEntityTypeIds, entityTypes],
  );

  return (
    <div className="space-y-2 border-t px-2 pb-3 pt-2">
      {presetAppliesText(preset) && selectedRegexTypes.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
            {t('settings.redaction.regexGroup')} ({selectedRegexTypes.length})
          </p>
          <div className={presetPreviewChipGridClass}>
            {selectedRegexTypes.map(id => (
              <span
                key={id}
                className={cn(presetPreviewChipClass, 'truncate')}
                title={entityTypes.find(type => type.id === id)?.name ?? id}
              >
                {entityTypes.find(type => type.id === id)?.name ?? id}
              </span>
            ))}
          </div>
        </div>
      )}

      {presetAppliesText(preset) && selectedSemanticTypes.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
            {t('settings.redaction.semanticGroup')} ({selectedSemanticTypes.length})
          </p>
          <div className={presetPreviewChipGridClass}>
            {selectedSemanticTypes.map(id => (
              <span
                key={id}
                className={cn(presetPreviewChipClass, 'truncate')}
                title={entityTypes.find(type => type.id === id)?.name ?? id}
              >
                {entityTypes.find(type => type.id === id)?.name ?? id}
              </span>
            ))}
          </div>
        </div>
      )}

      {presetAppliesVision(preset) && (
        <>
          {preset.ocrHasTypes.length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
                {t('settings.redaction.ocrGroup')} ({preset.ocrHasTypes.length})
              </p>
              <div className={presetPreviewChipGridClass}>
                {preset.ocrHasTypes.map(id => (
                  <span
                    key={id}
                    className={cn(presetPreviewChipClass, 'truncate')}
                    title={ocrPipeline?.types.find(type => type.id === id)?.name ?? id}
                  >
                    {ocrPipeline?.types.find(type => type.id === id)?.name ?? id}
                  </span>
                ))}
              </div>
            </div>
          )}
          {preset.hasImageTypes.length > 0 && (
            <div>
              <p className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">
                {t('settings.redaction.imageGroup')} ({preset.hasImageTypes.length})
              </p>
              <div className={presetPreviewChipGridClass}>
                {preset.hasImageTypes.map(id => (
                  <span
                    key={id}
                    className={cn(presetPreviewChipClass, 'truncate')}
                    title={imagePipeline?.types.find(type => type.id === id)?.name ?? id}
                  >
                    {imagePipeline?.types.find(type => type.id === id)?.name ?? id}
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TypeCheckboxGrid({
  title,
  types,
  selectedIds,
  onToggle,
  variant,
}: {
  title: string;
  types: EntityTypeConfig[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  variant: SelectionVariant;
}) {
  return (
    <div>
      <p className="mb-2 border-l-[3px] border-muted-foreground/30 pl-2 text-sm font-semibold">
        {title} <span className="text-xs text-muted-foreground">({types.length})</span>
      </p>
      <div className="grid grid-cols-2 gap-2 rounded-xl border bg-muted/20 p-3 sm:grid-cols-3 md:grid-cols-4">
        {types.map(type => {
          const checked = selectedIds.includes(type.id);
          return (
            <label
              key={type.id}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors',
                selectableCardClass(checked, variant),
              )}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(type.id)}
                className={cn('shrink-0', selectableCheckboxClass(variant, 'md'))}
              />
              <span className="min-w-0 break-words">{type.name}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function PipelineCheckboxGrid({
  pipeline,
  selectedOcr,
  selectedImg,
  onToggle,
}: {
  pipeline: PipelineConfig;
  selectedOcr: string[];
  selectedImg: string[];
  onToggle: (mode: string, id: string) => void;
}) {
  const t = useT();
  const variant: SelectionVariant = pipeline.mode === 'ocr_has' ? 'semantic' : 'visual';
  const toneClasses = getSelectionToneClasses(variant);
  const selectedIds = pipeline.mode === 'ocr_has' ? selectedOcr : selectedImg;

  return (
    <div>
      <p
        className={cn(
          'mb-2 border-l-[3px] pl-2 text-sm font-semibold',
          toneClasses.dot,
        )}
      >
        {pipeline.mode === 'ocr_has' ? t('settings.redaction.ocrGroup') : t('settings.redaction.imageGroup')}
      </p>
      <div className="grid grid-cols-2 gap-2 rounded-xl border bg-muted/20 p-3 sm:grid-cols-3 md:grid-cols-4">
        {pipeline.types.filter(type => type.enabled).map(type => {
          const active = selectedIds.includes(type.id);
          return (
            <label
              key={type.id}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition-colors',
                selectableCardClass(active, variant),
              )}
            >
              <input
                type="checkbox"
                checked={active}
                onChange={() => onToggle(pipeline.mode, type.id)}
                className={cn('shrink-0', selectableCheckboxClass(variant, 'md'))}
              />
              <span className="min-w-0 break-words">{type.name}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
