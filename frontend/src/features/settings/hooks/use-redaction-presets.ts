// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useT } from '@/i18n';
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
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
  fetchRecognitionPresets,
} from '@/services/recognition-config';
import type { EntityTypeConfig, PipelineConfig } from './use-entity-types';

function sortPresets(presets: RecognitionPreset[]): RecognitionPreset[] {
  return [...presets].sort((left, right) => {
    const leftTime = left.created_at ? Date.parse(left.created_at) : Number.MAX_SAFE_INTEGER;
    const rightTime = right.created_at ? Date.parse(right.created_at) : Number.MAX_SAFE_INTEGER;
    return (Number.isFinite(leftTime) ? leftTime : Number.MAX_SAFE_INTEGER)
      - (Number.isFinite(rightTime) ? rightTime : Number.MAX_SAFE_INTEGER);
  });
}

export function useRedactionPresets() {
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

  const fetchPipelinesData = useCallback(async () => {
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
    void fetchPipelinesData();
    void reloadPresets();
  }, [fetchEntityTypes, fetchPipelinesData, reloadPresets]);

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

  return {
    // Data
    loading,
    loadError,
    effectiveEntityTypes,
    effectivePipelines,
    textPresets,
    visionPresets,
    regexTypes,
    semanticTypes,
    defaultTextPreset,
    defaultVisionPreset,
    summaryTextLabel,
    summaryVisionLabel,

    // Bridge state
    bridgeText,
    setBridgeText,
    bridgeVision,
    setBridgeVision,

    // Expanded / confirm
    expanded,
    setExpanded,
    confirmState,
    setConfirmState,

    // Modal state
    modalOpen,
    setModalOpen,
    editingPresetId,
    presetForm,
    setPresetForm,
    saving,
    presetKindLabel,

    // Actions
    openNew,
    openEdit,
    saveModal,
    removePreset,
  };
}
