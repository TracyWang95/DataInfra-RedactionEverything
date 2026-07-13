// Copyright 2026 DataInfra-RedactionEverything Contributors

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
import { localizePresetName } from '@/features/settings/lib/redaction-display';
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

function localizePresetList(presets: RecognitionPreset[]): RecognitionPreset[] {
  return presets.map((preset) => ({
    ...preset,
    name: localizePresetName(preset, t),
  }));
}

export interface BatchConfigState {
  cfg: BatchWizardPersistedConfig;
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  configLoaded: boolean;
  textTypes: TextEntityType[];
  pipelines: PipelineCfg[];
  presets: RecognitionPreset[];
  textPresets: RecognitionPreset[];
  visionPresets: RecognitionPreset[];
  presetLoadError: string | null;
  presetReloading: boolean;
  retryLoadPresets: () => Promise<void>;
  confirmStep1: boolean;
  setConfirmStep1: React.Dispatch<React.SetStateAction<boolean>>;
  isStep1Complete: boolean;
  onBatchTextPresetChange: (id: string) => void;
  onBatchVisionPresetChange: (id: string) => void;
  batchDefaultTextTypeIds: string[];
  batchDefaultOcrHasTypeIds: string[];
  batchDefaultVisualFeatureTypeIds: string[];
  setConfigLoadError: (msg: string) => void;
  jobPriority: string;
  setJobPriority: React.Dispatch<React.SetStateAction<string>>;
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
  const [presetLoadError, setPresetLoadError] = useState<string | null>(null);
  const [presetReloading, setPresetReloading] = useState(false);
  const [confirmStep1, setConfirmStep1] = useState(false);
  const [jobPriority, setJobPriority] = useState('normal');

  // Save config to local storage on change
  useEffect(() => {
    saveBatchWizardConfig(cfg, mode);
  }, [cfg, mode]);

  // Load config from backend or preview fixtures
  useEffect(() => {
    let cancelled = false;
    if (isPreviewMode) {
      setTextTypes(previewTextTypes);
      setPipelines(previewPipelines);
      setPresets(previewPresets);
      setPresetLoadError(null);
      setPresetReloading(false);
      setCfg({ ...previewBatchConfig });
      setConfirmStep1(true);
      setConfigLoaded(true);
      setMsg(null);
      if (!activeJobId) setActiveJobId(PREVIEW_BATCH_JOB_ID);
      return () => {
        cancelled = true;
      };
    }
    (async () => {
      try {
        const presetFetch = fetchRecognitionPresets()
          .then((value) => ({ ok: true as const, value }))
          .catch(() => ({ ok: false as const, value: [] as RecognitionPreset[] }));
        const [types, pipes, presetResult] = await Promise.all([
          fetchRecognitionEntityTypes(true, 25_000),
          fetchRecognitionPipelines(25_000) as Promise<PipelineCfg[]>,
          presetFetch,
        ]);
        if (cancelled) return;
        setTextTypes(types);
        setPipelines(pipes);
        setPresetLoadError(presetResult.ok ? null : t('batchWizard.step1.presetLoadError'));
        setPresets(Array.isArray(presetResult.value) ? localizePresetList(presetResult.value) : []);

        const persisted = loadBatchWizardConfig(mode);
        const defaultTextTypeIds = buildDefaultTextTypeIds(types);
        const defaultOcrHasTypeIds = buildDefaultPipelineTypeIds(pipes, 'ocr_has');
        const defaultVisualFeatureTypeIds = buildDefaultPipelineTypeIds(pipes, 'visual_features');
        const ocrIds = pipes
          .filter((p) => p.mode === 'ocr_has' && p.enabled)
          .flatMap((p) => p.types.filter((tt) => tt.enabled).map((tt) => tt.id));
        const visualIds = pipes
          .filter((p) => p.mode === 'visual_features' && p.enabled)
          .flatMap((p) => p.types.filter((tt) => tt.enabled).map((tt) => tt.id));

        const presetList: RecognitionPreset[] = Array.isArray(presetResult.value)
          ? localizePresetList(presetResult.value)
          : [];
        const persistedTextIds = persisted?.selectedEntityTypeIds?.length
          ? persisted.selectedEntityTypeIds.filter((id) => types.some((tt) => tt.id === id))
          : [];
        const selectedEntityTypeIds = persistedTextIds.length
          ? persistedTextIds
          : defaultTextTypeIds;
        const persistedOcrHas = persisted?.ocrHasTypes?.length
          ? persisted.ocrHasTypes.filter((id) => ocrIds.includes(id))
          : [];
        const filteredOcrHas = persistedOcrHas.length ? persistedOcrHas : defaultOcrHasTypeIds;
        const filteredVisualFeatures = persisted?.visualFeatureTypes?.length
          ? persisted.visualFeatureTypes.filter((id) => visualIds.includes(id))
          : defaultVisualFeatureTypeIds;
        const ocrHas =
          persisted?.ocrHasTypes?.length && filteredOcrHas.length === 0
            ? defaultOcrHasTypeIds
            : filteredOcrHas;
        const visualFeatures =
          persisted?.visualFeatureTypes?.length && filteredVisualFeatures.length === 0
            ? defaultVisualFeatureTypeIds
            : filteredVisualFeatures;
        const applyFetchedTextPresetWithFallback = (preset: RecognitionPreset) => {
          const applied = applyTextPresetFields(preset, types);
          return {
            ...applied,
            selectedEntityTypeIds:
              preset.selectedEntityTypeIds.length > 0 && applied.selectedEntityTypeIds.length === 0
                ? [...defaultTextTypeIds]
                : applied.selectedEntityTypeIds,
          };
        };
        const applyFetchedVisionPresetWithFallback = (preset: RecognitionPreset) => {
          const applied = applyVisionPresetFields(preset, pipes);
          return {
            ...applied,
            ocrHasTypes:
              preset.ocrHasTypes.length > 0 && applied.ocrHasTypes.length === 0
                ? [...defaultOcrHasTypeIds]
                : applied.ocrHasTypes,
            visualFeatureTypes:
              (preset.visualFeatureTypes ?? []).length > 0 &&
              applied.visualFeatureTypes.length === 0
                ? [...defaultVisualFeatureTypeIds]
                : applied.visualFeatureTypes,
          };
        };

        let next: BatchWizardPersistedConfig = {
          selectedEntityTypeIds,
          ocrHasTypes: ocrHas,
          visualFeatureTypes: visualFeatures,
          replacementMode: persisted?.replacementMode ?? 'structured',
          imageRedactionMethod: persisted?.imageRedactionMethod ?? 'mosaic',
          imageRedactionStrength: persisted?.imageRedactionStrength ?? 75,
          imageFillColor: persisted?.imageFillColor ?? '#000000',
          presetTextId: null,
          presetVisionId: null,
          executionDefault: persisted?.executionDefault === 'local' ? 'local' : 'queue',
        };

        const bridgeTextId = getActivePresetTextId();
        const bridgeVisionId = getActivePresetVisionId();
        const textPresetCandidates = [bridgeTextId, persisted?.presetTextId ?? null].filter(
          Boolean,
        ) as string[];
        const visionPresetCandidates = [bridgeVisionId, persisted?.presetVisionId ?? null].filter(
          Boolean,
        ) as string[];
        const pt = textPresetCandidates
          .map((id) => presetList.find((x) => x.id === id && presetAppliesText(x)))
          .find(Boolean);
        const pv = visionPresetCandidates
          .map((id) => presetList.find((x) => x.id === id && presetAppliesVision(x)))
          .find(Boolean);
        if (pt) next = { ...next, ...applyFetchedTextPresetWithFallback(pt), presetTextId: pt.id };
        if (pv)
          next = { ...next, ...applyFetchedVisionPresetWithFallback(pv), presetVisionId: pv.id };
        setCfg(next);
      } catch {
        setMsg({ text: t('batchWizard.waitConfig'), tone: 'err' });
      } finally {
        if (!cancelled) setConfigLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeJobId, isPreviewMode, mode, setActiveJobId, setMsg]);

  const retryLoadPresets = useCallback(async () => {
    setPresetReloading(true);
    try {
      const presetRes = await fetchRecognitionPresets();
      setPresets(Array.isArray(presetRes) ? localizePresetList(presetRes) : []);
      setPresetLoadError(null);
    } catch {
      setPresetLoadError(t('batchWizard.step1.presetLoadError'));
    } finally {
      setPresetReloading(false);
    }
  }, []);

  // Refresh text types when entity types are changed in Settings
  useEffect(() => {
    const handler = async () => {
      try {
        const types = await fetchRecognitionEntityTypes(true, 10_000);
        setTextTypes(types);
      } catch {
        /* ignore — will pick up on next full load */
      }
    };
    window.addEventListener('entity-types-changed', handler);
    return () => window.removeEventListener('entity-types-changed', handler);
  }, []);

  // Derived values
  const textPresets = useMemo(() => presets.filter(presetAppliesText), [presets]);
  const visionPresets = useMemo(() => presets.filter(presetAppliesVision), [presets]);
  const batchDefaultTextTypeIds = useMemo(() => buildDefaultTextTypeIds(textTypes), [textTypes]);
  const batchDefaultOcrHasTypeIds = useMemo(
    () => buildDefaultPipelineTypeIds(pipelines, 'ocr_has'),
    [pipelines],
  );
  const batchDefaultVisualFeatureTypeIds = useMemo(
    () => buildDefaultPipelineTypeIds(pipelines, 'visual_features'),
    [pipelines],
  );

  const applyTextPresetWithFallback = useCallback(
    (preset: RecognitionPreset) => {
      const applied = applyTextPresetFields(preset, textTypes);
      return {
        ...applied,
        selectedEntityTypeIds:
          preset.selectedEntityTypeIds.length > 0 && applied.selectedEntityTypeIds.length === 0
            ? [...batchDefaultTextTypeIds]
            : applied.selectedEntityTypeIds,
      };
    },
    [batchDefaultTextTypeIds, textTypes],
  );

  const applyVisionPresetWithFallback = useCallback(
    (preset: RecognitionPreset) => {
      const applied = applyVisionPresetFields(preset, pipelines);
      const recoveredOcr =
        preset.ocrHasTypes.length > 0 && applied.ocrHasTypes.length === 0
          ? [...batchDefaultOcrHasTypeIds]
          : applied.ocrHasTypes;
      const recoveredVisualFeatures =
        (preset.visualFeatureTypes ?? []).length > 0 &&
        applied.visualFeatureTypes.length === 0
          ? [...batchDefaultVisualFeatureTypeIds]
          : applied.visualFeatureTypes;
      return {
        ...applied,
        ocrHasTypes: recoveredOcr,
        visualFeatureTypes: recoveredVisualFeatures,
      };
    },
    [batchDefaultOcrHasTypeIds, batchDefaultVisualFeatureTypeIds, pipelines],
  );

  const isStep1Complete = useMemo(() => {
    if (!confirmStep1 || !configLoaded) return false;
    const anyTextSelected = cfg.selectedEntityTypeIds.length > 0;
    const anyVisionSelected =
      cfg.ocrHasTypes.length > 0 ||
      cfg.visualFeatureTypes.length > 0;
    if (mode === 'text') return anyTextSelected;
    if (mode === 'image') return anyVisionSelected;
    return anyTextSelected || anyVisionSelected;
  }, [
    configLoaded,
    cfg.selectedEntityTypeIds,
    cfg.ocrHasTypes,
    cfg.visualFeatureTypes,
    confirmStep1,
    mode,
  ]);

  // Preset change handlers
  const onBatchTextPresetChange = useCallback(
    (id: string) => {
      if (!id) {
        setActivePresetTextId(null);
        setCfg((c) => ({
          ...c,
          presetTextId: null,
          selectedEntityTypeIds: [...batchDefaultTextTypeIds],
          replacementMode: 'structured',
        }));
        return;
      }
      const p = presets.find((x) => x.id === id);
      if (p && presetAppliesText(p)) {
        setActivePresetTextId(p.id);
        if (mode !== 'text' && presetAppliesVision(p)) {
          setActivePresetVisionId(p.id);
          setCfg((c) => ({
            ...c,
            ...applyTextPresetWithFallback(p),
            ...applyVisionPresetWithFallback(p),
            presetTextId: p.id,
            presetVisionId: p.id,
          }));
          return;
        }
        setCfg((c) => ({ ...c, ...applyTextPresetWithFallback(p), presetTextId: p.id }));
      }
    },
    [
      applyTextPresetWithFallback,
      applyVisionPresetWithFallback,
      batchDefaultTextTypeIds,
      mode,
      presets,
    ],
  );

  const onBatchVisionPresetChange = useCallback(
    (id: string) => {
      if (!id) {
        setActivePresetVisionId(null);
        setCfg((c) => ({
          ...c,
          presetVisionId: null,
          ocrHasTypes: [...batchDefaultOcrHasTypeIds],
          visualFeatureTypes: [...batchDefaultVisualFeatureTypeIds],
        }));
        return;
      }
      const p = presets.find((x) => x.id === id);
      if (p && presetAppliesVision(p)) {
        setActivePresetVisionId(p.id);
        if (mode !== 'image' && presetAppliesText(p)) {
          setActivePresetTextId(p.id);
          setCfg((c) => ({
            ...c,
            ...applyTextPresetWithFallback(p),
            ...applyVisionPresetWithFallback(p),
            presetTextId: p.id,
            presetVisionId: p.id,
          }));
          return;
        }
        const applied = applyVisionPresetWithFallback(p);
        setCfg((c) => ({
          ...c,
          ...applied,
          presetVisionId: p.id,
        }));
      }
    },
    [
      applyTextPresetWithFallback,
      applyVisionPresetWithFallback,
      batchDefaultOcrHasTypeIds,
      batchDefaultVisualFeatureTypeIds,
      mode,
      presets,
    ],
  );

  const setConfigLoadError = useCallback(
    (msg: string) => {
      setMsg({ text: msg, tone: 'err' });
    },
    [setMsg],
  );

  return {
    cfg,
    setCfg,
    configLoaded,
    textTypes,
    pipelines,
    presets,
    textPresets,
    visionPresets,
    presetLoadError,
    presetReloading,
    retryLoadPresets,
    confirmStep1,
    setConfirmStep1,
    isStep1Complete,
    onBatchTextPresetChange,
    onBatchVisionPresetChange,
    batchDefaultTextTypeIds,
    batchDefaultOcrHasTypeIds,
    batchDefaultVisualFeatureTypeIds,
    setConfigLoadError,
    jobPriority,
    setJobPriority,
  };
}
