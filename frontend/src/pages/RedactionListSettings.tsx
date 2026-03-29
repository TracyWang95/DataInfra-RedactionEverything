import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { fetchWithTimeout } from '../utils/fetchWithTimeout';
import {
  fetchPresets,
  createPreset,
  updatePreset,
  deletePreset,
  type RecognitionPreset,
  type PresetPayload,
  type PresetKind,
  presetAppliesText,
  presetAppliesVision,
} from '../services/presetsApi';
import {
  getActivePresetTextId,
  getActivePresetVisionId,
  setActivePresetTextId,
  setActivePresetVisionId,
} from '../services/activePresetBridge';
import {
  selectableCardClass,
  selectableCheckboxClass,
  type SelectionVariant,
} from '../ui/selectionClasses';

interface EntityTypeConfig {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
  order?: number;
  tag_template?: string | null;
}

interface PipelineTypeConfig {
  id: string;
  name: string;
  description?: string;
  examples?: string[];
  color: string;
  enabled: boolean;
  order: number;
}

interface PipelineConfig {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: PipelineTypeConfig[];
}

function presetKindLabel(k?: PresetKind): string {
  const x = k ?? 'full';
  if (x === 'text') return '文本';
  if (x === 'vision') return '图像';
  return '组合';
}

const previewChipClass =
  'inline-flex min-h-[1.625rem] items-center justify-center rounded-lg border px-2.5 py-1 text-center text-2xs font-medium leading-snug shadow-sm';

const redactionOutlineButtonClass =
  'redaction-btn-outline inline-flex items-center justify-center rounded-md border px-2.5 py-1.5 text-caption font-medium';

const redactionPrimaryButtonClass =
  'redaction-btn-primary inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50';

const redactionDangerButtonClass =
  'redaction-btn-danger inline-flex items-center justify-center rounded-md border px-2.5 py-1.5 text-xs font-medium';

const redactionFieldClass =
  'redaction-field w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-800';

function PresetPreviewExpandBody({
  p,
  entityTypes,
  pipelines,
}: {
  p: RecognitionPreset;
  entityTypes: EntityTypeConfig[];
  pipelines: PipelineConfig[];
}) {
  const ocrPipe = pipelines.find(pl => pl.mode === 'ocr_has');
  const imgPipe = pipelines.find(pl => pl.mode === 'has_image');

  return (
    <div className="space-y-4 text-left">
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-b border-gray-100 pb-2 text-2xs text-gray-600">
        <span>
          <span className="text-gray-400">种类：</span>
          {presetKindLabel(p.kind)}
        </span>
        {(p.kind ?? 'full') === 'full' && (
          <span>
            <span className="text-gray-400">替换模式：</span>
            {p.replacementMode}
          </span>
        )}
      </div>

      {presetAppliesText(p) && (
        <>
          {(() => {
            const regexIds = p.selectedEntityTypeIds.filter(
              id => !!entityTypes.find(t => t.id === id)?.regex_pattern
            );
            const semIds = p.selectedEntityTypeIds.filter(id => {
              const t = entityTypes.find(x => x.id === id);
              return !!(t?.use_llm && !t.regex_pattern);
            });
            return (
              <>
                <div>
                  <p className="mb-2 flex items-baseline gap-2 text-2xs font-semibold uppercase tracking-wide text-gray-500">
                    <span>正则规则</span>
                    <span className="tabular-nums font-normal normal-case text-gray-400">({regexIds.length})</span>
                  </p>
                  {regexIds.length === 0 ? (
                    <p className="text-2xs text-gray-400">暂无</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                      {regexIds.map(id => (
                        <span
                          key={`rx-${id}`}
                          className={`${previewChipClass} border-slate-200/90 bg-white text-gray-800`}
                        >
                          {entityTypes.find(t => t.id === id)?.name ?? id}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <p className="mb-2 flex items-baseline gap-2 text-2xs font-semibold uppercase tracking-wide text-gray-500">
                    <span>AI 语义（HaS）</span>
                    <span className="tabular-nums font-normal normal-case text-gray-400">({semIds.length})</span>
                  </p>
                  {semIds.length === 0 ? (
                    <p className="text-2xs text-gray-400">暂无</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                      {semIds.map(id => (
                        <span
                          key={`sem-${id}`}
                          className={`${previewChipClass} border-slate-200/90 bg-white text-gray-800`}
                        >
                          {entityTypes.find(t => t.id === id)?.name ?? id}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </>
            );
          })()}
        </>
      )}

      {presetAppliesVision(p) && (
        <>
          <div>
            <p className="mb-2 flex items-baseline gap-2 text-2xs font-semibold uppercase tracking-wide text-gray-500">
              <span>OCR + HaS</span>
              <span className="tabular-nums font-normal normal-case text-gray-400">({p.ocrHasTypes.length})</span>
            </p>
            {p.ocrHasTypes.length === 0 ? (
              <p className="text-2xs text-gray-400">暂无</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                {p.ocrHasTypes.map(id => (
                  <span
                    key={`ocr-${id}`}
                    className={`${previewChipClass} border-gray-200 bg-white text-gray-800`}
                  >
                    {ocrPipe?.types.find(t => t.id === id)?.name ?? id}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div>
            <p className="mb-2 flex items-baseline gap-2 text-2xs font-semibold uppercase tracking-wide text-gray-500">
              <span>HaS Image</span>
              <span className="tabular-nums font-normal normal-case text-gray-400">({p.hasImageTypes.length})</span>
            </p>
            {p.hasImageTypes.length === 0 ? (
              <p className="text-2xs text-gray-400">暂无</p>
            ) : (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                {p.hasImageTypes.map(id => (
                  <span
                    key={`hi-${id}`}
                    className={`${previewChipClass} border-gray-200 bg-white text-gray-800`}
                  >
                    {imgPipe?.types.find(t => t.id === id)?.name ?? id}
                  </span>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export const RedactionListSettings: React.FC = () => {
  const [entityTypes, setEntityTypes] = useState<EntityTypeConfig[]>([]);
  const [pipelines, setPipelines] = useState<PipelineConfig[]>([]);
  const [loading, setLoading] = useState(true);

  const [recognitionPresets, setRecognitionPresets] = useState<RecognitionPreset[]>([]);
  const [presetModalOpen, setPresetModalOpen] = useState(false);
  const [editingPresetId, setEditingPresetId] = useState<string | null>(null);
  const [presetForm, setPresetForm] = useState<PresetPayload>({
    name: '',
    kind: 'full',
    selectedEntityTypeIds: [],
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
  });
  const [presetSaving, setPresetSaving] = useState(false);
  /** 与 Playground / 批量向导 localStorage 同步的「当前选用」 */
  const [bridgeText, setBridgeText] = useState<string>(() => getActivePresetTextId() ?? '');
  const [bridgeVision, setBridgeVision] = useState<string>(() => getActivePresetVisionId() ?? '');
  /** 清单行「预览」行内展开；键含列前缀避免组合预设在两列同时展开 */
  const [expandedPresetKey, setExpandedPresetKey] = useState<string | null>(null);

  const reloadPresets = useCallback(async () => {
    try {
      const list = await fetchPresets();
      setRecognitionPresets(list);
    } catch {
      setRecognitionPresets([]);
    }
  }, []);

  useEffect(() => {
    fetchEntityTypes();
    fetchPipelines();
    void reloadPresets();
  }, [reloadPresets]);

  useEffect(() => {
    const on = () => {
      setBridgeText(getActivePresetTextId() ?? '');
      setBridgeVision(getActivePresetVisionId() ?? '');
    };
    window.addEventListener('datainfra-redaction-active-preset', on);
    return () => window.removeEventListener('datainfra-redaction-active-preset', on);
  }, []);

  const buildDefaultPresetForm = useCallback(
    (kind: PresetKind = 'full'): PresetPayload => {
      const enabledText = entityTypes.filter(t => t.enabled !== false).map(t => t.id);
      const ocrIds = pipelines
        .filter(p => p.mode === 'ocr_has' && p.enabled)
        .flatMap(p => p.types.filter(t => t.enabled).map(t => t.id));
      const hiIds = pipelines
        .filter(p => p.mode === 'has_image' && p.enabled)
        .flatMap(p => p.types.filter(t => t.enabled).map(t => t.id));
      if (kind === 'text') {
        return {
          name: '',
          kind: 'text',
          selectedEntityTypeIds: enabledText,
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
          hasImageTypes: hiIds,
          replacementMode: 'structured',
        };
      }
      return {
        name: '',
        kind: 'full',
        selectedEntityTypeIds: enabledText,
        ocrHasTypes: ocrIds,
        hasImageTypes: hiIds,
        replacementMode: 'structured',
      };
    },
    [entityTypes, pipelines]
  );

  const openNewPresetModal = (kind: PresetKind) => {
    setExpandedPresetKey(null);
    setEditingPresetId(null);
    setPresetForm(buildDefaultPresetForm(kind));
    setPresetModalOpen(true);
  };

  const openEditPreset = (p: RecognitionPreset) => {
    setExpandedPresetKey(null);
    setEditingPresetId(p.id);
    const k = p.kind ?? 'full';
    setPresetForm({
      name: p.name,
      kind: k,
      selectedEntityTypeIds: [...p.selectedEntityTypeIds],
      ocrHasTypes: [...p.ocrHasTypes],
      hasImageTypes: [...p.hasImageTypes],
      replacementMode: p.replacementMode,
    });
    setPresetModalOpen(true);
  };

  const textPresetsList = useMemo(
    () => recognitionPresets.filter(presetAppliesText),
    [recognitionPresets]
  );
  const visionPresetsList = useMemo(
    () => recognitionPresets.filter(presetAppliesVision),
    [recognitionPresets]
  );

  /** 与「识别项配置」文本 Tab 一致：正则 / 语义 分栏勾选 */
  const textRegexTypesForModal = useMemo(
    () => entityTypes.filter(t => t.enabled !== false && t.regex_pattern),
    [entityTypes]
  );
  const textSemanticTypesForModal = useMemo(
    () => entityTypes.filter(t => t.enabled !== false && t.use_llm && !t.regex_pattern),
    [entityTypes]
  );

  const summaryTextLabel = useMemo(() => {
    if (!bridgeText) return '默认';
    return textPresetsList.find(p => p.id === bridgeText)?.name ?? bridgeText;
  }, [bridgeText, textPresetsList]);

  const summaryVisionLabel = useMemo(() => {
    if (!bridgeVision) return '默认';
    return visionPresetsList.find(p => p.id === bridgeVision)?.name ?? bridgeVision;
  }, [bridgeVision, visionPresetsList]);

  const savePresetModal = async () => {
    if (!presetForm.name.trim()) {
      alert('请填写预设名称');
      return;
    }
    const normalized: PresetPayload =
      presetForm.kind === 'text'
        ? { ...presetForm, ocrHasTypes: [], hasImageTypes: [], replacementMode: 'structured' }
        : presetForm.kind === 'vision'
          ? { ...presetForm, selectedEntityTypeIds: [], replacementMode: 'structured' }
          : presetForm;
    setPresetSaving(true);
    try {
      if (editingPresetId) {
        await updatePreset(editingPresetId, normalized);
      } else {
        const created = await createPreset(normalized);
        const k = normalized.kind;
        if (k === 'text' || k === 'full') {
          setActivePresetTextId(created.id);
          setBridgeText(created.id);
        }
        if (k === 'vision' || k === 'full') {
          setActivePresetVisionId(created.id);
          setBridgeVision(created.id);
        }
      }
      setPresetModalOpen(false);
      await reloadPresets();
    } catch (e) {
      alert(e instanceof Error ? e.message : '保存失败');
    } finally {
      setPresetSaving(false);
    }
  };

  const removePreset = async (id: string) => {
    if (!confirm('确定删除该预设？')) return;
    try {
      await deletePreset(id);
      setExpandedPresetKey(k => (k === `text:${id}` || k === `vision:${id}` ? null : k));
      await reloadPresets();
      setBridgeText(t => {
        if (t === id) {
          setActivePresetTextId(null);
          return '';
        }
        return t;
      });
      setBridgeVision(v => {
        if (v === id) {
          setActivePresetVisionId(null);
          return '';
        }
        return v;
      });
    } catch (e) {
      alert(e instanceof Error ? e.message : '删除失败');
    }
  };

  const fetchEntityTypes = async () => {
    try {
      setLoading(true);
      const res = await fetchWithTimeout('/api/v1/custom-types?enabled_only=false', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('获取失败');
      const data = await res.json();
      setEntityTypes(data.custom_types || []);
    } catch (err) {
      console.error('获取实体类型失败', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchPipelines = async () => {
    try {
      const res = await fetchWithTimeout('/api/v1/vision-pipelines', { timeoutMs: 25000 });
      if (!res.ok) throw new Error('获取失败');
      const data = await res.json();
      const normalizedPipelines = (data || []).map((p: PipelineConfig) =>
        p.mode === 'has_image'
          ? {
              ...p,
              name: 'HaS Image',
              description: '使用视觉语言模型识别签名、印章、手写等视觉信息。',
            }
          : p
      );
      setPipelines(normalizedPipelines);
    } catch (err) {
      console.error('获取Pipeline配置失败', err);
    }
  };

  return (
    <div className="redaction-root flex-1 min-h-0 min-w-0 flex flex-col overflow-hidden bg-[#fafafa]">
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden px-3 py-2 sm:px-4 sm:py-3 w-full max-w-[min(100%,1920px)] mx-auto">
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <div className="w-7 h-7 border-2 border-[#e5e5e5] border-t-[#0a0a0a] rounded-full animate-spin" />
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col gap-2 overflow-hidden">
          <div className="redaction-surface shrink-0 bg-white rounded-lg border border-gray-200 p-3 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-gray-900 text-sm">脱敏清单配置</h3>
                <p className="text-2xs text-gray-500 mt-0.5 leading-snug">
                  共用 <code className="text-2xs bg-gray-100 px-1 rounded">/api/v1/presets</code>
                  ；选用同步 Playground / 批量向导（新会话）。
                </p>
              </div>
              <div className="flex flex-wrap flex-col sm:flex-row items-stretch sm:items-end gap-2 shrink-0 max-w-full">
                <div className="redaction-summary text-2xs rounded-lg border border-gray-200/80 bg-white px-2.5 py-2 min-w-[min(100%,15rem)]">
                  <p className="text-[0.65rem] font-semibold text-gray-500 uppercase tracking-wide mb-1">当前选用</p>
                  <p className="text-gray-800 leading-snug">
                    <span className="text-gray-500">文本链：</span>
                    <span className="font-medium">{summaryTextLabel}</span>
                  </p>
                  <p className="text-gray-800 leading-snug mt-0.5">
                    <span className="text-gray-500">图像链：</span>
                    <span className="font-medium">{summaryVisionLabel}</span>
                  </p>
                  <p className="text-gray-400 mt-1 pt-1 border-t border-gray-100 leading-tight">
                    已保存 {textPresetsList.length} 个文本清单 · {visionPresetsList.length} 个图像预设
                  </p>
                </div>
                <div className="flex flex-wrap gap-1.5 justify-end sm:justify-start">
                  <button
                    type="button"
                    onClick={() => openNewPresetModal('text')}
                    className={redactionOutlineButtonClass}
                  >
                    + 文本清单
                  </button>
                  <button
                    type="button"
                    onClick={() => openNewPresetModal('vision')}
                    className={redactionOutlineButtonClass}
                  >
                    + 图像预设
                  </button>
                </div>
              </div>
            </div>
            <div className="grid gap-2 md:grid-cols-2 mb-2">
              <div className="flex flex-col gap-0.5">
                <span className="text-2xs font-medium text-gray-600">选用 · 文本链</span>
                <select
                  className={redactionFieldClass}
                  value={bridgeText}
                  onChange={e => {
                    const v = e.target.value;
                    setBridgeText(v);
                    setActivePresetTextId(v || null);
                  }}
                >
                  <option value="">默认（全选启用类型，与识别项一致）</option>
                  {textPresetsList.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.kind === 'full' ? '（组合）' : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-2xs font-medium text-gray-600">选用 · 图像链</span>
                <select
                  className={redactionFieldClass}
                  value={bridgeVision}
                  onChange={e => {
                    const v = e.target.value;
                    setBridgeVision(v);
                    setActivePresetVisionId(v || null);
                  }}
                >
                  <option value="">默认（OCR+HaS 与 HaS 图像全选）</option>
                  {visionPresetsList.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                      {p.kind === 'full' ? '（组合）' : ''}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <div className="min-h-0 flex flex-col">
                <h4 className="text-2xs font-semibold text-gray-500 uppercase tracking-wide mb-1">文本脱敏清单</h4>
                {textPresetsList.length === 0 ? (
                  <p className="text-caption text-gray-400 py-1 leading-snug">
                    暂无；与「识别项配置」中正则 / 语义类型对应，在此命名并勾选后保存。
                  </p>
                ) : (
                  <ul className="divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-100 text-caption max-h-[min(55vh,520px)]">
                    {textPresetsList.map(p => {
                      const rowKey = `text:${p.id}`;
                      const rxN = p.selectedEntityTypeIds.filter(
                        id => !!entityTypes.find(t => t.id === id)?.regex_pattern
                      ).length;
                      const semN = p.selectedEntityTypeIds.filter(id => {
                        const t = entityTypes.find(x => x.id === id);
                        return !!(t?.use_llm && !t.regex_pattern);
                      }).length;
                      return (
                      <li key={p.id} className="bg-[#fafafa]">
                        <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1.5">
                          <div>
                            <span className="font-medium text-gray-900">{p.name}</span>
                            <span className="ml-2 text-xs text-gray-400">
                              {p.kind === 'full' ? '组合 · ' : ''}
                              正则 {rxN} · 语义 {semN}
                              {p.kind === 'full' ? ` · ${p.replacementMode}` : ''}
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => setExpandedPresetKey(cur => (cur === rowKey ? null : rowKey))}
                              className={redactionOutlineButtonClass}
                            >
                              {expandedPresetKey === rowKey ? '收起' : '预览'}
                            </button>
                            <button
                              type="button"
                              onClick={() => openEditPreset(p)}
                              className={redactionOutlineButtonClass}
                            >
                              编辑
                            </button>
                            <button
                              type="button"
                              onClick={() => removePreset(p.id)}
                              className={redactionDangerButtonClass}
                            >
                              删除
                            </button>
                          </div>
                        </div>
                        {expandedPresetKey === rowKey && (
                          <div className="border-t border-gray-100/80 bg-white px-2 pb-3 pt-2">
                            <div className="rounded-lg border border-gray-200/90 bg-white px-3 py-3 shadow-sm">
                              <PresetPreviewExpandBody p={p} entityTypes={entityTypes} pipelines={pipelines} />
                            </div>
                          </div>
                        )}
                      </li>
                    );
                    })}
                  </ul>
                )}
              </div>
              <div className="min-h-0 flex flex-col">
                <h4 className="text-2xs font-semibold text-gray-500 uppercase tracking-wide mb-1">图像脱敏配置清单</h4>
                {visionPresetsList.length === 0 ? (
                  <p className="text-caption text-gray-400 py-1 leading-snug">暂无；可在 Playground 另存为图像预设。</p>
                ) : (
                  <ul className="divide-y divide-gray-100 overflow-y-auto rounded-md border border-gray-100 text-caption max-h-[min(55vh,520px)]">
                    {visionPresetsList.map(p => {
                      const rowKey = `vision:${p.id}`;
                      return (
                      <li key={p.id} className="bg-[#fafafa]">
                        <div className="flex flex-wrap items-center justify-between gap-1 px-2 py-1.5">
                          <div>
                            <span className="font-medium text-gray-900">{p.name}</span>
                            <span className="ml-2 text-xs text-gray-400">
                              {p.kind === 'full' ? '组合 · ' : ''}
                              OCR {p.ocrHasTypes.length} · 图像 {p.hasImageTypes.length}
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => setExpandedPresetKey(cur => (cur === rowKey ? null : rowKey))}
                              className={redactionOutlineButtonClass}
                            >
                              {expandedPresetKey === rowKey ? '收起' : '预览'}
                            </button>
                            <button
                              type="button"
                              onClick={() => openEditPreset(p)}
                              className={redactionOutlineButtonClass}
                            >
                              编辑
                            </button>
                            <button
                              type="button"
                              onClick={() => removePreset(p.id)}
                              className={redactionDangerButtonClass}
                            >
                              删除
                            </button>
                          </div>
                        </div>
                        {expandedPresetKey === rowKey && (
                          <div className="border-t border-gray-100/80 bg-white px-2 pb-3 pt-2">
                            <div className="rounded-lg border border-gray-200/90 bg-white px-3 py-3 shadow-sm">
                              <PresetPreviewExpandBody p={p} entityTypes={entityTypes} pipelines={pipelines} />
                            </div>
                          </div>
                        )}
                      </li>
                    );
                    })}
                  </ul>
                )}
              </div>
            </div>
          </div>

        </div>
      )}

            {presetModalOpen && (
        <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4 sm:p-6">
          <div className="redaction-modal bg-white rounded-xl w-full max-w-[min(100%,56rem)] min-w-0 max-h-[92vh] overflow-hidden flex flex-col shadow-xl border border-gray-200/80">
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                {editingPresetId
                  ? presetForm.kind === 'text'
                    ? '编辑文本清单'
                    : presetForm.kind === 'vision'
                      ? '编辑图像预设'
                      : '编辑组合预设'
                  : presetForm.kind === 'text'
                    ? '新建文本清单'
                    : presetForm.kind === 'vision'
                      ? '新建图像预设'
                      : '新建组合预设'}
              </h3>
              <button
                type="button"
                onClick={() => setPresetModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-xl leading-none px-1"
                aria-label="关闭"
              >
                ×
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6 space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">名称 *</label>
                <input
                  type="text"
                  value={presetForm.name}
                  onChange={e => setPresetForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full px-3 py-2.5 border border-gray-200 rounded-lg text-sm"
                  placeholder="如：合同默认、仅人名与金额"
                />
              </div>
              {(presetForm.kind === 'text' || presetForm.kind === 'full') && (
                <>
                  {presetForm.kind === 'full' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">替换模式</label>
                      <select
                        value={presetForm.replacementMode}
                        onChange={e =>
                          setPresetForm(f => ({
                            ...f,
                            replacementMode: e.target.value as PresetPayload['replacementMode'],
                          }))
                        }
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                      >
                        <option value="structured">structured（结构化）</option>
                        <option value="smart">smart（智能）</option>
                        <option value="mask">mask（掩码）</option>
                      </select>
                    </div>
                  )}
                  <p className="text-2xs text-[#737373] leading-snug">
                    类型与「识别项配置 → 文本识别规则」一致：正则与 AI 语义分两路勾选（同图像预设两路结构）。
                  </p>
                  <div>
                    <p className="text-sm font-semibold text-[#1d1d1f] mb-2 pl-2 border-l-[3px] border-[#d4d4d4]">
                      正则规则
                      <span className="ml-1.5 text-xs font-normal tabular-nums text-[#a3a3a3]">
                        ({textRegexTypesForModal.length})
                      </span>
                    </p>
                    <p className="text-2xs text-[#a3a3a3] mb-2">每条为一条正则模式，与设置页「正则」Tab 一致。</p>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 max-h-[min(40vh,360px)] overflow-y-auto border border-black/[0.06] rounded-xl p-3 bg-white/70">
                      {textRegexTypesForModal.map(t => {
                        const checked = presetForm.selectedEntityTypeIds.includes(t.id);
                        return (
                          <label
                            key={`rx-${t.id}`}
                            className={`flex items-center gap-2 text-xs px-2.5 py-2 cursor-pointer transition-colors ${selectableCardClass(checked, 'regex')}`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() =>
                                setPresetForm(f => ({
                                  ...f,
                                  selectedEntityTypeIds: f.selectedEntityTypeIds.includes(t.id)
                                    ? f.selectedEntityTypeIds.filter(x => x !== t.id)
                                    : [...f.selectedEntityTypeIds, t.id],
                                }))
                              }
                              className={selectableCheckboxClass('regex', 'md')}
                            />
                            <span className="truncate min-w-0">{t.name}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-[#1d1d1f] mb-2 pl-2 border-l-[3px] border-[#d4d4d4]">
                      AI 语义（HaS）
                      <span className="ml-1.5 text-xs font-normal tabular-nums text-[#a3a3a3]">
                        ({textSemanticTypesForModal.length})
                      </span>
                    </p>
                    <p className="text-2xs text-[#a3a3a3] mb-2">由模型识别语义类型，与设置页「语义」Tab 一致。</p>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 max-h-[min(40vh,360px)] overflow-y-auto border border-black/[0.06] rounded-xl p-3 bg-white/70">
                      {textSemanticTypesForModal.map(t => {
                        const checked = presetForm.selectedEntityTypeIds.includes(t.id);
                        return (
                          <label
                            key={`sem-${t.id}`}
                            className={`flex items-center gap-2 text-xs px-2.5 py-2 cursor-pointer transition-colors ${selectableCardClass(checked, 'ner')}`}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() =>
                                setPresetForm(f => ({
                                  ...f,
                                  selectedEntityTypeIds: f.selectedEntityTypeIds.includes(t.id)
                                    ? f.selectedEntityTypeIds.filter(x => x !== t.id)
                                    : [...f.selectedEntityTypeIds, t.id],
                                }))
                              }
                              className={selectableCheckboxClass('ner', 'md')}
                            />
                            <span className="truncate min-w-0">{t.name}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
              {(presetForm.kind === 'vision' || presetForm.kind === 'full') &&
                pipelines.map(p =>
                p.enabled ? (
                  <div key={p.mode}>
                    <p
                      className={`text-sm font-semibold text-[#1d1d1f] mb-2 pl-2 border-l-[3px] ${
                        p.mode === 'ocr_has' ? 'border-[#34C759]' : 'border-[#AF52DE]'
                      }`}
                    >
                      {p.mode === 'ocr_has' ? '图片类文本（OCR+HaS）' : '图像特征（HaS Image）'}
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 max-h-[min(48vh,420px)] overflow-y-auto border border-black/[0.06] rounded-xl p-3 bg-white/70">
                      {p.types
                        .filter(t => t.enabled)
                        .map(t => {
                          const active =
                            p.mode === 'ocr_has'
                              ? presetForm.ocrHasTypes.includes(t.id)
                              : presetForm.hasImageTypes.includes(t.id);
                          const v: SelectionVariant = p.mode === 'ocr_has' ? 'ner' : 'yolo';
                          return (
                            <label
                              key={t.id}
                              className={`flex items-center gap-2 text-xs px-2.5 py-2 text-left cursor-pointer transition-colors ${selectableCardClass(active, v)}`}
                            >
                              <input
                                type="checkbox"
                                checked={active}
                                onChange={() =>
                                  setPresetForm(f => {
                                    if (p.mode === 'ocr_has') {
                                      const next = active
                                        ? f.ocrHasTypes.filter(x => x !== t.id)
                                        : [...f.ocrHasTypes, t.id];
                                      return { ...f, ocrHasTypes: next };
                                    }
                                    const next = active
                                      ? f.hasImageTypes.filter(x => x !== t.id)
                                      : [...f.hasImageTypes, t.id];
                                    return { ...f, hasImageTypes: next };
                                  })
                                }
                                className={selectableCheckboxClass(v, 'md')}
                              />
                              <span className="truncate">{t.name}</span>
                            </label>
                          );
                        })}
                    </div>
                  </div>
                ) : null
                )}
            </div>
            <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3 bg-gray-50/50">
              <button
                type="button"
                onClick={() => setPresetModalOpen(false)}
                className="px-4 py-2 text-sm text-gray-600 rounded-lg border border-transparent hover:bg-gray-100"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void savePresetModal()}
                disabled={presetSaving}
                className={redactionPrimaryButtonClass}
              >
                {presetSaving ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}

      </div>
    </div>
  );
};

export default RedactionListSettings;
