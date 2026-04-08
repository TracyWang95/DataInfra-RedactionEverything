// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useCallback, useEffect, useMemo, useState } from 'react';
import { t } from '@/i18n';
import {
  loadBatchWizardConfig,
  saveBatchWizardConfig,
  type BatchWizardMode,
  type BatchWizardPersistedConfig,
} from '@/services/batchPipeline';
import {
  getActivePresetTextId,
  getActivePresetVisionId,
  setActivePresetTextId,
  setActivePresetVisionId,
} from '@/services/activePresetBridge';
import {
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '@/services/presetsApi';
import {
  buildDefaultPipelineTypeIds,
  buildDefaultTextTypeIds,
} from '@/services/defaultRedactionPreset';
import {
  fetchRecognitionEntityTypes,
  fetchRecognitionPipelines,
  fetchRecognitionPresets,
} from '@/services/recognition-config';
import {
  previewBatchConfig,
  previewPipelines,
  previewPresets,
  previewTextTypes,
  PREVIEW_BATCH_JOB_ID,
} from '../lib/batch-preview-fixtures';
import type { PipelineCfg, TextEntityType } from '../types';
import {
  applyTextPresetFields,
  applyVisionPresetFields,
  defaultConfig,
} from './use-batch-wizard-utils';

export interface BatchConfigState {
  cfg: BatchWizardPersistedConfig;
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  configLoaded: boolean;
  textTypes: TextEntityType[];
  pipelines: PipelineCfg[];
  presets: RecognitionPreset[];
  textPresets: RecognitionPreset[];
  visionPresets: RecognitionPreset[];
  confirmStep1: boolean;
  setConfirmStep1: React.Dispatch<React.SetStateAction<boolean>>;
  isStep1Complete: boolean;
  jobPriority: number;
  setJobPriority: React.Dispatch<React.SetStateAction<number>>;
  onBatchTextPresetChange: (id: string) => void;
  onBatchVisionPresetChange: (id: string) => void;
  batchDefaultTextTypeIds: string[];
  batchDefaultOcrHasTypeIds: string[];
  batchDefaultHasImageTypeIds: string[];
  setConfigLoadError: (msg: string) => void;
}

export function useBatchConfig(
  mode: BatchWizardMode,
  activeJobId: string | null,
  setActiveJobId: React.Dispatch<React.SetStateAction<string | null>>,
  isPreviewMode: boolean,
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void,
): BatchConfigState {
  const [cfg, setCfg] = useState<BatchWizardPersistedConfig>(() => defaultConfig());
  const [textTypes, setTextTypes] = useState<TextEntityType[]>([]);
  const [pipelines, setPipelines] = useState<PipelineCfg[]>([]);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [presets, setPresets] = useState<RecognitionPreset[]>([]);
  const [confirmStep1, setConfirmStep1] = useState(false);
  const [jobPriority, setJobPriority] = useState<number>(0);

  // Save config to local storage on change
  useEffect(() => { saveBatchWizardConfig(cfg, mode); }, [cfg, mode]);

  // Load config from backend or preview fixtures
  useEffect(() => {
    let cancelled = false;
    if (isPreviewMode) {
      setTextTypes(previewTextTypes);
      setPipelines(previewPipelines);
      setPresets(previewPresets);
      setCfg({ ...previewBatchConfig });
      setConfirmStep1(true);
      setJobPriority(5);
      setConfigLoaded(true);
      setMsg(null);
      if (!activeJobId) setActiveJobId(PREVIEW_BATCH_JOB_ID);
      return () => { cancelled = true; };
    }
    (async () => {
      try {
        const [types, pipes, presetRes] = await Promise.all([
          fetchRecognitionEntityTypes(true, 25_000),
          fetchRecognitionPipelines(25_000) as Promise<PipelineCfg[]>,
          fetchRecognitionPresets().catch(() => [] as RecognitionPreset[]),
        ]);
        if (cancelled) return;
        setTextTypes(types);
        setPipelines(pipes);
        setPresets(Array.isArray(presetRes) ? presetRes : []);

        const persisted = loadBatchWizardConfig(mode);
        const defaultTextTypeIds = buildDefaultTextTypeIds(types);
        const defaultOcrHasTypeIds = buildDefaultPipelineTypeIds(pipes, 'ocr_has');
        const defaultHasImageTypeIds = buildDefaultPipelineTypeIds(pipes, 'has_image');
        const ocrIds = pipes.filter(p => p.mode === 'ocr_has' && p.enabled).flatMap(p => p.types.filter(tt => tt.enabled).map(tt => tt.id));
        const hiIds = pipes.filter(p => p.mode === 'has_image' && p.enabled).flatMap(p => p.types.filter(tt => tt.enabled).map(tt => tt.id));

        const presetList: RecognitionPreset[] = Array.isArray(presetRes) ? presetRes : [];
        const selectedEntityTypeIds = persisted?.selectedEntityTypeIds?.length
          ? persisted.selectedEntityTypeIds.filter(id => types.some(tt => tt.id === id))
          : defaultTextTypeIds;
        const ocrHas = persisted?.ocrHasTypes?.length
          ? persisted.ocrHasTypes.filter(id => ocrIds.includes(id))
          : defaultOcrHasTypeIds;
        const hasImg = persisted?.hasImageTypes?.length
          ? persisted.hasImageTypes.filter(id => hiIds.includes(id))
          : defaultHasImageTypeIds;

        let next: BatchWizardPersistedConfig = {
          selectedEntityTypeIds, ocrHasTypes: ocrHas, hasImageTypes: hasImg,
          replacementMode: persisted?.replacementMode ?? 'structured',
          imageRedactionMethod: persisted?.imageRedactionMethod ?? 'mosaic',
          imageRedactionStrength: persisted?.imageRedactionStrength ?? 25,
          imageFillColor: persisted?.imageFillColor ?? '#000000',
          presetTextId: null, presetVisionId: null,
          executionDefault: persisted?.executionDefault === 'local' ? 'local' : 'queue',
        };

        const tid = persisted?.presetTextId ?? null;
        const vid = persisted?.presetVisionId ?? null;
        const pt = tid ? presetList.find(x => x.id === tid && presetAppliesText(x)) : undefined;
        const pv = vid ? presetList.find(x => x.id === vid && presetAppliesVision(x)) : undefined;
        if (pt) next = { ...next, ...applyTextPresetFields(pt, types), presetTextId: pt.id };
        if (pv) next = { ...next, ...applyVisionPresetFields(pv, pipes), presetVisionId: pv.id };
        if (!pt && persisted === null) {
          const bid = getActivePresetTextId();
          const ptB = bid ? presetList.find(x => x.id === bid && presetAppliesText(x)) : undefined;
          if (ptB) next = { ...next, ...applyTextPresetFields(ptB, types), presetTextId: ptB.id };
        }
        if (!pv && persisted === null) {
          const bid = getActivePresetVisionId();
          const pvB = bid ? presetList.find(x => x.id === bid && presetAppliesVision(x)) : undefined;
          if (pvB) next = { ...next, ...applyVisionPresetFields(pvB, pipes), presetVisionId: pvB.id };
        }
        setCfg(next);
      } catch {
        setMsg({ text: t('batchWizard.waitConfig'), tone: 'err' });
      } finally {
        if (!cancelled) setConfigLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [activeJobId, isPreviewMode, mode, setActiveJobId, setMsg]);

  // Refresh text types when entity types are changed in Settings
  useEffect(() => {
    const handler = async () => {
      try {
        const types = await fetchRecognitionEntityTypes(true, 10_000);
        setTextTypes(types);
      } catch { /* ignore — will pick up on next full load */ }
    };
    window.addEventListener('entity-types-changed', handler);
    return () => window.removeEventListener('entity-types-changed', handler);
  }, []);

  // Derived values
  const textPresets = useMemo(() => presets.filter(presetAppliesText), [presets]);
  const visionPresets = useMemo(() => presets.filter(presetAppliesVision), [presets]);
  const batchDefaultTextTypeIds = useMemo(() => buildDefaultTextTypeIds(textTypes), [textTypes]);
  const batchDefaultOcrHasTypeIds = useMemo(() => buildDefaultPipelineTypeIds(pipelines, 'ocr_has'), [pipelines]);
  const batchDefaultHasImageTypeIds = useMemo(() => buildDefaultPipelineTypeIds(pipelines, 'has_image'), [pipelines]);

  const isStep1Complete = useMemo(() => {
    if (!confirmStep1 || !configLoaded) return false;
    const anyTextSelected = cfg.selectedEntityTypeIds.length > 0;
    const anyVisionSelected = cfg.ocrHasTypes.length > 0 || cfg.hasImageTypes.length > 0;
    return anyTextSelected || anyVisionSelected;
  }, [configLoaded, cfg.selectedEntityTypeIds, cfg.ocrHasTypes, cfg.hasImageTypes, confirmStep1]);

  // Preset change handlers
  const onBatchTextPresetChange = useCallback((id: string) => {
    if (!id) {
      setActivePresetTextId(null);
      setCfg(c => ({ ...c, presetTextId: null, selectedEntityTypeIds: [...batchDefaultTextTypeIds], replacementMode: 'structured' }));
      return;
    }
    const p = presets.find(x => x.id === id);
    if (p && presetAppliesText(p)) {
      setActivePresetTextId(p.id);
      setCfg(c => ({ ...c, ...applyTextPresetFields(p, textTypes), presetTextId: p.id }));
    }
  }, [batchDefaultTextTypeIds, presets, textTypes]);

  const onBatchVisionPresetChange = useCallback((id: string) => {
    if (!id) {
      setActivePresetVisionId(null);
      setCfg(c => ({ ...c, presetVisionId: null, ocrHasTypes: [...batchDefaultOcrHasTypeIds], hasImageTypes: [...batchDefaultHasImageTypeIds] }));
      return;
    }
    const p = presets.find(x => x.id === id);
    if (p && presetAppliesVision(p)) {
      setActivePresetVisionId(p.id);
      setCfg(c => ({ ...c, ...applyVisionPresetFields(p, pipelines), presetVisionId: p.id }));
    }
  }, [batchDefaultOcrHasTypeIds, batchDefaultHasImageTypeIds, presets, pipelines]);

  const setConfigLoadError = useCallback((msg: string) => {
    setMsg({ text: msg, tone: 'err' });
  }, [setMsg]);

  return {
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    presets,
    textPresets,
    visionPresets,
    confirmStep1,
    setConfirmStep1,
    isStep1Complete,
    jobPriority,
    setJobPriority,
    onBatchTextPresetChange,
    onBatchVisionPresetChange,
    batchDefaultTextTypeIds,
    batchDefaultOcrHasTypeIds,
    batchDefaultHasImageTypeIds,
    setConfigLoadError,
  };
}
