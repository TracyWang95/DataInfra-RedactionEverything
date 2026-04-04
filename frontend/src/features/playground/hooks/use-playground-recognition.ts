/**
 * Recognition-specific logic: NER entity extraction, vision detection,
 * progress tracking, and timeout handling.
 */
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import {
  fetchPresets,
  createPreset,
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '@/services/presetsApi';
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
import { safeJson } from '../utils';
import type {
  EntityTypeConfig,
  VisionTypeConfig,
  PipelineConfig,
} from '../types';

export function usePlaygroundRecognition() {
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [visionTypes, setVisionTypes] = useState<VisionTypeConfig[]>([]);
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
    (p: RecognitionPreset) => {
      if (!presetAppliesText(p)) return;
      const textIds = new Set(entityTypes.filter(t => t.enabled !== false).map(t => t.id));
      setSelectedTypes(p.selectedEntityTypeIds.filter(id => textIds.has(id)));
      if ((p.kind ?? 'full') !== 'text') {
        setReplacementMode(p.replacementMode);
      }
      setPlaygroundPresetTextId(p.id);
      setActivePresetTextId(p.id);
    },
    [entityTypes]
  );

  const applyVisionPresetToPlayground = useCallback(
    (p: RecognitionPreset) => {
      if (!presetAppliesVision(p)) return;
      const ocrIds = pipelines
        .filter(pl => pl.mode === 'ocr_has' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id));
      const hiIds = pipelines
        .filter(pl => pl.mode === 'has_image' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id));
      updateOcrHasTypes(p.ocrHasTypes.filter(id => ocrIds.includes(id)));
      updateHasImageTypes(p.hasImageTypes.filter(id => hiIds.includes(id)));
      setPlaygroundPresetVisionId(p.id);
      setActivePresetVisionId(p.id);
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
        return;
      }
      const p = playgroundPresets.find(x => x.id === id);
      if (p) applyTextPresetToPlayground(p);
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
      const p = playgroundPresets.find(x => x.id === id);
      if (p) applyVisionPresetToPlayground(p);
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

  const saveTextPresetFromPlayground = useCallback(async () => {
    const name = window.prompt(t('preset.saveText.prompt'));
    if (!name?.trim()) return;
    try {
      const created = await createPreset({
        name: name.trim(),
        kind: 'text',
        selectedEntityTypeIds: selectedTypes,
        ocrHasTypes: [],
        hasImageTypes: [],
        replacementMode: 'structured',
      });
      const list = await fetchPresets();
      setPlaygroundPresets(list);
      setPlaygroundPresetTextId(created.id);
      setActivePresetTextId(created.id);
      showToast(t('preset.saveText.success'), 'success');
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('preset.save.failed'), 'error');
    }
  }, [selectedTypes]);

  const saveVisionPresetFromPlayground = useCallback(async () => {
    const name = window.prompt(t('preset.saveVision.prompt'));
    if (!name?.trim()) return;
    try {
      const created = await createPreset({
        name: name.trim(),
        kind: 'vision',
        selectedEntityTypeIds: [],
        ocrHasTypes: selectedOcrHasTypes,
        hasImageTypes: selectedHasImageTypes,
        replacementMode: 'structured',
      });
      const list = await fetchPresets();
      setPlaygroundPresets(list);
      setPlaygroundPresetVisionId(created.id);
      setActivePresetVisionId(created.id);
      showToast(t('preset.saveVision.success'), 'success');
    } catch (e) {
      showToast(e instanceof Error ? e.message : t('preset.save.failed'), 'error');
    }
  }, [selectedOcrHasTypes, selectedHasImageTypes]);

  const fetchEntityTypes = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/custom-types?enabled_only=true');
      if (!res.ok) throw new Error('获取类型失败');
      const data = await safeJson(res);
      const types = data.custom_types || [];
      setEntityTypes(types);
      setSelectedTypes(buildDefaultTextTypeIds(types));
    } catch (err) {
      if (import.meta.env.DEV) console.error('获取实体类型失败', err);
      setEntityTypes([
        { id: 'PERSON', name: '人名', color: '#3B82F6' },
        { id: 'ID_CARD', name: '身份证号', color: '#9333EA' },
        { id: 'PHONE', name: '电话号码', color: '#059669' },
        { id: 'ADDRESS', name: '地址', color: '#0284C7' },
        { id: 'BANK_CARD', name: '银行卡号', color: '#059669' },
        { id: 'CASE_NUMBER', name: '案件编号', color: '#6366F1' },
      ]);
      setSelectedTypes(['PERSON', 'ID_CARD', 'PHONE', 'ADDRESS', 'BANK_CARD', 'CASE_NUMBER']);
    }
  }, []);

  const fetchVisionTypes = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/vision-pipelines');
      if (!res.ok) throw new Error('获取Pipeline配置失败');
      const data: PipelineConfig[] = await safeJson<PipelineConfig[]>(res);
      const normalizedPipelines = data.map(p =>
        p.mode === 'has_image'
          ? { ...p, name: 'HaS Image', description: '本地 YOLO11 微服务（8081），21 类隐私区域分割。' }
          : p
      );
      setPipelines(normalizedPipelines);

      const allTypes: VisionTypeConfig[] = [];
      const ocrHasTypeIds: string[] = [];
      normalizedPipelines.forEach(pipeline => {
        if (pipeline.enabled) {
          pipeline.types.forEach(tp => {
            if (tp.enabled) {
              allTypes.push(tp);
              if (pipeline.mode === 'ocr_has') ocrHasTypeIds.push(tp.id);
            }
          });
        }
      });
      setVisionTypes(allTypes);

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
        .filter(p => p.mode === 'has_image' && p.enabled)
        .flatMap(p => p.types.filter(tp => tp.enabled).map(tp => tp.id));
      const defaultHasImageTypeIds = buildDefaultPipelineTypeIds(normalizedPipelines, 'has_image');
      const savedHasImageTypes =
        localStorage.getItem('hasImageTypes') || localStorage.getItem('glmVisionTypes');
      if (savedHasImageTypes) {
        try {
          const parsed = JSON.parse(savedHasImageTypes);
          updateHasImageTypes(parsed.filter((id: string) => hasImageTypeIds.includes(id)));
        } catch {
          updateHasImageTypes(defaultHasImageTypeIds);
        }
      } else {
        updateHasImageTypes(defaultHasImageTypeIds);
      }
    } catch (err) {
      if (import.meta.env.DEV) console.error('获取图像类型失败', err);
      setVisionTypes([
        { id: 'PERSON', name: '人名/签名', color: '#3B82F6' },
        { id: 'ID_CARD', name: '身份证号', color: '#9333EA' },
        { id: 'PHONE', name: '电话号码', color: '#059669' },
      ]);
      updateOcrHasTypes(['PERSON', 'ID_CARD', 'PHONE']);
      updateHasImageTypes([]);
    }
  }, [updateOcrHasTypes, updateHasImageTypes]);

  // Load on mount
  useEffect(() => {
    fetchEntityTypes();
    fetchVisionTypes();
  }, [fetchEntityTypes, fetchVisionTypes]);

  // Refresh on window focus
  useEffect(() => {
    const handleFocus = () => {
      fetchEntityTypes();
      fetchVisionTypes();
    };
    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, [fetchEntityTypes, fetchVisionTypes]);

  // Bridge init: apply active presets from other pages on data ready
  const bridgeInitRef = useRef(false);
  useEffect(() => {
    if (bridgeInitRef.current) return;
    if (!playgroundPresets.length || !entityTypes.length) return;
    const tid = getActivePresetTextId();
    if (tid) {
      const p = playgroundPresets.find(x => x.id === tid && presetAppliesText(x));
      if (p) applyTextPresetToPlayground(p);
    }
    const vid = getActivePresetVisionId();
    if (vid && pipelines.length) {
      const p = playgroundPresets.find(x => x.id === vid && presetAppliesVision(x));
      if (p) applyVisionPresetToPlayground(p);
    }
    bridgeInitRef.current = true;
  }, [
    playgroundPresets,
    entityTypes,
    pipelines,
    applyTextPresetToPlayground,
    applyVisionPresetToPlayground,
  ]);

  const sortedEntityTypes = useMemo(
    () =>
      [...entityTypes].sort((a, b) => {
        const aRegex = a.regex_pattern ? 1 : 0;
        const bRegex = b.regex_pattern ? 1 : 0;
        if (aRegex !== bRegex) return bRegex - aRegex;
        return a.name.localeCompare(b.name);
      }),
    [entityTypes]
  );

  const playgroundTextGroups = useMemo(() => {
    const regex = sortedEntityTypes.filter(t => !!t.regex_pattern);
    const llm = sortedEntityTypes.filter(t => t.use_llm);
    const other = sortedEntityTypes.filter(t => !t.regex_pattern && !t.use_llm);
    return [
      { key: 'regex' as const, label: '正则识别', types: regex },
      { key: 'llm' as const, label: '语义识别', types: llm },
      { key: 'other' as const, label: '其他', types: other },
    ].filter(g => g.types.length > 0);
  }, [sortedEntityTypes]);

  const setPlaygroundTextTypeGroupSelection = useCallback(
    (ids: string[], turnOn: boolean) => {
      clearPlaygroundTextPresetTracking();
      setSelectedTypes(prev => {
        if (turnOn) {
          const next = new Set(prev);
          ids.forEach(id => next.add(id));
          return [...next];
        }
        return prev.filter(id => !ids.includes(id));
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
          ? selectedOcrHasTypes.filter(t => t !== typeId)
          : [...selectedOcrHasTypes, typeId];
        updateOcrHasTypes(next);
        return { typeId, wasActive: isActive };
      } else {
        const isActive = selectedHasImageTypes.includes(typeId);
        const next = isActive
          ? selectedHasImageTypes.filter(t => t !== typeId)
          : [...selectedHasImageTypes, typeId];
        updateHasImageTypes(next);
        return { typeId, wasActive: isActive };
      }
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
    selectedTypes,
    setSelectedTypes,
    visionTypes,
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
    clearPlaygroundTextPresetTracking,
    clearPlaygroundVisionPresetTracking,
    sortedEntityTypes,
    playgroundTextGroups,
    setPlaygroundTextTypeGroupSelection,
    toggleVisionType,
    updateOcrHasTypes,
    updateHasImageTypes,
    getTypeConfig: (typeId: string): { name: string; color: string } => {
      const config = entityTypes.find(t => t.id === typeId);
      return config || { name: typeId, color: '#6366F1' };
    },
    getVisionTypeConfig: (typeId: string): { name: string; color: string } => {
      const config = visionTypes.find(t => t.id === typeId);
      return config || { name: typeId, color: '#6366F1' };
    },
  };
}
