// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useMemo, useRef, useState, type SetStateAction } from 'react';
import {
  createPreset,
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '@/services/presetsApi';
import { usePresets, useInvalidatePresets } from '@/services/hooks/use-presets';
import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
} from '@/services/recognition-config';
import {
  buildDefaultPipelineTypeIds,
  buildDefaultTextTypeIds,
} from '@/services/defaultRedactionPreset';
import {
  buildVisionSelectionSignature,
  getCachedRecognitionConfig,
  updateRecognitionConfigCache,
} from '../lib/recognition-config';
import {
  setActivePresetTextId,
  setActivePresetVisionId,
  getActivePresetTextId,
  getActivePresetVisionId,
} from '@/services/activePresetBridge';
import { t, useI18n } from '@/i18n';
import { STORAGE_KEYS } from '@/constants/storage-keys';
import { getScopedStorageItem, setScopedStorageItem } from '@/lib/storage';
import { useAuth } from '@/features/auth/auth-context';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import { localizePresetName } from '@/features/settings/lib/redaction-display';
import {
  buildPlaygroundTextGroups,
  type ConfigLoadState,
  flattenVisionTypes,
  normalizeVisionPipelines,
  sortEntityTypes,
} from '../lib/recognition-config';
import type { EntityTypeConfig, VisionTypeConfig, PipelineConfig } from '../types';

// 与批量向导(use-batch-config 25s)对齐：目录接口经远程隧道单程可达数百毫秒，
// 1.2s 会间歇性 abort → 单文件页"暂时无法加载识别项"。快在缓存，不靠掐超时。
const RECOGNITION_FETCH_TIMEOUT_MS = 25_000;

function uniqueIds(ids: string[]): string[] {
  return Array.from(new Set(ids));
}

function resolveVisionSelectionsFromStorage(pipelines: PipelineConfig[], ownerId?: string | null) {
  const ocrHasTypeIds = pipelines
    .filter((pipeline) => pipeline.mode === 'ocr_has')
    .flatMap((pipeline) => pipeline.types.map((type) => type.id));
  const defaultOcrHasTypeIds = buildDefaultPipelineTypeIds(pipelines, 'ocr_has');
  const visualFeatureTypeIds = pipelines
    .filter((pipeline) => pipeline.mode === 'visual_features')
    .flatMap((pipeline) => pipeline.types.map((type) => type.id));
  const defaultVisualFeatureTypeIds = buildDefaultPipelineTypeIds(pipelines, 'visual_features');

  const visionSelectionSignature = buildVisionSelectionSignature(pipelines);
  const savedOcrHasTypes = getScopedStorageItem<string[] | null>(STORAGE_KEYS.OCR_HAS_TYPES, null, ownerId);
  const savedVisualFeatureTypes = getScopedStorageItem<string[] | null>(
    STORAGE_KEYS.VISUAL_FEATURE_TYPES,
    null,
    ownerId,
  );
  const savedVisionSelectionSignature = getScopedStorageItem<string | null>(
    STORAGE_KEYS.VISION_SELECTION_SIGNATURE,
    null,
    ownerId,
  );
  const canUseSavedVisionSelection = savedVisionSelectionSignature === visionSelectionSignature;

  const ocrHasTypes = canUseSavedVisionSelection && Array.isArray(savedOcrHasTypes)
    ? (() => {
        const filtered = savedOcrHasTypes.filter((id: string) => ocrHasTypeIds.includes(id));
        return filtered.length > 0 || savedOcrHasTypes.length === 0
          ? filtered
          : defaultOcrHasTypeIds;
      })()
    : defaultOcrHasTypeIds;

  const visualFeatureTypes = canUseSavedVisionSelection && Array.isArray(savedVisualFeatureTypes)
    ? (() => {
        const filtered = uniqueIds(savedVisualFeatureTypes).filter((id: string) =>
          visualFeatureTypeIds.includes(id),
        );
        return filtered.length > 0 || savedVisualFeatureTypes.length === 0
          ? filtered
          : defaultVisualFeatureTypeIds;
      })()
    : defaultVisualFeatureTypeIds;

  return {
    ocrHasTypes,
    visualFeatureTypes,
    visionSelectionSignature,
  };
}

export function usePlaygroundRecognition() {
  const locale = useI18n((state) => state.locale);
  const { status } = useAuth();
  const ownerKey = status?.authenticated && status.username ? status.username.toLowerCase() : 'anonymous';
  const presetsQuery = usePresets();
  const invalidatePresets = useInvalidatePresets();

  const cachedConfig = getCachedRecognitionConfig(ownerKey);
  const cachedEntityTypes = cachedConfig ? sortEntityTypes(cachedConfig.entityTypes) : [];
  const cachedPipelines = cachedConfig
    ? normalizeVisionPipelines(cachedConfig.pipelines as PipelineConfig[])
    : [];
  const cachedVisionSelections = resolveVisionSelectionsFromStorage(cachedPipelines, ownerKey);

  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>(cachedEntityTypes);
  const [textConfigState, setTextConfigState] = useState<ConfigLoadState>(cachedEntityTypes.length > 0 ? 'ready' : 'loading');
  const entityConfigLoadedRef = useRef(cachedEntityTypes.length > 0);
  const initialSelectedTypes = buildDefaultTextTypeIds(cachedEntityTypes);
  const [selectedTypes, setSelectedTypesState] = useState<string[]>(initialSelectedTypes);
  const selectedTypesRef = useRef<string[]>(initialSelectedTypes);
  const setSelectedTypes = useCallback((next: SetStateAction<string[]>) => {
    const base = selectedTypesRef.current;
    const resolved = typeof next === 'function' ? next(base) : next;
    selectedTypesRef.current = resolved;
    setSelectedTypesState(resolved);
  }, []);
  const [visionTypes, setVisionTypes] = useState<VisionTypeConfig[]>(() => flattenVisionTypes(cachedPipelines));
  const [visionConfigState, setVisionConfigState] = useState<ConfigLoadState>(
    cachedPipelines.length > 0 ? 'ready' : 'loading',
  );
  const visionConfigLoadedRef = useRef(cachedPipelines.length > 0);
  const [selectedOcrHasTypes, setSelectedOcrHasTypes] = useState<string[]>(() => [
    ...cachedVisionSelections.ocrHasTypes,
  ]);
  const [selectedVisualFeatureTypes, setSelectedVisualFeatureTypes] = useState<string[]>(() => [
    ...cachedVisionSelections.visualFeatureTypes,
  ]);
  const selectedOcrHasTypesRef = useRef(selectedOcrHasTypes);
  const selectedVisualFeatureTypesRef = useRef(selectedVisualFeatureTypes);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>(cachedPipelines);
  const [typeTab, setTypeTab] = useState<'text' | 'vision'>('text');
  const [replacementMode, setReplacementMode] = useState<'structured' | 'smart' | 'mask'>(
    'structured',
  );
  const [playgroundPresets, setPlaygroundPresets] = useState<RecognitionPreset[]>([]);
  const [playgroundPresetTextId, setPlaygroundPresetTextId] = useState<string | null>(null);
  const [playgroundPresetVisionId, setPlaygroundPresetVisionId] = useState<string | null>(null);
  const [presetDialogKind, setPresetDialogKind] = useState<'text' | 'vision' | null>(null);
  const [presetDialogName, setPresetDialogName] = useState('');
  const [presetSaving, setPresetSaving] = useState(false);
  const [presetApplySeq, setPresetApplySeq] = useState(0);

  useEffect(() => {
    selectedTypesRef.current = selectedTypes;
  }, [selectedTypes]);

  const localizedPlaygroundPresets = useMemo(
    () => {
      void locale;
      return playgroundPresets.map((preset) => ({
        ...preset,
        name: localizePresetName(preset, t),
      }));
    },
    [playgroundPresets, locale],
  );

  const textPresetsPg = useMemo(
    () => localizedPlaygroundPresets.filter(presetAppliesText),
    [localizedPlaygroundPresets],
  );
  const visionPresetsPg = useMemo(
    () => localizedPlaygroundPresets.filter(presetAppliesVision),
    [localizedPlaygroundPresets],
  );

  const playgroundDefaultTextTypeIds = useMemo(
    () => buildDefaultTextTypeIds(entityTypes),
    [entityTypes],
  );
  const playgroundDefaultOcrHasTypeIds = useMemo(
    () => buildDefaultPipelineTypeIds(pipelines, 'ocr_has'),
    [pipelines],
  );
  const playgroundDefaultVisualFeatureTypeIds = useMemo(
    () => buildDefaultPipelineTypeIds(pipelines, 'visual_features'),
    [pipelines],
  );

  const updateOcrHasTypes = useCallback((types: string[]) => {
    selectedOcrHasTypesRef.current = types;
    setSelectedOcrHasTypes(types);
    setScopedStorageItem(STORAGE_KEYS.OCR_HAS_TYPES, types, ownerKey);
  }, [ownerKey]);

  const updateVisualFeatureTypes = useCallback((types: string[]) => {
    const uniqueTypes = uniqueIds(types);
    selectedVisualFeatureTypesRef.current = uniqueTypes;
    setSelectedVisualFeatureTypes(uniqueTypes);
    setScopedStorageItem(STORAGE_KEYS.VISUAL_FEATURE_TYPES, uniqueTypes, ownerKey);
  }, [ownerKey]);

  const clearPlaygroundTextPresetTracking = useCallback(() => {
    setPlaygroundPresetTextId(null);
    setActivePresetTextId(null);
  }, []);

  const clearPlaygroundVisionPresetTracking = useCallback(() => {
    setPlaygroundPresetVisionId(null);
    setActivePresetVisionId(null);
  }, []);

  const applyTextPresetToPlayground = useCallback(
    (preset: RecognitionPreset) => {
      if (!presetAppliesText(preset)) return;
      const enabledTextIds = new Set(
        entityTypes.filter((type) => type.enabled !== false).map((type) => type.id),
      );
      setSelectedTypes(preset.selectedEntityTypeIds.filter((id) => enabledTextIds.has(id)));
      if ((preset.kind ?? 'full') !== 'text') {
        setReplacementMode(preset.replacementMode);
      }
      setPlaygroundPresetTextId(preset.id);
      setActivePresetTextId(preset.id);
      setPresetApplySeq((s) => s + 1);
    },
    [entityTypes, setSelectedTypes],
  );

  const applyVisionPresetToPlayground = useCallback(
    (preset: RecognitionPreset) => {
      if (!presetAppliesVision(preset)) return;
      const hasLoadedPipelines = pipelines.length > 0;
      const ocrIds = hasLoadedPipelines
        ? pipelines
            .filter((pipeline) => pipeline.mode === 'ocr_has')
            .flatMap((pipeline) => pipeline.types.map((type) => type.id))
        : null;
      const imageIds = hasLoadedPipelines
        ? pipelines
            .filter((pipeline) => pipeline.mode === 'visual_features')
            .flatMap((pipeline) => pipeline.types.map((type) => type.id))
        : null;

      updateOcrHasTypes(
        hasLoadedPipelines
          ? preset.ocrHasTypes.filter((id) => ocrIds?.includes(id))
          : [...preset.ocrHasTypes],
      );
      updateVisualFeatureTypes(
        hasLoadedPipelines
          ? uniqueIds(preset.visualFeatureTypes ?? []).filter((id) => imageIds?.includes(id))
          : uniqueIds(preset.visualFeatureTypes ?? []),
      );
      setPlaygroundPresetVisionId(preset.id);
      setActivePresetVisionId(preset.id);
      setPresetApplySeq((s) => s + 1);
    },
    [pipelines, updateOcrHasTypes, updateVisualFeatureTypes],
  );

  const selectPlaygroundTextPresetById = useCallback(
    (id: string) => {
      if (!id) {
        setPlaygroundPresetTextId(null);
        setActivePresetTextId(null);
        setSelectedTypes([...playgroundDefaultTextTypeIds]);
        setReplacementMode('structured');
        setPresetApplySeq((s) => s + 1);
        return;
      }

      const preset = playgroundPresets.find((item) => item.id === id);
      if (preset) applyTextPresetToPlayground(preset);
    },
    [playgroundDefaultTextTypeIds, playgroundPresets, applyTextPresetToPlayground, setSelectedTypes],
  );

  const selectPlaygroundVisionPresetById = useCallback(
    (id: string) => {
      if (!id) {
        setPlaygroundPresetVisionId(null);
        setActivePresetVisionId(null);
        updateOcrHasTypes([...playgroundDefaultOcrHasTypeIds]);
        updateVisualFeatureTypes([...playgroundDefaultVisualFeatureTypeIds]);
        setPresetApplySeq((s) => s + 1);
        return;
      }

      const preset = playgroundPresets.find((item) => item.id === id);
      if (preset) applyVisionPresetToPlayground(preset);
    },
    [
      playgroundDefaultOcrHasTypeIds,
      playgroundDefaultVisualFeatureTypeIds,
      playgroundPresets,
      applyVisionPresetToPlayground,
      updateOcrHasTypes,
      updateVisualFeatureTypes,
    ],
  );

  // Sync presets from react-query cache into local state
  useEffect(() => {
    setPlaygroundPresets(presetsQuery.data ?? []);
  }, [presetsQuery.data]);

  const closePresetDialog = useCallback(() => {
    if (presetSaving) return;
    setPresetDialogKind(null);
    setPresetDialogName('');
  }, [presetSaving]);

  const openTextPresetDialog = useCallback(() => {
    setPresetDialogKind('text');
    setPresetDialogName('');
  }, []);

  const openVisionPresetDialog = useCallback(() => {
    setPresetDialogKind('vision');
    setPresetDialogName('');
  }, []);

  const saveTextPresetFromPlayground = useCallback(async () => {
    const name = presetDialogName.trim();
    if (!name) {
      showToast(t('settings.redaction.nameRequired'), 'error');
      return;
    }

    setPresetSaving(true);
    try {
      const created = await createPreset({
        name,
        kind: 'text',
        selectedEntityTypeIds: selectedTypes,
        ocrHasTypes: [],
        visualFeatureTypes: [],
        replacementMode: 'structured',
      });
      await invalidatePresets();
      setPlaygroundPresetTextId(created.id);
      setActivePresetTextId(created.id);
      closePresetDialog();
      showToast(t('preset.saveText.success'), 'success');
    } catch (error) {
      showToast(localizeErrorMessage(error, 'preset.save.failed'), 'error');
    } finally {
      setPresetSaving(false);
    }
  }, [closePresetDialog, presetDialogName, selectedTypes, invalidatePresets]);

  const saveVisionPresetFromPlayground = useCallback(async () => {
    const name = presetDialogName.trim();
    if (!name) {
      showToast(t('settings.redaction.nameRequired'), 'error');
      return;
    }

    setPresetSaving(true);
    try {
      // Option B:视觉预设的文本通道(ocrHasTypes)= 共享语义选择(过滤 regex),
      // 与行业预设 ocrHasTypes=selectedEntityTypeIds 同口径,保证图像文本检出可用。
      const sharedTextTypes = selectedTypes.filter((id) => {
        const ty = entityTypes.find((type) => type.id === id);
        return ty ? !ty.regex_pattern : true;
      });
      const created = await createPreset({
        name,
        kind: 'vision',
        selectedEntityTypeIds: [],
        ocrHasTypes: sharedTextTypes,
        visualFeatureTypes: uniqueIds(selectedVisualFeatureTypes),
        replacementMode: 'structured',
      });
      await invalidatePresets();
      setPlaygroundPresetVisionId(created.id);
      setActivePresetVisionId(created.id);
      closePresetDialog();
      showToast(t('preset.saveVision.success'), 'success');
    } catch (error) {
      showToast(localizeErrorMessage(error, 'preset.save.failed'), 'error');
    } finally {
      setPresetSaving(false);
    }
  }, [
    closePresetDialog,
    presetDialogName,
    selectedVisualFeatureTypes,
    selectedTypes,
    entityTypes,
    invalidatePresets,
  ]);

  const fetchEntityTypes = useCallback(
    async (preserveSelection = false) => {
      try {
        const types = sortEntityTypes(await fetchRecognitionEntityTypes(true, RECOGNITION_FETCH_TIMEOUT_MS));
        const defaultTypeIds = buildDefaultTextTypeIds(types);
        const validTypeIds = new Set(types.map((type) => type.id));
        const hadLoaded = entityConfigLoadedRef.current;

        setEntityTypes(types);
        entityConfigLoadedRef.current = types.length > 0;
        setTextConfigState(types.length > 0 ? 'ready' : 'empty');
        setSelectedTypes((previous) => {
          if (!preserveSelection || !hadLoaded) return defaultTypeIds;
          const filtered = previous.filter((id) => validTypeIds.has(id));
          return filtered.length > 0 || previous.length === 0 ? filtered : defaultTypeIds;
        });
        updateRecognitionConfigCache({ entityTypes: types }, ownerKey);
      } catch (error) {
        if (import.meta.env.DEV) console.error('fetch entity types failed', error);
        if (!entityConfigLoadedRef.current) {
          setTextConfigState('unavailable');
        }
      }
    },
    [ownerKey, setSelectedTypes],
  );

  const fetchVisionTypes = useCallback(async () => {
    try {
      const normalizedPipelines = normalizeVisionPipelines(
        (await fetchRecognitionPipelines(RECOGNITION_FETCH_TIMEOUT_MS)) as PipelineConfig[],
      );
      const nextVisionSelections = resolveVisionSelectionsFromStorage(normalizedPipelines, ownerKey);
      const nextVisionTypes = flattenVisionTypes(normalizedPipelines);

      setPipelines(normalizedPipelines);
      setVisionTypes(nextVisionTypes);
      visionConfigLoadedRef.current = normalizedPipelines.length > 0;
      setVisionConfigState(normalizedPipelines.length > 0 ? 'ready' : 'empty');
      updateOcrHasTypes(nextVisionSelections.ocrHasTypes);
      updateVisualFeatureTypes(nextVisionSelections.visualFeatureTypes);
      setScopedStorageItem(
        STORAGE_KEYS.VISION_SELECTION_SIGNATURE,
        nextVisionSelections.visionSelectionSignature,
        ownerKey,
      );
      updateRecognitionConfigCache({ pipelines: normalizedPipelines }, ownerKey);
    } catch (error) {
      if (import.meta.env.DEV) console.error('fetch vision pipelines failed', error);
      if (!visionConfigLoadedRef.current) {
        setVisionConfigState('unavailable');
      }
    }
  }, [ownerKey, updateOcrHasTypes, updateVisualFeatureTypes]);

  const loadRecognitionConfig = useCallback(
    async (preserveSelection = false) => {
      await Promise.allSettled([fetchEntityTypes(preserveSelection), fetchVisionTypes()]);
    },
    [fetchEntityTypes, fetchVisionTypes],
  );

  useEffect(() => {
    void loadRecognitionConfig(false);
  }, [loadRecognitionConfig]);

  useEffect(() => {
    const handleFocus = () => {
      void loadRecognitionConfig(true);
    };

    window.addEventListener('focus', handleFocus);
    const handleEntityTypesChanged = () => fetchEntityTypes(true);
    window.addEventListener('entity-types-changed', handleEntityTypesChanged);
    return () => {
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('entity-types-changed', handleEntityTypesChanged);
    };
  }, [fetchEntityTypes, loadRecognitionConfig]);

  const bridgeInitRef = useRef(false);
  useEffect(() => {
    bridgeInitRef.current = false;
  }, [ownerKey]);

  useEffect(() => {
    if (bridgeInitRef.current) return;
    if (!playgroundPresets.length || !entityTypes.length) return;

    const textPresetId = getActivePresetTextId();
    if (textPresetId) {
      const preset = playgroundPresets.find(
        (item) => item.id === textPresetId && presetAppliesText(item),
      );
      if (preset) applyTextPresetToPlayground(preset);
    }

    const visionPresetId = getActivePresetVisionId();
    if (visionPresetId && pipelines.length) {
      const preset = playgroundPresets.find(
        (item) => item.id === visionPresetId && presetAppliesVision(item),
      );
      if (preset) applyVisionPresetToPlayground(preset);
    }

    bridgeInitRef.current = true;
  }, [
    playgroundPresets,
    entityTypes,
    pipelines,
    applyTextPresetToPlayground,
    applyVisionPresetToPlayground,
  ]);

  const getTypeConfig = useCallback(
    (typeId: string): { name: string; color: string } => {
      const config = entityTypes.find((type) => type.id === typeId);
      return config || { name: typeId, color: '#6366F1' };
    },
    [entityTypes],
  );

  const getVisionTypeConfig = useCallback(
    (typeId: string): { name: string; color: string } => {
      const config = visionTypes.find((type) => type.id === typeId);
      return config || { name: typeId, color: '#6366F1' };
    },
    [visionTypes],
  );

  const sortedEntityTypes = useMemo(() => sortEntityTypes(entityTypes), [entityTypes]);

  const playgroundTextGroups = useMemo(
    () => buildPlaygroundTextGroups(sortedEntityTypes),
    [sortedEntityTypes],
  );

  const setPlaygroundTextTypeGroupSelection = useCallback(
    (ids: string[], turnOn: boolean) => {
      clearPlaygroundTextPresetTracking();
      setSelectedTypes((previous) => {
        if (turnOn) {
          const next = new Set(previous);
          ids.forEach((id) => next.add(id));
          return [...next];
        }
        return previous.filter((id) => !ids.includes(id));
      });
    },
    [clearPlaygroundTextPresetTracking, setSelectedTypes],
  );

  const toggleVisionType = useCallback(
    (typeId: string, pipelineMode: 'ocr_has' | 'visual_features') => {
      clearPlaygroundVisionPresetTracking();
      if (pipelineMode === 'ocr_has') {
        const isActive = selectedOcrHasTypes.includes(typeId);
        const next = isActive
          ? selectedOcrHasTypes.filter((id) => id !== typeId)
          : [...selectedOcrHasTypes, typeId];
        updateOcrHasTypes(next);
        return { typeId, wasActive: isActive };
      }
      const isActive = selectedVisualFeatureTypes.includes(typeId);
      const next = isActive
        ? selectedVisualFeatureTypes.filter((id) => id !== typeId)
        : [...selectedVisualFeatureTypes, typeId];
      updateVisualFeatureTypes(next);
      return { typeId, wasActive: isActive };
    },
    [
      selectedOcrHasTypes,
      selectedVisualFeatureTypes,
      updateOcrHasTypes,
      updateVisualFeatureTypes,
      clearPlaygroundVisionPresetTracking,
    ],
  );

  return {
    entityTypes,
    textConfigState,
    selectedTypes,
    selectedTypesRef,
    setSelectedTypes,
    visionTypes,
    visionConfigState,
    selectedOcrHasTypes,
    selectedVisualFeatureTypes,
    selectedOcrHasTypesRef,
    selectedVisualFeatureTypesRef,
    pipelines,
    typeTab,
    setTypeTab,
    replacementMode,
    setReplacementMode,
    textPresetsPg,
    visionPresetsPg,
    playgroundPresetTextId,
    playgroundPresetVisionId,
    selectPlaygroundTextPresetById,
    selectPlaygroundVisionPresetById,
    saveTextPresetFromPlayground,
    saveVisionPresetFromPlayground,
    presetDialogKind,
    presetDialogName,
    setPresetDialogName,
    presetSaving,
    closePresetDialog,
    openTextPresetDialog,
    openVisionPresetDialog,
    clearPlaygroundTextPresetTracking,
    clearPlaygroundVisionPresetTracking,
    sortedEntityTypes,
    playgroundTextGroups,
    setPlaygroundTextTypeGroupSelection,
    toggleVisionType,
    updateOcrHasTypes,
    updateVisualFeatureTypes,
    presetApplySeq,
    getTypeConfig,
    getVisionTypeConfig,
  };
}
