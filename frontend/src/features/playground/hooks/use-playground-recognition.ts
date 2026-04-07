// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import {
  fetchPresets,
  createPreset,
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '@/services/presetsApi';
import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
} from '@/services/recognition-config';
import {
  buildDefaultPipelineTypeIds,
  buildDefaultTextTypeIds,
} from '@/services/defaultRedactionPreset';
import {
  setActivePresetTextId,
  setActivePresetVisionId,
  getActivePresetTextId,
  getActivePresetVisionId,
} from '@/services/activePresetBridge';
import { t } from '@/i18n';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import {
  buildPlaygroundTextGroups,
  type ConfigLoadState,
  flattenVisionTypes,
  normalizeVisionPipelines,
  sortEntityTypes,
} from '../lib/recognition-config';
import type {
  EntityTypeConfig,
  VisionTypeConfig,
  PipelineConfig,
} from '../types';

export function usePlaygroundRecognition() {
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [textConfigState, setTextConfigState] = useState<ConfigLoadState>('loading');
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [visionTypes, setVisionTypes] = useState<VisionTypeConfig[]>([]);
  const [visionConfigState, setVisionConfigState] = useState<ConfigLoadState>('loading');
  const [selectedOcrHasTypes, setSelectedOcrHasTypes] = useState<string[]>([]);
  const [selectedHasImageTypes, setSelectedHasImageTypes] = useState<string[]>([]);
  const selectedOcrHasTypesRef = useRef(selectedOcrHasTypes);
  const selectedHasImageTypesRef = useRef(selectedHasImageTypes);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [typeTab, setTypeTab] = useState<'text' | 'vision'>('text');
  const [replacementMode, setReplacementMode] = useState<'structured' | 'smart' | 'mask'>('structured');
  const [playgroundPresets, setPlaygroundPresets] = useState<RecognitionPreset[]>([]);
  const [playgroundPresetTextId, setPlaygroundPresetTextId] = useState<string | null>(null);
  const [playgroundPresetVisionId, setPlaygroundPresetVisionId] = useState<string | null>(null);
  const [presetDialogKind, setPresetDialogKind] = useState<'text' | 'vision' | null>(null);
  const [presetDialogName, setPresetDialogName] = useState('');
  const [presetSaving, setPresetSaving] = useState(false);
  const [presetApplySeq, setPresetApplySeq] = useState(0);

  const textPresetsPg = useMemo(() => playgroundPresets.filter(presetAppliesText), [playgroundPresets]);
  const visionPresetsPg = useMemo(() => playgroundPresets.filter(presetAppliesVision), [playgroundPresets]);

  const playgroundDefaultTextTypeIds = useMemo(
    () => buildDefaultTextTypeIds(entityTypes),
    [entityTypes]
  );
  const playgroundDefaultOcrHasTypeIds = useMemo(
    () => buildDefaultPipelineTypeIds(pipelines, 'ocr_has'),
    [pipelines]
  );
  const playgroundDefaultHasImageTypeIds = useMemo(
    () => buildDefaultPipelineTypeIds(pipelines, 'has_image'),
    [pipelines]
  );

  const updateOcrHasTypes = useCallback((types: string[]) => {
    selectedOcrHasTypesRef.current = types;
    setSelectedOcrHasTypes(types);
    localStorage.setItem('ocrHasTypes', JSON.stringify(types));
  }, []);

  const updateHasImageTypes = useCallback((types: string[]) => {
    selectedHasImageTypesRef.current = types;
    setSelectedHasImageTypes(types);
    localStorage.setItem('hasImageTypes', JSON.stringify(types));
  }, []);

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
      const enabledTextIds = new Set(entityTypes.filter(type => type.enabled !== false).map(type => type.id));
      setSelectedTypes(preset.selectedEntityTypeIds.filter(id => enabledTextIds.has(id)));
      if ((preset.kind ?? 'full') !== 'text') {
        setReplacementMode(preset.replacementMode);
      }
      setPlaygroundPresetTextId(preset.id);
      setActivePresetTextId(preset.id);
      setPresetApplySeq(s => s + 1);
    },
    [entityTypes]
  );

  const applyVisionPresetToPlayground = useCallback(
    (preset: RecognitionPreset) => {
      if (!presetAppliesVision(preset)) return;
      const ocrIds = pipelines
        .filter(pipeline => pipeline.mode === 'ocr_has')
        .flatMap(pipeline => pipeline.types.map(type => type.id));
      const imageIds = pipelines
        .filter(pipeline => pipeline.mode === 'has_image')
        .flatMap(pipeline => pipeline.types.map(type => type.id));

      updateOcrHasTypes(preset.ocrHasTypes.filter(id => ocrIds.includes(id)));
      updateHasImageTypes(preset.hasImageTypes.filter(id => imageIds.includes(id)));
      setPlaygroundPresetVisionId(preset.id);
      setActivePresetVisionId(preset.id);
    },
    [pipelines, updateOcrHasTypes, updateHasImageTypes]
  );

  const selectPlaygroundTextPresetById = useCallback(
    (id: string) => {
      if (!id) {
        setPlaygroundPresetTextId(null);
        setActivePresetTextId(null);
        setSelectedTypes([...playgroundDefaultTextTypeIds]);
        setReplacementMode('structured');
        setPresetApplySeq(s => s + 1);
        return;
      }

      const preset = playgroundPresets.find(item => item.id === id);
      if (preset) applyTextPresetToPlayground(preset);
    },
    [playgroundDefaultTextTypeIds, playgroundPresets, applyTextPresetToPlayground]
  );

  const selectPlaygroundVisionPresetById = useCallback(
    (id: string) => {
      if (!id) {
        setPlaygroundPresetVisionId(null);
        setActivePresetVisionId(null);
        updateOcrHasTypes([...playgroundDefaultOcrHasTypeIds]);
        updateHasImageTypes([...playgroundDefaultHasImageTypeIds]);
        return;
      }

      const preset = playgroundPresets.find(item => item.id === id);
      if (preset) applyVisionPresetToPlayground(preset);
    },
    [
      playgroundDefaultOcrHasTypeIds,
      playgroundDefaultHasImageTypeIds,
      playgroundPresets,
      applyVisionPresetToPlayground,
      updateOcrHasTypes,
      updateHasImageTypes,
    ]
  );

  useEffect(() => {
    void fetchPresets()
      .then(setPlaygroundPresets)
      .catch(() => setPlaygroundPresets([]));
  }, []);

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
        hasImageTypes: [],
        replacementMode: 'structured',
      });
      const nextPresets = await fetchPresets();
      setPlaygroundPresets(nextPresets);
      setPlaygroundPresetTextId(created.id);
      setActivePresetTextId(created.id);
      closePresetDialog();
      showToast(t('preset.saveText.success'), 'success');
    } catch (error) {
      showToast(localizeErrorMessage(error, 'preset.save.failed'), 'error');
    } finally {
      setPresetSaving(false);
    }
  }, [closePresetDialog, presetDialogName, selectedTypes]);

  const saveVisionPresetFromPlayground = useCallback(async () => {
    const name = presetDialogName.trim();
    if (!name) {
      showToast(t('settings.redaction.nameRequired'), 'error');
      return;
    }

    setPresetSaving(true);
    try {
      const created = await createPreset({
        name,
        kind: 'vision',
        selectedEntityTypeIds: [],
        ocrHasTypes: selectedOcrHasTypes,
        hasImageTypes: selectedHasImageTypes,
        replacementMode: 'structured',
      });
      const nextPresets = await fetchPresets();
      setPlaygroundPresets(nextPresets);
      setPlaygroundPresetVisionId(created.id);
      setActivePresetVisionId(created.id);
      closePresetDialog();
      showToast(t('preset.saveVision.success'), 'success');
    } catch (error) {
      showToast(localizeErrorMessage(error, 'preset.save.failed'), 'error');
    } finally {
      setPresetSaving(false);
    }
  }, [closePresetDialog, presetDialogName, selectedHasImageTypes, selectedOcrHasTypes]);

  const fetchEntityTypes = useCallback(async () => {
    try {
      const types = sortEntityTypes(await fetchRecognitionEntityTypes(true, 1_200));
      setEntityTypes(types);
      setTextConfigState(types.length > 0 ? 'ready' : 'empty');
      setSelectedTypes(buildDefaultTextTypeIds(types));
    } catch (error) {
      if (import.meta.env.DEV) console.error('fetch entity types failed', error);
      setEntityTypes([]);
      setSelectedTypes([]);
      setTextConfigState('unavailable');
    }
  }, []);

  const fetchVisionTypes = useCallback(async () => {
    try {
      const normalizedPipelines = normalizeVisionPipelines(
        await fetchRecognitionPipelines(1_200) as PipelineConfig[],
      );
      const nextVisionTypes = flattenVisionTypes(normalizedPipelines);

      setPipelines(normalizedPipelines);
      setVisionTypes(nextVisionTypes);
      setVisionConfigState(normalizedPipelines.length > 0 ? 'ready' : 'empty');

      const ocrHasTypeIds = normalizedPipelines
        .filter(pipeline => pipeline.mode === 'ocr_has')
        .flatMap(pipeline => pipeline.types.map(type => type.id));
      const defaultOcrHasTypeIds = buildDefaultPipelineTypeIds(normalizedPipelines, 'ocr_has');
      const savedOcrHasTypes = localStorage.getItem('ocrHasTypes');
      if (savedOcrHasTypes) {
        try {
          const parsed = JSON.parse(savedOcrHasTypes);
          const filtered = Array.isArray(parsed)
            ? parsed.filter((id: string) => ocrHasTypeIds.includes(id))
            : [];
          updateOcrHasTypes(filtered);
        } catch {
          updateOcrHasTypes(defaultOcrHasTypeIds);
        }
      } else {
        updateOcrHasTypes(defaultOcrHasTypeIds);
      }

      const hasImageTypeIds = normalizedPipelines
        .filter(pipeline => pipeline.mode === 'has_image')
        .flatMap(pipeline => pipeline.types.map(type => type.id));
      const defaultHasImageTypeIds = buildDefaultPipelineTypeIds(normalizedPipelines, 'has_image');
      const savedHasImageTypes =
        localStorage.getItem('hasImageTypes') || localStorage.getItem('glmVisionTypes');
      if (savedHasImageTypes) {
        try {
          const parsed = JSON.parse(savedHasImageTypes);
          const filtered = Array.isArray(parsed)
            ? parsed.filter((id: string) => hasImageTypeIds.includes(id))
            : [];
          updateHasImageTypes(filtered);
        } catch {
          updateHasImageTypes(defaultHasImageTypeIds);
        }
      } else {
        updateHasImageTypes(defaultHasImageTypeIds);
      }
    } catch (error) {
      if (import.meta.env.DEV) console.error('fetch vision pipelines failed', error);
      setPipelines([]);
      setVisionTypes([]);
      setVisionConfigState('unavailable');
      updateOcrHasTypes([]);
      updateHasImageTypes([]);
    }
  }, [updateOcrHasTypes, updateHasImageTypes]);

  useEffect(() => {
    fetchEntityTypes();
    fetchVisionTypes();
  }, [fetchEntityTypes, fetchVisionTypes]);

  useEffect(() => {
    const handleFocus = () => {
      fetchEntityTypes();
      fetchVisionTypes();
    };

    window.addEventListener('focus', handleFocus);
    window.addEventListener('entity-types-changed', fetchEntityTypes);
    return () => {
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('entity-types-changed', fetchEntityTypes);
    };
  }, [fetchEntityTypes, fetchVisionTypes]);

  const bridgeInitRef = useRef(false);
  useEffect(() => {
    if (bridgeInitRef.current) return;
    if (!playgroundPresets.length || !entityTypes.length) return;

    const textPresetId = getActivePresetTextId();
    if (textPresetId) {
      const preset = playgroundPresets.find(item => item.id === textPresetId && presetAppliesText(item));
      if (preset) applyTextPresetToPlayground(preset);
    }

    const visionPresetId = getActivePresetVisionId();
    if (visionPresetId && pipelines.length) {
      const preset = playgroundPresets.find(item => item.id === visionPresetId && presetAppliesVision(item));
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

  const sortedEntityTypes = useMemo(() => sortEntityTypes(entityTypes), [entityTypes]);

  const playgroundTextGroups = useMemo(
    () => buildPlaygroundTextGroups(sortedEntityTypes),
    [sortedEntityTypes]
  );

  const setPlaygroundTextTypeGroupSelection = useCallback(
    (ids: string[], turnOn: boolean) => {
      clearPlaygroundTextPresetTracking();
      setSelectedTypes(previous => {
        if (turnOn) {
          const next = new Set(previous);
          ids.forEach(id => next.add(id));
          return [...next];
        }
        return previous.filter(id => !ids.includes(id));
      });
    },
    [clearPlaygroundTextPresetTracking]
  );

  const toggleVisionType = useCallback(
    (typeId: string, pipelineMode: 'ocr_has' | 'has_image') => {
      clearPlaygroundVisionPresetTracking();
      if (pipelineMode === 'ocr_has') {
        const isActive = selectedOcrHasTypes.includes(typeId);
        const next = isActive
          ? selectedOcrHasTypes.filter(id => id !== typeId)
          : [...selectedOcrHasTypes, typeId];
        updateOcrHasTypes(next);
        return { typeId, wasActive: isActive };
      }

      const isActive = selectedHasImageTypes.includes(typeId);
      const next = isActive
        ? selectedHasImageTypes.filter(id => id !== typeId)
        : [...selectedHasImageTypes, typeId];
      updateHasImageTypes(next);
      return { typeId, wasActive: isActive };
    },
    [
      selectedOcrHasTypes,
      selectedHasImageTypes,
      updateOcrHasTypes,
      updateHasImageTypes,
      clearPlaygroundVisionPresetTracking,
    ]
  );

  return {
    entityTypes,
    textConfigState,
    selectedTypes,
    setSelectedTypes,
    visionTypes,
    visionConfigState,
    selectedOcrHasTypes,
    selectedHasImageTypes,
    selectedOcrHasTypesRef,
    selectedHasImageTypesRef,
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
    updateHasImageTypes,
    presetApplySeq,
    getTypeConfig: (typeId: string): { name: string; color: string } => {
      const config = entityTypes.find(type => type.id === typeId);
      return config || { name: typeId, color: '#6366F1' };
    },
    getVisionTypeConfig: (typeId: string): { name: string; color: string } => {
      const config = visionTypes.find(type => type.id === typeId);
      return config || { name: typeId, color: '#6366F1' };
    },
  };
}
