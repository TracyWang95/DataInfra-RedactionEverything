import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useParams, useBlocker } from 'react-router-dom';
import { fetchWithTimeout } from '../utils/fetchWithTimeout';
import { useDropzone } from 'react-dropzone';
import ImageBBoxEditor, { type BoundingBox as EditorBox } from '../components/ImageBBoxEditor';
import { getEntityRiskConfig, getEntityTypeName } from '../config/entityTypes';
import { fileApi } from '../services/api';
import type { FileListItem } from '../types';
import { ReplacementMode } from '../types';
import {
  batchExecute,
  batchGetFileRaw,
  batchHybridNer,
  batchParse,
  batchPreviewEntityMap,
  batchVision,
  flattenBoundingBoxesFromStore,
  loadBatchWizardConfig,
  saveBatchWizardConfig,
  type BatchWizardMode,
  type BatchWizardPersistedConfig,
} from '../services/batchPipeline';
import {
  getActivePresetTextId,
  getActivePresetVisionId,
  setActivePresetTextId,
  setActivePresetVisionId,
} from '../services/activePresetBridge';
import {
  fetchPresets,
  presetAppliesText,
  presetAppliesVision,
  type RecognitionPreset,
} from '../services/presetsApi';
import {
  formCheckboxClass,
  selectableCardClassCompact,
  textGroupKeyToVariant,
  type SelectionVariant,
} from '../ui/selectionClasses';
import {
  buildFallbackPreviewEntityMap,
  buildTextSegments,
  mergePreviewMapWithDocumentSlices,
} from '../utils/textRedactionSegments';

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

type Step = 1 | 2 | 3 | 4 | 5;

interface PipelineCfg {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: { id: string; name: string; color: string; enabled: boolean }[];
}

interface TextEntityType {
  id: string;
  name: string;
  color: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
}

interface BatchRow extends FileListItem {
  analyzeStatus: 'pending' | 'parsing' | 'analyzing' | 'done' | 'failed';
  analyzeError?: string;
  isImageMode?: boolean;
}

type ReviewEntity = {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  selected: boolean;
  page?: number;
  confidence?: number;
  source?: string;
  coref_id?: string | null;
};

const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: '配置' },
  { n: 2, label: '上传' },
  { n: 3, label: '批量识别' },
  { n: 4, label: '审阅确认' },
  { n: 5, label: '导出' },
];

function defaultConfig(): BatchWizardPersistedConfig {
  return {
    selectedEntityTypeIds: [],
    ocrHasTypes: [],
    hasImageTypes: [],
    replacementMode: 'structured',
    imageRedactionMethod: 'mosaic',
    imageRedactionStrength: 25,
    imageFillColor: '#000000',
    presetTextId: null,
    presetVisionId: null,
    presetId: null,
  };
}

function normalizeReviewEntity(e: ReviewEntity): ReviewEntity {
  const start = Math.max(0, Math.floor(Number(e.start) || 0));
  const end = Math.max(start, Math.floor(Number(e.end) || 0));
  return {
    ...e,
    id: String(e.id ?? ''),
    text: String(e.text ?? ''),
    type: String(e.type ?? 'CUSTOM'),
    start,
    end,
    page: Math.max(1, Math.floor(Number(e.page) || 1)),
    confidence: typeof e.confidence === 'number' && !Number.isNaN(e.confidence) ? e.confidence : 1,
    selected: e.selected !== false,
  };
}

function buildPreviewPayload(entities: ReviewEntity[]) {
  return entities.map(e => {
    const n = normalizeReviewEntity(e);
    return {
      id: n.id,
      text: n.text,
      type: n.type,
      start: n.start,
      end: n.end,
      page: n.page,
      confidence: n.confidence,
      selected: n.selected,
      source: n.source,
      coref_id: n.coref_id,
    };
  });
}

async function fetchBatchPreviewMap(
  entities: ReviewEntity[],
  replacementMode: BatchWizardPersistedConfig['replacementMode']
): Promise<Record<string, string>> {
  const payload = buildPreviewPayload(entities).map(p => ({ ...p, selected: true }));
  if (payload.length === 0) return {};
  const replacement_mode =
    replacementMode === 'smart'
      ? ReplacementMode.SMART
      : replacementMode === 'mask'
        ? ReplacementMode.MASK
        : ReplacementMode.STRUCTURED;
  const modeKey: 'structured' | 'smart' | 'mask' =
    replacementMode === 'smart' ? 'smart' : replacementMode === 'mask' ? 'mask' : 'structured';
  try {
    const map = await batchPreviewEntityMap({
      entities: payload,
      config: {
        replacement_mode,
        entity_types: [],
        custom_replacements: {},
      },
    });
    if (map && Object.keys(map).length > 0) {
      return map;
    }
  } catch {
    /* 后端不可用时使用本地与 execute 一致的占位逻辑 */
  }
  return buildFallbackPreviewEntityMap(
    payload.map(p => ({ text: p.text, type: p.type, selected: p.selected })),
    modeKey
  );
}

function applyTextPresetFields(
  p: RecognitionPreset,
  textTypes: TextEntityType[]
): Pick<BatchWizardPersistedConfig, 'selectedEntityTypeIds' | 'presetTextId'> &
  Partial<Pick<BatchWizardPersistedConfig, 'replacementMode'>> {
  const textIds = new Set(textTypes.map(t => t.id));
  const base = {
    selectedEntityTypeIds: p.selectedEntityTypeIds.filter((id: string) => textIds.has(id)),
    presetTextId: p.id,
  };
  if ((p.kind ?? 'full') === 'text') {
    return base;
  }
  return { ...base, replacementMode: p.replacementMode };
}

/** 批量步骤 ① 只读：方格气泡，样式与可勾选时「已选」一致，不可修改 */
function ReadonlyTypeBubble({ name, variant }: { name: string; variant: SelectionVariant }) {
  return (
    <div
      className={`flex items-center gap-1 text-2xs min-w-0 cursor-default !px-1.5 !py-1 ${selectableCardClassCompact(true, variant)}`}
      title={name}
    >
      <span
        className={`flex h-3 w-3 shrink-0 items-center justify-center rounded border text-[8px] leading-none font-semibold ${
          variant === 'regex'
            ? 'border-[#007AFF]/45 bg-white/80 text-[#007AFF]'
            : variant === 'ner'
              ? 'border-[#34C759]/45 bg-white/80 text-[#34C759]'
              : 'border-[#AF52DE]/45 bg-white/80 text-[#AF52DE]'
        }`}
        aria-hidden
      >
        ✓
      </span>
      <span className="truncate leading-snug">{name}</span>
    </div>
  );
}

function applyVisionPresetFields(
  p: RecognitionPreset,
  pipelines: PipelineCfg[]
): Pick<BatchWizardPersistedConfig, 'ocrHasTypes' | 'hasImageTypes' | 'presetVisionId'> {
  const ocrIds = pipelines
    .filter(pl => pl.mode === 'ocr_has' && pl.enabled)
    .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id));
  const hiIds = pipelines
    .filter(pl => pl.mode === 'has_image' && pl.enabled)
    .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id));
  return {
    ocrHasTypes: p.ocrHasTypes.filter(id => ocrIds.includes(id)),
    hasImageTypes: p.hasImageTypes.filter(id => hiIds.includes(id)),
    presetVisionId: p.id,
  };
}

function PresetDetailBlock({
  cfg,
  textTypes,
  pipelines,
  allPresets,
  scope,
  onReplacementModeChange,
  onVisionImagePatch,
}: {
  cfg: BatchWizardPersistedConfig;
  textTypes: TextEntityType[];
  pipelines: PipelineCfg[];
  allPresets: RecognitionPreset[];
  /** 与批量向导路由一致：只展示当前链路的预设详情 */
  scope: 'text' | 'image';
  onReplacementModeChange: (mode: BatchWizardPersistedConfig['replacementMode']) => void;
  onVisionImagePatch: (
    patch: Partial<
      Pick<BatchWizardPersistedConfig, 'imageRedactionMethod' | 'imageRedactionStrength' | 'imageFillColor'>
    >
  ) => void;
}) {
  const visionName = (mode: 'ocr_has' | 'has_image', id: string) => {
    const pl = pipelines.find(p => p.mode === mode);
    return pl?.types.find(t => t.id === id)?.name ?? id;
  };
  const textPresetLabel = cfg.presetTextId
    ? allPresets.find(p => p.id === cfg.presetTextId)?.name ?? cfg.presetTextId
    : null;
  const visionPresetLabel = cfg.presetVisionId
    ? allPresets.find(p => p.id === cfg.presetVisionId)?.name ?? cfg.presetVisionId
    : null;

  const regexTextSelected = textTypes.filter(
    t => cfg.selectedEntityTypeIds.includes(t.id) && !!t.regex_pattern
  );
  const llmTextSelected = textTypes.filter(
    t => cfg.selectedEntityTypeIds.includes(t.id) && t.use_llm
  );
  const otherTextSelected = textTypes.filter(
    t =>
      cfg.selectedEntityTypeIds.includes(t.id) && !t.regex_pattern && !t.use_llm
  );

  const textSections = [
    { key: 'regex' as const, label: '正则规则', sub: 'regex_pattern', types: regexTextSelected },
    { key: 'llm' as const, label: '语义规则', sub: 'use_llm', types: llmTextSelected },
    { key: 'other' as const, label: '其他', sub: '未标注正则或语义', types: otherTextSelected },
  ].filter(s => s.types.length > 0);

  return (
    <div className="text-xs text-[#1d1d1f] space-y-2 border border-black/[0.06] rounded-xl p-2.5 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      {(scope === 'text' ? textPresetLabel : visionPresetLabel) && (
        <div className="text-2xs text-gray-500 space-y-0.5 pb-2 border-b border-gray-100">
          {scope === 'text' && textPresetLabel && <div>文本预设：{textPresetLabel}</div>}
          {scope === 'image' && visionPresetLabel && <div>图像预设：{visionPresetLabel}</div>}
        </div>
      )}
      {scope === 'text' ? (
        <div className="rounded-lg bg-gray-50/80 border border-gray-100/80 px-2.5 py-1.5 space-y-1.5">
          <div className="space-y-1">
            <p className="text-[0.65rem] font-semibold text-gray-500 uppercase tracking-wide">替换模式</p>
            <div
              className="grid grid-cols-1 min-[380px]:grid-cols-3 gap-1"
              role="radiogroup"
              aria-label="替换模式"
            >
              {(
                [
                  { value: 'structured' as const, label: 'structured（结构化）' },
                  { value: 'smart' as const, label: 'smart（智能）' },
                  { value: 'mask' as const, label: 'mask（掩码）' },
                ] as const
              ).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={cfg.replacementMode === value}
                  onClick={() => onReplacementModeChange(value)}
                  className={`text-2xs rounded-lg px-2 py-1.5 border font-medium transition-colors ${
                    cfg.replacementMode === value
                      ? 'border-[#1d1d1f] bg-[#1d1d1f] text-white'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="text-2xs text-gray-500 space-y-0.5 leading-snug">
            <p>
              <span className="text-gray-600 font-medium">structured</span>：语义占位
            </p>
            <p>
              <span className="text-gray-600 font-medium">smart</span>：中文类别编号
            </p>
            <p>
              <span className="text-gray-600 font-medium">mask</span>：部分打星（核对确认脱敏时生效）
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-lg bg-gray-50/80 border border-gray-100/80 px-2.5 py-1.5 space-y-1.5">
          <p className="text-[0.65rem] font-semibold text-gray-500 uppercase tracking-wide">图像脱敏（HaS Image）</p>
          <div className="space-y-1">
            <label className="text-2xs font-medium text-gray-700">方式</label>
            <div
              className="grid grid-cols-1 min-[380px]:grid-cols-3 gap-1"
              role="radiogroup"
              aria-label="图像脱敏方式"
            >
              {(
                [
                  { value: 'mosaic' as const, label: '马赛克' },
                  { value: 'blur' as const, label: '高斯模糊' },
                  { value: 'fill' as const, label: '纯色填充' },
                ] as const
              ).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={(cfg.imageRedactionMethod ?? 'mosaic') === value}
                  onClick={() => onVisionImagePatch({ imageRedactionMethod: value })}
                  className={`text-2xs rounded-lg px-2 py-1.5 border font-medium transition-colors ${
                    (cfg.imageRedactionMethod ?? 'mosaic') === value
                      ? 'border-[#1d1d1f] bg-[#1d1d1f] text-white'
                      : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="text-2xs text-gray-500 space-y-0.5 leading-snug">
            <p>
              <span className="text-gray-600 font-medium">马赛克</span>：按块遮挡敏感区域
            </p>
            <p>
              <span className="text-gray-600 font-medium">高斯模糊</span>：对敏感区域做模糊
            </p>
            <p>
              <span className="text-gray-600 font-medium">纯色填充</span>：用指定颜色覆盖
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-x-2 gap-y-1.5">
            {(cfg.imageRedactionMethod ?? 'mosaic') !== 'fill' && (
              <div className="flex flex-col gap-0.5 flex-1 min-w-[10rem] max-w-sm">
                <label className="text-2xs font-medium text-gray-700">
                  {(cfg.imageRedactionMethod ?? 'mosaic') === 'blur' ? '强度 1–100（模糊）' : '强度 1–100（块）'}
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="range"
                    min={1}
                    max={100}
                    value={cfg.imageRedactionStrength ?? 25}
                    onChange={e =>
                      onVisionImagePatch({ imageRedactionStrength: Number(e.target.value) })
                    }
                    className="flex-1 min-w-0 accent-[#007AFF] h-1.5"
                    aria-label="脱敏强度"
                  />
                  <span className="text-2xs text-gray-500 tabular-nums w-7 text-right shrink-0">
                    {cfg.imageRedactionStrength ?? 25}
                  </span>
                </div>
              </div>
            )}
            {(cfg.imageRedactionMethod ?? 'mosaic') === 'fill' && (
              <div className="flex flex-wrap items-center gap-1.5">
                <input
                  type="color"
                  value={
                    /^#[0-9A-Fa-f]{6}$/.test(cfg.imageFillColor ?? '') ? cfg.imageFillColor : '#000000'
                  }
                  onChange={e => onVisionImagePatch({ imageFillColor: e.target.value })}
                  className="h-7 w-11 cursor-pointer rounded border border-gray-200 shrink-0"
                  aria-label="填充颜色"
                />
                <input
                  type="text"
                  className="text-2xs border border-gray-200 rounded-md px-2 py-1 w-[6.5rem] font-mono"
                  placeholder="#000000"
                  value={cfg.imageFillColor ?? '#000000'}
                  onChange={e => onVisionImagePatch({ imageFillColor: e.target.value })}
                  aria-label="填充色十六进制"
                />
              </div>
            )}
          </div>
        </div>
      )}
      {scope === 'text' && (
        <div className="space-y-2">
          <div className="text-xs font-semibold text-[#1d1d1f] tracking-tight leading-tight">
            文本类型 · {cfg.selectedEntityTypeIds.length} 项
            <span className="block text-2xs font-normal text-gray-500 mt-0.5">只读预览</span>
          </div>
          {textSections.map(sec => {
            const v = textGroupKeyToVariant(sec.key);
            return (
              <div key={sec.key}>
                <div
                  className={`text-2xs font-semibold text-[#1d1d1f] mb-1 pl-2 border-l-[3px] ${
                    sec.key === 'regex'
                      ? 'border-[#007AFF]'
                      : sec.key === 'llm'
                        ? 'border-[#34C759]'
                        : 'border-[#86868b]/50'
                  }`}
                >
                  {sec.label}
                  <span className="font-normal text-gray-400 ml-1">· {sec.sub}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7 gap-1">
                  {sec.types.map(t => (
                    <ReadonlyTypeBubble key={`${sec.key}-${t.id}`} name={t.name} variant={v} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {scope === 'image' && (
        <div className="space-y-2">
          <div>
            <div className="text-xs font-semibold text-[#1d1d1f] mb-1 pl-2 border-l-[3px] border-[#34C759] tracking-tight leading-tight">
              图片类文本（OCR+HaS）· {cfg.ocrHasTypes.length} 项
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7 gap-1">
              {cfg.ocrHasTypes.map(id => (
                <ReadonlyTypeBubble key={`ocr-${id}`} name={visionName('ocr_has', id)} variant="ner" />
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold text-[#1d1d1f] mb-1 pl-2 border-l-[3px] border-[#AF52DE] tracking-tight leading-tight">
              图像特征（HaS Image）· {cfg.hasImageTypes.length} 项
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7 gap-1">
              {cfg.hasImageTypes.map(id => (
                <ReadonlyTypeBubble key={`hi-${id}`} name={visionName('has_image', id)} variant="yolo" />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export const Batch: React.FC = () => {
  const { batchMode } = useParams<{ batchMode: string }>();
  const modeValid = batchMode === 'text' || batchMode === 'image';
  const mode: BatchWizardMode = batchMode === 'image' ? 'image' : 'text';

  const [step, setStep] = useState<Step>(1);
  /** 已到达过的最前步骤，用于禁止跳过 2→3→4 直接点「导出」 */
  const [furthestStep, setFurthestStep] = useState<Step>(1);
  const [cfg, setCfg] = useState<BatchWizardPersistedConfig>(() => defaultConfig());

  const [textTypes, setTextTypes] = useState<TextEntityType[]>([]);
  const [pipelines, setPipelines] = useState<PipelineCfg[]>([]);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [presets, setPresets] = useState<RecognitionPreset[]>([]);

  const [rows, setRows] = useState<BatchRow[]>([]);
  /** 同一「本批上传」会话内多文件共享，用于处理历史树状分组与整批下载 */
  const batchGroupIdRef = useRef<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [analyzeRunning, setAnalyzeRunning] = useState(false);
  /** 批量识别已完成文件数（用于进度条，0 … rows.length） */
  const [analyzeDoneCount, setAnalyzeDoneCount] = useState(0);
  const [zipLoading, setZipLoading] = useState(false);
  const [msg, setMsg] = useState<{ text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null>(null);

  const [reviewIndex, setReviewIndex] = useState(0);
  const [reviewEntities, setReviewEntities] = useState<ReviewEntity[]>([]);
  const [reviewBoxes, setReviewBoxes] = useState<EditorBox[]>([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewExecuteLoading, setReviewExecuteLoading] = useState(false);
  /** 文本类第 4 步：与 Playground 一致的原文展示 */
  const [reviewTextContent, setReviewTextContent] = useState('');
  /** 后端 preview-map，与「确认脱敏」执行时 entity_map 一致 */
  const [previewEntityMap, setPreviewEntityMap] = useState<Record<string, string>>({});
  /** 识别项点击跳转：与 Playground 一致，同 key 多处分次循环定位 */
  const batchScrollCountersRef = useRef<Record<string, number>>({});
  /** 步骤 1 显式确认（避免默认全选时未阅读即可进入上传） */
  const [confirmStep1, setConfirmStep1] = useState(false);

  /** 第 4 步离开：切换步骤或跳转应用内其它路由时 */
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false);
  const [pendingStepAfterLeave, setPendingStepAfterLeave] = useState<Step | null>(null);

  const navigationBlocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      step === 4 &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search ||
        currentLocation.hash !== nextLocation.hash)
  );

  useEffect(() => {
    saveBatchWizardConfig(cfg, mode);
  }, [cfg, mode]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ctRes, pipeRes, presetRes] = await Promise.all([
          fetchWithTimeout('/api/v1/custom-types?enabled_only=true', { timeoutMs: 25000 }),
          fetchWithTimeout('/api/v1/vision-pipelines', { timeoutMs: 25000 }),
          fetchPresets().catch(() => [] as RecognitionPreset[]),
        ]);
        if (!ctRes.ok || !pipeRes.ok) throw new Error('加载配置失败');
        const ctData = await ctRes.json();
        const pipes: PipelineCfg[] = await pipeRes.json();
        if (cancelled) return;
        const types: TextEntityType[] = (ctData.custom_types || []).map((t: TextEntityType) => ({
          id: t.id,
          name: t.name,
          color: t.color,
          regex_pattern: t.regex_pattern,
          use_llm: t.use_llm,
        }));
        setTextTypes(types);
        setPipelines(pipes);
        setPresets(Array.isArray(presetRes) ? presetRes : []);

        const persisted = loadBatchWizardConfig(mode);
        const ocrIds = pipes
          .filter(p => p.mode === 'ocr_has' && p.enabled)
          .flatMap(p => p.types.filter(t => t.enabled).map(t => t.id));
        const hiIds = pipes
          .filter(p => p.mode === 'has_image' && p.enabled)
          .flatMap(p => p.types.filter(t => t.enabled).map(t => t.id));

        const presetList: RecognitionPreset[] = Array.isArray(presetRes) ? presetRes : [];

        const selectedEntityTypeIds =
          persisted?.selectedEntityTypeIds?.length
            ? persisted.selectedEntityTypeIds.filter(id => types.some(t => t.id === id))
            : types.map(t => t.id);
        const ocrHas = persisted?.ocrHasTypes?.length
          ? persisted.ocrHasTypes.filter(id => ocrIds.includes(id))
          : ocrIds;
        /** 与 ocrHas 一致：session 中未保存或非空列表时才用持久化值；空数组表示旧版/损坏默认，回退为管线全选 */
        const hasImg = persisted?.hasImageTypes?.length
          ? persisted.hasImageTypes.filter(id => hiIds.includes(id))
          : hiIds;

        let next: BatchWizardPersistedConfig = {
          selectedEntityTypeIds,
          ocrHasTypes: ocrHas,
          hasImageTypes: hasImg,
          replacementMode: persisted?.replacementMode ?? 'structured',
          imageRedactionMethod: persisted?.imageRedactionMethod ?? 'mosaic',
          imageRedactionStrength: persisted?.imageRedactionStrength ?? 25,
          imageFillColor: persisted?.imageFillColor ?? '#000000',
          presetTextId: null,
          presetVisionId: null,
          presetId: null,
        };

        const tid = persisted?.presetTextId ?? persisted?.presetId ?? null;
        const vid = persisted?.presetVisionId ?? persisted?.presetId ?? null;
        const pt = tid ? presetList.find(x => x.id === tid && presetAppliesText(x)) : undefined;
        const pv = vid ? presetList.find(x => x.id === vid && presetAppliesVision(x)) : undefined;

        if (pt) {
          next = {
            ...next,
            ...applyTextPresetFields(pt, types),
            presetTextId: pt.id,
          };
        }
        if (pv) {
          next = {
            ...next,
            ...applyVisionPresetFields(pv, pipes),
            presetVisionId: pv.id,
          };
        }
        // 首次进入批量向导且无 session 时，沿用 Playground/识别项配置中选用的命名预设
        if (!pt && persisted === null && mode === 'text') {
          const bid = getActivePresetTextId();
          const ptB = bid ? presetList.find(x => x.id === bid && presetAppliesText(x)) : undefined;
          if (ptB) {
            next = {
              ...next,
              ...applyTextPresetFields(ptB, types),
              presetTextId: ptB.id,
            };
          }
        }
        if (!pv && persisted === null && mode === 'image') {
          const bid = getActivePresetVisionId();
          const pvB = bid ? presetList.find(x => x.id === bid && presetAppliesVision(x)) : undefined;
          if (pvB) {
            next = {
              ...next,
              ...applyVisionPresetFields(pvB, pipes),
              presetVisionId: pvB.id,
            };
          }
        }
        setCfg(next);
      } catch (e) {
        console.error(e);
        setMsg({ text: '加载识别类型配置失败，请刷新重试', tone: 'err' });
      } finally {
        if (!cancelled) setConfigLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode]);

  const textPresets = useMemo(() => presets.filter(presetAppliesText), [presets]);
  const visionPresets = useMemo(() => presets.filter(presetAppliesVision), [presets]);

  /** 下拉「默认」：与「识别项配置」当前启用的文本类型一致（全选） */
  const batchDefaultTextTypeIds = useMemo(() => textTypes.map(t => t.id), [textTypes]);
  const batchDefaultOcrHasTypeIds = useMemo(
    () =>
      pipelines
        .filter(pl => pl.mode === 'ocr_has' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id)),
    [pipelines]
  );
  const batchDefaultHasImageTypeIds = useMemo(
    () =>
      pipelines
        .filter(pl => pl.mode === 'has_image' && pl.enabled)
        .flatMap(pl => pl.types.filter(t => t.enabled).map(t => t.id)),
    [pipelines]
  );

  const onBatchTextPresetChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const id = e.target.value;
      if (!id) {
        setActivePresetTextId(null);
        setCfg(c => ({
          ...c,
          presetTextId: null,
          selectedEntityTypeIds: [...batchDefaultTextTypeIds],
          replacementMode: 'structured',
        }));
        return;
      }
      const p = presets.find(x => x.id === id);
      if (p && presetAppliesText(p)) {
        setActivePresetTextId(p.id);
        setCfg(c => ({
          ...c,
          ...applyTextPresetFields(p, textTypes),
          presetTextId: p.id,
        }));
      }
    },
    [batchDefaultTextTypeIds, presets, textTypes]
  );

  const onBatchVisionPresetChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      const id = e.target.value;
      if (!id) {
        setActivePresetVisionId(null);
        setCfg(c => ({
          ...c,
          presetVisionId: null,
          ocrHasTypes: [...batchDefaultOcrHasTypeIds],
          hasImageTypes: [...batchDefaultHasImageTypeIds],
        }));
        return;
      }
      const p = presets.find(x => x.id === id);
      if (p && presetAppliesVision(p)) {
        setActivePresetVisionId(p.id);
        setCfg(c => ({
          ...c,
          ...applyVisionPresetFields(p, pipelines),
          presetVisionId: p.id,
        }));
      }
    },
    [batchDefaultOcrHasTypeIds, batchDefaultHasImageTypeIds, presets, pipelines]
  );

  /** 步骤 1 完成：已勾选确认 + 配置已加载；文本链至少选一类；图像链至少启用一路识别（可仅 OCR+HaS 或仅 HaS Image） */
  const isStep1Complete = useMemo(() => {
    if (!confirmStep1) return false;
    if (!configLoaded) return false;
    if (mode === 'text') {
      if (textTypes.length === 0) return true;
      return cfg.selectedEntityTypeIds.length > 0;
    }
    const ocrAvail = batchDefaultOcrHasTypeIds.length > 0;
    const hiAvail = batchDefaultHasImageTypeIds.length > 0;
    const visionPipelineHasTypes = ocrAvail || hiAvail;
    const anyVisionTypeSelected = cfg.ocrHasTypes.length > 0 || cfg.hasImageTypes.length > 0;
    if (visionPipelineHasTypes && !anyVisionTypeSelected) return false;
    return true;
  }, [
    configLoaded,
    mode,
    textTypes.length,
    cfg.selectedEntityTypeIds,
    cfg.ocrHasTypes,
    cfg.hasImageTypes,
    batchDefaultOcrHasTypeIds,
    batchDefaultHasImageTypeIds,
    confirmStep1,
  ]);

  const doneRows = useMemo(() => rows.filter(r => r.analyzeStatus === 'done'), [rows]);
  const reviewFile = doneRows[reviewIndex] ?? null;

  useEffect(() => {
    batchScrollCountersRef.current = {};
  }, [reviewFile?.file_id]);

  /** 与 loadReviewData 同帧：先置 loading，避免预览 effect 在实体加载前用空列表清空映射 */
  useLayoutEffect(() => {
    if (step !== 4 || !reviewFile) return;
    setReviewLoading(true);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode]);

  const loadReviewData = useCallback(
    async (fileId: string, isImage: boolean) => {
      setReviewLoading(true);
      setPreviewEntityMap({});
      try {
        const info = await batchGetFileRaw(fileId);
        if (isImage) {
          setReviewTextContent('');
          const raw = flattenBoundingBoxesFromStore(info.bounding_boxes);
          const boxes: EditorBox[] = raw.map((b, idx) => ({
            id: String(b.id ?? `bbox_${idx}`),
            x: Number(b.x),
            y: Number(b.y),
            width: Number(b.width),
            height: Number(b.height),
            type: String(b.type ?? 'CUSTOM'),
            text: b.text ? String(b.text) : undefined,
            selected: b.selected !== false,
            confidence: typeof b.confidence === 'number' ? b.confidence : undefined,
            source: (b.source as EditorBox['source']) || undefined,
          }));
          setReviewBoxes(boxes);
          setReviewEntities([]);
        } else {
          setReviewEntities([]);
          setReviewTextContent('');
          const ents = (info.entities as ReviewEntity[]) || [];
          const mapped = ents.map((e, i) =>
            normalizeReviewEntity({
              id: e.id || `ent_${i}`,
              text: e.text,
              type: typeof e.type === 'string' ? e.type : String(e.type ?? 'CUSTOM'),
              start: typeof e.start === 'number' ? e.start : Number(e.start),
              end: typeof e.end === 'number' ? e.end : Number(e.end),
              selected: true,
              page: e.page ?? 1,
              confidence: e.confidence,
              source: e.source,
              coref_id: e.coref_id,
            })
          );
          setReviewBoxes([]);
          const c = info.content;
          const contentStr = typeof c === 'string' ? c : '';
          setReviewEntities(mapped);
          setReviewTextContent(contentStr);
          const map = await fetchBatchPreviewMap(mapped, cfg.replacementMode);
          setPreviewEntityMap(map);
        }
      } finally {
        setReviewLoading(false);
      }
    },
    [cfg.replacementMode]
  );

  useEffect(() => {
    if (step !== 4 || !reviewFile) return;
    const isImg = reviewFile.isImageMode === true;
    void loadReviewData(reviewFile.file_id, isImg);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode, loadReviewData]);

  /** 文本批量第 4 步：配置变化时刷新替换预览（防抖；首屏映射由 loadReviewData 内联请求） */
  useEffect(() => {
    if (step !== 4 || mode !== 'text' || !reviewFile || reviewLoading) return;
    if (!reviewTextContent) return;
    if (reviewEntities.length === 0) return;
    let cancelled = false;
    const t = window.setTimeout(async () => {
      const withAllSelected = reviewEntities.map(e => ({ ...e, selected: true }));
      const map = await fetchBatchPreviewMap(withAllSelected, cfg.replacementMode);
      if (!cancelled) setPreviewEntityMap(map);
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [step, mode, reviewFile?.file_id, reviewEntities, reviewTextContent, reviewLoading, cfg.replacementMode]);

  const displayPreviewMap = useMemo(
    () => mergePreviewMapWithDocumentSlices(reviewTextContent, reviewEntities, previewEntityMap),
    [reviewTextContent, reviewEntities, previewEntityMap]
  );

  const textPreviewSegments = useMemo(
    () => buildTextSegments(reviewTextContent, displayPreviewMap),
    [reviewTextContent, displayPreviewMap]
  );

  /** 与 Playground 结果页一致：四套统一色（ENTITY_PALETTE） */
  const origToTypeIdBatch = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of reviewEntities) {
      const tid = typeof e.type === 'string' ? e.type : String(e.type ?? 'CUSTOM');
      m.set(e.text, tid);
      if (typeof e.start === 'number' && typeof e.end === 'number' && e.end <= reviewTextContent.length) {
        const sl = reviewTextContent.slice(e.start, e.end);
        if (sl && sl !== e.text) m.set(sl, tid);
      }
    }
    return m;
  }, [reviewEntities, reviewTextContent]);

  const batchMarkStyle = useCallback(
    (origKey: string): React.CSSProperties => {
      const tid = origToTypeIdBatch.get(origKey) ?? 'CUSTOM';
      const cfg = getEntityRiskConfig(tid);
      return {
        backgroundColor: cfg.bgColor,
        color: cfg.textColor,
        boxShadow: `inset 0 -2px 0 ${cfg.color}50`,
      };
    },
    [origToTypeIdBatch]
  );

  /** 与 Playground 结果页 scrollToMatch 一致：data-match-key 不用 CSS.escape，避免与 DOM 属性不一致导致选不中 */
  const scrollToBatchMatch = useCallback((e: ReviewEntity) => {
    const orig =
      typeof e.start === 'number' &&
      typeof e.end === 'number' &&
      e.start >= 0 &&
      e.end <= reviewTextContent.length
        ? reviewTextContent.slice(e.start, e.end)
        : e.text;
    if (!orig) return;
    const safeKey = orig.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
    const origMarks = document.querySelectorAll(`.result-mark-orig[data-match-key="${safeKey}"]`);
    const redactedMarks = document.querySelectorAll(`.result-mark-redacted[data-match-key="${safeKey}"]`);
    const total = Math.max(origMarks.length, redactedMarks.length);
    if (total === 0) {
      const oCandidates = Array.from(document.querySelectorAll('.result-mark-orig')).filter(
        n => n.textContent === orig
      ) as HTMLElement[];
      if (oCandidates.length === 0) return;
      const idxFb = (batchScrollCountersRef.current[safeKey] || 0) % oCandidates.length;
      batchScrollCountersRef.current[safeKey] = idxFb + 1;
      const oEl = oCandidates[idxFb];
      const mk = oEl.getAttribute('data-match-key');
      const mi = oEl.getAttribute('data-match-idx');
      let rEl: HTMLElement | null = null;
      if (mk != null && mi != null) {
        rEl = document.querySelector(
          `.result-mark-redacted[data-match-key="${mk}"][data-match-idx="${mi}"]`
        ) as HTMLElement | null;
      }
      document.querySelectorAll('.result-mark-active').forEach(el => {
        el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
      });
      oEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      oEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
      if (rEl) {
        rEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        rEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
      }
      window.setTimeout(() => {
        document.querySelectorAll('.result-mark-active').forEach(ell => {
          ell.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
        });
      }, 2500);
      return;
    }
    const idx = (batchScrollCountersRef.current[safeKey] || 0) % total;
    batchScrollCountersRef.current[safeKey] = idx + 1;
    document.querySelectorAll('.result-mark-active').forEach(el => {
      el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    });
    const origEl = origMarks[Math.min(idx, origMarks.length - 1)] as HTMLElement;
    if (origEl) {
      origEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      origEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    }
    const redEl = redactedMarks[Math.min(idx, redactedMarks.length - 1)] as HTMLElement;
    if (redEl) {
      redEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      redEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    }
    window.setTimeout(() => {
      document.querySelectorAll('.result-mark-active').forEach(ell => {
        ell.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
      });
    }, 2500);
  }, [reviewTextContent]);

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onDrop = useCallback(async (accepted: File[]) => {
    if (!accepted.length) return;
    setLoading(true);
    setMsg(null);
    const uploaded: BatchRow[] = [];
    const failed: string[] = [];
    try {
      if (!batchGroupIdRef.current) {
        batchGroupIdRef.current =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : `bg_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
      }
      const bg = batchGroupIdRef.current;
      for (const file of accepted) {
        try {
          const r = await fileApi.upload(file, bg);
          uploaded.push({
            file_id: r.file_id,
            original_filename: r.filename,
            file_size: r.file_size,
            file_type: r.file_type,
            created_at: r.created_at ?? undefined,
            has_output: false,
            entity_count: 0,
            analyzeStatus: 'pending',
          });
        } catch {
          failed.push(file.name);
        }
      }
      if (uploaded.length) {
        setRows(prev => [...uploaded, ...prev]);
        setSelected(prev => {
          const n = new Set(prev);
          uploaded.forEach(u => n.add(u.file_id));
          return n;
        });
      }
      if (failed.length && uploaded.length) {
        setMsg({
          text: `已上传 ${uploaded.length} 个；失败 ${failed.length} 个：${failed.slice(0, 3).join('、')}${failed.length > 3 ? '…' : ''}`,
          tone: 'warn',
        });
      } else if (failed.length) {
        setMsg({ text: `全部上传失败（${failed.length} 个）`, tone: 'err' });
      } else {
        setMsg({ text: `已上传 ${uploaded.length} 个文件`, tone: 'ok' });
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled: loading,
    multiple: true,
  });

  const selectedIds = rows.filter(r => selected.has(r.file_id)).map(r => r.file_id);

  const canGoStep = (target: Step): boolean => {
    if (target <= 1) return true;
    if (target < step) return true;
    if (!isStep1Complete && target >= 2) return false;
    /** 步骤 1 时仅靠勾选完成还不能点步骤条「2 上传」，须先点过一次底部「下一步：上传」（furthestStep≥2） */
    if (target === 2) return furthestStep >= 2;
    if (target === 3) return furthestStep >= 2 && rows.length > 0;
    if (target === 4) return furthestStep >= 3 && doneRows.length > 0;
    /** 步骤 4 时须先点「前往导出」或最后一份「确认」自动进入，步骤条才能点「5」 */
    if (target === 5) return furthestStep >= 5 && rows.length > 0;
    return false;
  };

  /** 仅底部「下一步：上传」调用：首次从配置进入上传，不经过步骤条 */
  const advanceToUploadStep = () => {
    if (!isStep1Complete) {
      setMsg({
        text: !configLoaded
          ? '请等待识别配置加载完成。'
          : !confirmStep1
            ? '请在步骤 1 底部勾选「已确认上述配置」后再进入上传。'
            : mode === 'text'
              ? '请先完成步骤 1：至少勾选一个文本实体类型。'
              : '请先完成步骤 1：在「图片类文本」或「图像特征」中至少勾选一类识别项（可只选其中一路）。',
        tone: 'warn',
      });
      return;
    }
    setStep(2);
    setFurthestStep(prev => Math.max(prev, 2) as Step);
    setMsg(null);
  };

  /** 步骤 ④ 底部「前往导出」：首次进入导出步，步骤条上的「5」在此之前不可点（不弹离开确认） */
  const advanceToExportStep = () => {
    if (!rows.length) {
      setMsg({ text: '没有可导出的文件', tone: 'warn' });
      return;
    }
    setStep(5);
    setFurthestStep(prev => Math.max(prev, 5) as Step);
    setMsg(null);
  };

  /** 实际切换步骤（不含第 4 步离开确认） */
  const applyStep = (s: Step) => {
    if (s === step) return;
    if (s === 1) {
      setConfirmStep1(false);
    }
    if (s >= 2 && !isStep1Complete) {
      setMsg({
        text: !configLoaded
          ? '请等待识别配置加载完成。'
          : !confirmStep1
            ? '请在步骤 1 底部勾选「已确认上述配置」后再进入上传。'
            : mode === 'text'
              ? '请先完成步骤 1：至少勾选一个文本实体类型。'
              : '请先完成步骤 1：在「图片类文本」或「图像特征」中至少勾选一类识别项（可只选其中一路）。',
        tone: 'warn',
      });
      return;
    }
    if (!canGoStep(s)) {
      setMsg({
        text: '请按顺序完成：配置 → 上传 → 批量识别 → 审阅确认，再进入导出。',
        tone: 'warn',
      });
      return;
    }
    setStep(s);
    setFurthestStep(prev => Math.max(prev, s) as Step);
    setMsg(null);
    if (s === 4) setReviewIndex(0);
  };

  /** 从第 4 步去其它步骤（除「前往导出」进入步骤 5）时先确认 */
  const goStep = (s: Step) => {
    if (step === 4 && s !== 5) {
      setPendingStepAfterLeave(s);
      setLeaveConfirmOpen(true);
      return;
    }
    applyStep(s);
  };

  const showLeaveConfirmModal =
    leaveConfirmOpen || navigationBlocker.state === 'blocked';

  const handleConfirmLeaveReview = () => {
    if (navigationBlocker.state === 'blocked') {
      navigationBlocker.proceed();
    } else if (pendingStepAfterLeave !== null) {
      applyStep(pendingStepAfterLeave);
    }
    setLeaveConfirmOpen(false);
    setPendingStepAfterLeave(null);
  };

  const handleCancelLeaveReview = () => {
    if (navigationBlocker.state === 'blocked') {
      navigationBlocker.reset();
    }
    setLeaveConfirmOpen(false);
    setPendingStepAfterLeave(null);
  };

  useEffect(() => {
    if (!showLeaveConfirmModal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (navigationBlocker.state === 'blocked') {
        navigationBlocker.reset();
      }
      setLeaveConfirmOpen(false);
      setPendingStepAfterLeave(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [showLeaveConfirmModal, navigationBlocker]);

  const runBatchAnalyze = async () => {
    if (!rows.length) return;
    setAnalyzeRunning(true);
    setAnalyzeDoneCount(0);
    setMsg(null);
    const entityIds = cfg.selectedEntityTypeIds;
    const bodyNer = {
      entity_type_ids: entityIds,
    };

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      setRows(prev =>
        prev.map((r, j) => (j === i ? { ...r, analyzeStatus: 'parsing', analyzeError: undefined } : r))
      );
      try {
        const parseRes = await batchParse(row.file_id);
        const isImage = parseRes.file_type === 'image' || parseRes.is_scanned;
        setRows(prev =>
          prev.map((r, j) =>
            j === i ? { ...r, isImageMode: isImage, analyzeStatus: 'analyzing' } : r
          )
        );

        if (isImage) {
          await batchVision(row.file_id, 1, cfg.ocrHasTypes, cfg.hasImageTypes);
          const info = await batchGetFileRaw(row.file_id);
          const boxCount = flattenBoundingBoxesFromStore(info.bounding_boxes).length;
          setRows(prev =>
            prev.map((r, j) =>
              j === i
                ? {
                    ...r,
                    analyzeStatus: 'done',
                    entity_count: boxCount,
                  }
                : r
            )
          );
        } else {
          const ner = await batchHybridNer(row.file_id, bodyNer);
          setRows(prev =>
            prev.map((r, j) =>
              j === i
                ? {
                    ...r,
                    analyzeStatus: 'done',
                    entity_count: ner.entity_count,
                  }
                : r
            )
          );
        }
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        setRows(prev =>
          prev.map((r, j) => (j === i ? { ...r, analyzeStatus: 'failed', analyzeError: err } : r))
        );
      } finally {
        setAnalyzeDoneCount(i + 1);
      }
    }
    setAnalyzeRunning(false);
    setMsg({ text: '批量识别已跑完，请进入「审阅确认」', tone: 'ok' });
  };

  const confirmCurrentReview = async () => {
    if (!reviewFile) return;
    setReviewExecuteLoading(true);
    setMsg(null);
    try {
      const entitiesPayload = reviewEntities.map(e => ({
        id: e.id,
        text: e.text,
        type: e.type,
        start: e.start,
        end: e.end,
        page: e.page ?? 1,
        confidence: e.confidence ?? 1,
        selected: true,
        source: e.source,
        coref_id: e.coref_id,
      }));

      const boxesPayload = reviewBoxes.map(b => ({
        id: b.id,
        x: b.x,
        y: b.y,
        width: b.width,
        height: b.height,
        page: 1,
        type: b.type,
        text: b.text,
        selected: b.selected,
        source: b.source,
      }));

      const imageMethod = cfg.imageRedactionMethod ?? 'mosaic';
      const imageStrength = cfg.imageRedactionStrength ?? 25;
      const imageFill = cfg.imageFillColor ?? '#000000';

      await batchExecute({
        file_id: reviewFile.file_id,
        entities: entitiesPayload as any,
        bounding_boxes: boxesPayload as any,
        config: reviewFile.isImageMode
          ? {
              replacement_mode: ReplacementMode.STRUCTURED,
              entity_types: [] as any,
              custom_replacements: {},
              image_redaction_method: imageMethod,
              image_redaction_strength: imageStrength,
              image_fill_color: imageFill,
            }
          : {
              replacement_mode:
                cfg.replacementMode === 'smart'
                  ? ReplacementMode.SMART
                  : cfg.replacementMode === 'mask'
                    ? ReplacementMode.MASK
                    : ReplacementMode.STRUCTURED,
              entity_types: [] as any,
              custom_replacements: {},
            },
      });

      setRows(prev =>
        prev.map(r =>
          r.file_id === reviewFile.file_id ? { ...r, has_output: true } : r
        )
      );

      if (reviewIndex < doneRows.length - 1) {
        setReviewIndex(reviewIndex + 1);
        setMsg({
          text: reviewFile.isImageMode ? '本张已脱敏，已切换到下一张' : '本文件已脱敏，已切换到下一份',
          tone: 'ok',
        });
      } else {
        setMsg({ text: '本批已全部审阅完成，可进入「导出」', tone: 'ok' });
        setFurthestStep(prev => Math.max(prev, 5) as Step);
        setStep(5);
      }
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : '脱敏失败', tone: 'err' });
    } finally {
      setReviewExecuteLoading(false);
    }
  };

  const downloadZip = async (redacted: boolean) => {
    if (!selectedIds.length) {
      setMsg({ text: '请先勾选文件', tone: 'warn' });
      return;
    }
    if (redacted) {
      const noOut = rows.filter(r => selected.has(r.file_id) && !r.has_output);
      if (noOut.length) {
        setMsg({ text: '所选文件中有尚未完成核对脱敏的项', tone: 'warn' });
        return;
      }
    }
    setZipLoading(true);
    setMsg(null);
    try {
      const blob = await fileApi.batchDownloadZip(selectedIds, redacted);
      triggerDownload(blob, redacted ? 'batch_redacted.zip' : 'batch_original.zip');
      setMsg({ text: '已开始下载 ZIP', tone: 'ok' });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : '下载失败', tone: 'err' });
    } finally {
      setZipLoading(false);
    }
  };

  const msgClass =
    msg?.tone === 'ok'
      ? 'bg-emerald-50 text-emerald-900 border border-emerald-100'
      : msg?.tone === 'warn'
        ? 'bg-violet-50 text-violet-900 border border-violet-100'
        : msg?.tone === 'err'
          ? 'bg-violet-50 text-violet-900 border border-violet-200'
          : 'bg-[#f5f5f5] text-[#525252] border border-gray-100';

  const getVisionTypeMeta = (id: string) => {
    for (const p of pipelines) {
      const t = p.types.find(x => x.id === id);
      if (t) return { name: t.name, color: '#6366F1' };
    }
    return { name: id, color: '#6366F1' };
  };

  if (!modeValid) {
    return <Navigate to="/batch/text" replace />;
  }

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col bg-[#fafafa] overflow-hidden">
      <div
        className={`flex-1 flex flex-col min-h-0 min-w-0 w-full max-w-[min(100%,1920px)] mx-auto ${
          step === 1
            ? 'px-3 py-2 sm:px-4 sm:py-2.5 overflow-hidden'
            : mode === 'image' && step === 4
              ? 'px-2 py-1.5 sm:px-3 sm:py-2 flex flex-col min-h-0 overflow-hidden'
              : step === 4 && mode === 'text'
                ? 'px-2 py-2 sm:px-4 sm:py-3 flex flex-col min-h-0 overflow-hidden'
                : 'px-3 py-3 sm:px-5 sm:py-4 overflow-y-auto overscroll-contain'
        }`}
      >
        <p
          className={`mb-1 flex-shrink-0 text-2xs sm:text-caption text-[#737373] leading-tight ${
            step === 4 && (mode === 'image' || mode === 'text') ? 'hidden' : ''
          }`}
        >
          五步：配置 → 上传 → 批量识别 → 审阅确认 → 导出（与 Playground 无关）
        </p>

        {/* 步骤条 */}
        <div
          className={`flex flex-wrap items-center gap-1.5 flex-shrink-0 ${
            step === 4 && (mode === 'image' || mode === 'text') ? 'mb-1' : 'mb-1.5'
          }`}
        >
          {STEPS.map((s, i) => (
            <React.Fragment key={s.n}>
              <button
                type="button"
                onClick={() => goStep(s.n)}
                disabled={!canGoStep(s.n)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  step === s.n
                    ? 'bg-[#1d1d1f] text-white'
                    : canGoStep(s.n)
                      ? 'bg-white border border-gray-200 text-gray-700 hover:bg-gray-50'
                      : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                }`}
              >
                <span className="tabular-nums">{s.n}</span>
                {s.label}
              </button>
              {i < STEPS.length - 1 && <span className="text-gray-300 hidden sm:inline">→</span>}
            </React.Fragment>
          ))}
        </div>

        {msg && <div className={`text-sm rounded-lg px-3 py-2 mb-2 ${msgClass}`}>{msg.text}</div>}

        {/* 1 配置 */}
        {step === 1 && (
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm flex flex-col flex-1 min-h-0 overflow-hidden p-2 sm:p-3 space-y-2">
            <h3 className="font-semibold text-gray-900 shrink-0 text-sm leading-tight">
              ① 识别与脱敏配置
            </h3>
            {!configLoaded ? (
              <p className="text-sm text-gray-400">加载类型配置中…</p>
            ) : (
              <>
                <div className="rounded-lg border border-gray-100 bg-[#fafafa] flex flex-col flex-1 min-h-0 overflow-hidden p-2 space-y-2">
                  <div className="text-2xs text-gray-500 leading-snug space-y-0.5">
                    <p>
                      <span className="text-gray-600">「默认」</span>
                      与「识别项配置」中当前启用的类型一致；未选命名预设时即为全选。
                    </p>
                    <p>命名预设可在「识别项配置」或 Playground 另存为后在此选用。</p>
                  </div>
                  <div className={`grid gap-2 sm:grid-cols-1 ${mode === 'image' ? 'max-w-full' : 'max-w-xl'}`}>
                    {mode === 'text' && (
                      <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-medium text-gray-800">文本脱敏配置清单</label>
                        <p className="text-2xs text-gray-500">实体类型（HaS NER）与替换模式</p>
                        <select
                          className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white w-full"
                          value={cfg.presetTextId ?? ''}
                          onChange={onBatchTextPresetChange}
                        >
                          <option value="">默认</option>
                          {textPresets.map(p => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                              {p.kind === 'full' ? '（组合）' : ''}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    {mode === 'image' && (
                      <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-medium text-gray-800">图像脱敏配置清单</label>
                        <select
                          className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white w-full"
                          value={cfg.presetVisionId ?? ''}
                          onChange={onBatchVisionPresetChange}
                        >
                          <option value="">默认</option>
                          {visionPresets.map(p => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                              {p.kind === 'full' ? '（组合）' : ''}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                  {((mode === 'text' && textPresets.length === 0) || (mode === 'image' && visionPresets.length === 0)) && (
                    <p className="text-xs text-[#64748b] bg-slate-50 border border-slate-100 rounded-md px-3 py-2">
                      暂无命名预设。已使用「默认」全选（与识别项配置一致）；需要复用时可到「
                      <Link to="/settings" className="underline font-medium">
                        识别项配置
                      </Link>
                      」或 Playground 另存为预设。
                    </p>
                  )}
                  <div className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-black/[0.06] bg-white/80 p-2">
                    <PresetDetailBlock
                      cfg={cfg}
                      textTypes={textTypes}
                      pipelines={pipelines}
                      allPresets={presets}
                      scope={mode}
                      onReplacementModeChange={mode =>
                        setCfg(c => ({ ...c, presetTextId: null, replacementMode: mode }))
                      }
                      onVisionImagePatch={patch =>
                        setCfg(c => ({ ...c, presetVisionId: null, ...patch }))
                      }
                    />
                  </div>
                </div>

                {configLoaded &&
                  (mode === 'image' ? (
                    <div className="flex flex-col gap-1.5 pt-1.5 mt-0.5 border-t border-gray-100 sm:flex-row sm:items-center sm:justify-between sm:gap-2 shrink-0">
                      <label className="flex items-start gap-2 cursor-pointer text-2xs text-gray-700 leading-snug min-w-0 flex-1">
                        <input
                          type="checkbox"
                          checked={confirmStep1}
                          onChange={e => setConfirmStep1(e.target.checked)}
                          className={`mt-0.5 ${formCheckboxClass()}`}
                        />
                        <span>已确认当前识别与脱敏配置；未勾选无法进入「上传」。</span>
                      </label>
                      <button
                        type="button"
                        onClick={advanceToUploadStep}
                        disabled={!isStep1Complete}
                        className="shrink-0 px-4 py-2 text-sm font-medium rounded-xl bg-[#1d1d1f] text-white hover:bg-[#2d2d2f] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-[#1d1d1f]"
                      >
                        下一步：上传
                      </button>
                    </div>
                  ) : (
                    <>
                      <label className="flex items-start gap-2 cursor-pointer text-2xs text-gray-700 mb-1 pt-1.5 border-t border-gray-100 leading-snug shrink-0">
                        <input
                          type="checkbox"
                          checked={confirmStep1}
                          onChange={e => setConfirmStep1(e.target.checked)}
                          className={`mt-0.5 ${formCheckboxClass()}`}
                        />
                        <span>已确认当前识别与脱敏配置；未勾选无法进入「上传」。</span>
                      </label>
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={advanceToUploadStep}
                          disabled={!isStep1Complete}
                          className="px-4 py-2 text-sm font-medium rounded-xl bg-[#1d1d1f] text-white hover:bg-[#2d2d2f] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-[#1d1d1f]"
                        >
                          下一步：上传
                        </button>
                      </div>
                    </>
                  ))}
              </>
            )}
          </div>
        )}

        {/* 2 上传 */}
        {step === 2 && (
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="flex flex-col gap-4">
              <div
                {...getRootProps()}
                className={`min-h-[220px] rounded-xl border-2 border-dashed flex flex-col items-center justify-center px-6 py-8 cursor-pointer transition-all ${
                  isDragActive ? 'border-[#1d1d1f] bg-white shadow-sm' : 'border-[#e5e5e5] bg-white hover:border-[#d4d4d4]'
                } ${loading ? 'opacity-50 pointer-events-none' : ''}`}
              >
                <input {...getInputProps()} />
                <p className="text-base font-medium text-[#1d1d1f]">拖放多个文件，或点击选择</p>
                <p className="text-xs text-[#a3a3a3] mt-2">Word · PDF · 图片</p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => goStep(1)}
                  className="px-4 py-2 text-sm border border-gray-200 rounded-lg bg-white"
                >
                  上一步
                </button>
                <button
                  type="button"
                  onClick={() => goStep(3)}
                  disabled={!rows.length}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40"
                >
                  下一步：批量识别
                </button>
              </div>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col min-h-[240px]">
              <div className="px-4 py-3 border-b border-gray-100">
                <h3 className="font-semibold text-gray-900 text-sm">上传队列</h3>
                <p className="text-xs text-gray-400">共 {rows.length} 个</p>
              </div>
              <div className="flex-1 overflow-y-auto max-h-[320px] divide-y divide-gray-50">
                {rows.length === 0 ? (
                  <p className="p-6 text-sm text-gray-400 text-center">暂无文件</p>
                ) : (
                  rows.map(r => (
                    <div key={r.file_id} className="px-4 py-2 flex justify-between gap-2 text-sm">
                      <span className="truncate">{r.original_filename}</span>
                      <span className="text-xs text-gray-400 shrink-0">{r.file_type}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {/* 3 批量识别 */}
        {step === 3 && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
            <h3 className="font-semibold text-gray-900">③ 批量识别</h3>
            <p className="text-xs text-gray-500">
              将依次解析每个文件并运行文本 NER 或图像双路识别。失败项可在列表中查看原因，仍可对成功项继续核对。
            </p>
            {rows.length > 0 && (analyzeRunning || analyzeDoneCount > 0) && (
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs text-gray-600">
                  <span>识别进度</span>
                  <span className="tabular-nums font-medium text-gray-800">
                    {analyzeDoneCount} / {rows.length}
                  </span>
                </div>
                <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#007AFF] transition-[width] duration-300 ease-out"
                    style={{
                      width: `${rows.length ? Math.min(100, (analyzeDoneCount / rows.length) * 100) : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => goStep(2)}
                className="px-4 py-2 text-sm border border-gray-200 rounded-lg bg-white"
              >
                上一步
              </button>
              <button
                type="button"
                onClick={runBatchAnalyze}
                disabled={analyzeRunning || !rows.length}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40"
              >
                {analyzeRunning ? '识别中…' : '开始批量识别'}
              </button>
              <button
                type="button"
                onClick={() => goStep(4)}
                disabled={!canGoStep(4)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 bg-white disabled:opacity-40"
              >
                进入核对
              </button>
            </div>
            <div className="border border-gray-100 rounded-lg divide-y divide-gray-50 max-h-80 overflow-y-auto">
              {rows.map(r => (
                <div key={r.file_id} className="px-4 py-2 flex flex-wrap items-center gap-2 text-sm">
                  <span className="truncate flex-1 min-w-0">{r.original_filename}</span>
                  <span className="text-xs text-gray-500">{r.analyzeStatus}</span>
                  {r.analyzeError && <span className="text-xs text-violet-700">{r.analyzeError}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 4 核对 · 图像：画布最大化，控件浮层 */}
        {step === 4 && mode === 'image' && (
          <div className="flex-1 flex flex-col min-h-0 rounded-xl border border-gray-200 shadow-sm bg-white overflow-hidden">
            {!doneRows.length ? (
              <p className="p-3 text-sm text-gray-400 shrink-0">没有可核对的文件，请先完成识别。</p>
            ) : reviewLoading || !reviewFile ? (
              <p className="p-3 text-sm text-gray-400 shrink-0">加载中…</p>
            ) : reviewFile.isImageMode ? (
              <div className="flex-1 min-h-0 min-w-0 flex flex-col">
                <ImageBBoxEditor
                  imageSrc={fileApi.getDownloadUrl(reviewFile.file_id, false)}
                  boxes={reviewBoxes}
                  onBoxesChange={setReviewBoxes}
                  getTypeConfig={getVisionTypeMeta}
                  availableTypes={pipelines.flatMap(p => p.types.filter(t => t.enabled))}
                  defaultType="CUSTOM"
                  viewportTopSlot={
                    <>
                      <button
                        type="button"
                        onClick={() => goStep(3)}
                        className="px-2 py-0.5 text-2xs font-medium rounded border border-gray-200 bg-white/95 text-gray-800 shadow-sm hover:bg-white"
                      >
                        上一步
                      </button>
                      <span
                        className="text-2xs font-medium text-gray-900 truncate max-w-[min(42vw,14rem)] px-1.5 py-0.5 rounded bg-white/90 border border-gray-200/80 shadow-sm"
                        title={reviewFile.original_filename}
                      >
                        {reviewFile.original_filename}
                      </span>
                      {doneRows.length > 1 && (
                        <>
                          <button
                            type="button"
                            disabled={reviewIndex <= 0}
                            onClick={() => setReviewIndex(i => Math.max(0, i - 1))}
                            className="px-1.5 py-0.5 text-2xs rounded border border-gray-200 bg-white/95 disabled:opacity-40 shadow-sm"
                          >
                            上一张
                          </button>
                          <span className="text-2xs text-gray-700 tabular-nums px-0.5">
                            {reviewIndex + 1}/{doneRows.length}
                          </span>
                          <button
                            type="button"
                            disabled={reviewIndex >= doneRows.length - 1}
                            onClick={() => setReviewIndex(i => Math.min(doneRows.length - 1, i + 1))}
                            className="px-1.5 py-0.5 text-2xs rounded border border-gray-200 bg-white/95 disabled:opacity-40 shadow-sm"
                          >
                            下一张
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        onClick={advanceToExportStep}
                        disabled={!rows.length}
                        className="px-2 py-0.5 text-2xs font-medium rounded border border-gray-200 bg-white/95 text-gray-800 shadow-sm hover:bg-white disabled:opacity-40 ml-auto"
                      >
                        前往导出
                      </button>
                    </>
                  }
                  viewportBottomSlot={
                    <button
                      type="button"
                      onClick={confirmCurrentReview}
                      disabled={reviewExecuteLoading}
                      className="px-4 py-2 text-xs font-semibold rounded-lg bg-[#1d1d1f] text-white shadow-lg disabled:opacity-50"
                    >
                      {reviewExecuteLoading ? '处理中…' : '确认本张并脱敏'}
                    </button>
                  }
                />
              </div>
            ) : (
              <div className="flex flex-col flex-1 min-h-0 p-4 gap-3 overflow-auto">
                <p className="text-xs font-medium text-gray-900 truncate">{reviewFile.original_filename}</p>
                <div className="max-h-72 overflow-y-auto border border-gray-100 rounded-lg">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-left text-xs text-gray-500">
                      <tr>
                        <th className="p-2">类型</th>
                        <th className="p-2">文本</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reviewEntities.map(e => (
                        <tr key={e.id} className="border-t border-gray-50">
                          <td className="p-2 text-xs">
                            {textTypes.find(t => t.id === e.type)?.name ?? getEntityTypeName(e.type)}
                          </td>
                          <td className="p-2 text-xs break-all">{e.text}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {reviewEntities.length === 0 && (
                    <p className="p-4 text-sm text-gray-400">无识别实体，可直接确认（将不做文本替换）</p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={confirmCurrentReview}
                  disabled={reviewExecuteLoading}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-50 self-start"
                >
                  {reviewExecuteLoading ? '处理中…' : '确认本张并脱敏'}
                </button>
                <div className="flex justify-end pt-2">
                  <button
                    type="button"
                    onClick={advanceToExportStep}
                    disabled={!rows.length}
                    className="px-4 py-2 text-sm rounded-lg border border-gray-200 disabled:opacity-40"
                  >
                    前往导出
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 4 审阅 · 文本（与 Playground 文本脱敏结果区一致：三列 + 逐份切换） */}
        {step === 4 && mode === 'text' && (
          <div className="flex-1 flex flex-col min-h-0 rounded-xl border border-gray-200 shadow-sm bg-white overflow-hidden">
            <div className="shrink-0 px-4 pt-3 pb-2 border-b border-gray-100/80 space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="font-semibold text-gray-900 text-sm">④ 审阅确认</h3>
                  <p className="text-2xs text-gray-500 mt-0.5 leading-snug">
                    与 Playground 一致：原文 / 脱敏预览 / 识别项。点击识别项可在左右两列同步定位并高亮。多文件时逐份审阅。
                  </p>
                </div>
                <button
                  type="button"
                  onClick={advanceToExportStep}
                  disabled={!rows.length}
                  className="shrink-0 px-3 py-1.5 text-xs rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
                >
                  前往导出
                </button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => goStep(3)}
                  className="px-2.5 py-1 text-xs border border-gray-200 rounded-lg bg-white hover:bg-gray-50"
                >
                  上一步
                </button>
                {doneRows.length > 1 && (
                  <>
                    <button
                      type="button"
                      disabled={reviewIndex <= 0}
                      onClick={() => setReviewIndex(i => Math.max(0, i - 1))}
                      className="px-2.5 py-1 text-xs border border-gray-200 rounded-lg bg-white disabled:opacity-40"
                    >
                      上一份
                    </button>
                    <span className="text-xs text-gray-600 tabular-nums">
                      {reviewIndex + 1} / {doneRows.length}
                    </span>
                    <button
                      type="button"
                      disabled={reviewIndex >= doneRows.length - 1}
                      onClick={() => setReviewIndex(i => Math.min(doneRows.length - 1, i + 1))}
                      className="px-2.5 py-1 text-xs border border-gray-200 rounded-lg bg-white disabled:opacity-40"
                    >
                      下一份
                    </button>
                  </>
                )}
              </div>
            </div>

            {!doneRows.length && (
              <p className="p-4 text-sm text-gray-400 shrink-0">没有可审阅的文件，请先完成识别。</p>
            )}

            {!!doneRows.length && reviewFile && (
              <div className="flex-1 flex flex-col min-h-0 min-w-0 px-2 pb-3 sm:px-4 sm:pb-4 pt-2">
                <p
                  className="text-xs font-medium text-gray-900 truncate shrink-0 mb-2 px-0.5"
                  title={reviewFile.original_filename}
                >
                  {reviewFile.original_filename}
                </p>
                {reviewLoading ? (
                  <p className="text-sm text-gray-400 px-1">加载中…</p>
                ) : (
                  <div className="flex-1 flex gap-2 sm:gap-3 min-h-0 min-w-0">
                    <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                      <div className="flex-shrink-0 px-3 sm:px-4 py-2 border-b border-gray-100 flex items-center gap-2">
                        <span className="text-xs font-semibold text-gray-700 tracking-tight">原始文档</span>
                      </div>
                      <div className="flex-1 overflow-auto p-3 sm:p-4">
                        <div className="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap font-[system-ui]">
                          {textPreviewSegments.map((seg, i) =>
                            seg.isMatch ? (
                              <mark
                                key={i}
                                data-match-key={seg.safeKey}
                                data-match-idx={seg.matchIdx}
                                style={batchMarkStyle(seg.origKey)}
                                className="result-mark-orig px-0.5 rounded-md transition-all duration-300"
                              >
                                {seg.text}
                              </mark>
                            ) : (
                              <span key={i}>{seg.text}</span>
                            )
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                      <div className="flex-shrink-0 px-3 sm:px-4 py-2 border-b border-gray-100 flex items-center gap-2">
                        <span className="text-xs font-semibold text-gray-700 tracking-tight">脱敏预览</span>
                      </div>
                      <div className="flex-1 overflow-auto p-3 sm:p-4">
                        <div className="text-sm leading-relaxed text-gray-800 whitespace-pre-wrap font-[system-ui]">
                          {textPreviewSegments.map((seg, i) =>
                            seg.isMatch ? (
                              <mark
                                key={i}
                                data-match-key={seg.safeKey}
                                data-match-idx={seg.matchIdx}
                                style={batchMarkStyle(seg.origKey)}
                                className="result-mark-redacted px-0.5 rounded-md transition-all duration-300"
                              >
                                {displayPreviewMap[seg.origKey] ?? '…'}
                              </mark>
                            ) : (
                              <span key={i}>{seg.text}</span>
                            )
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="w-[min(100%,18rem)] sm:w-64 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden min-h-0">
                      <div className="flex-shrink-0 px-3 py-2 border-b border-gray-100 flex items-center justify-between">
                        <span className="text-xs font-semibold text-gray-700 tracking-tight">识别项</span>
                        <span className="text-2xs text-gray-400 tabular-nums">{reviewEntities.length}</span>
                      </div>
                      <div className="flex-1 overflow-y-auto overflow-x-hidden">
                        {reviewEntities.map(e => {
                          const repl =
                            displayPreviewMap[e.text] ??
                            (typeof e.start === 'number' && typeof e.end === 'number' && e.end <= reviewTextContent.length
                              ? displayPreviewMap[reviewTextContent.slice(e.start, e.end)]
                              : undefined);
                          const cfg = getEntityRiskConfig(e.type);
                          return (
                            <button
                              key={e.id}
                              type="button"
                              className="w-full text-left px-2.5 py-2.5 mx-1.5 my-1.5 rounded-xl border border-black/[0.06] shadow-sm shadow-violet-900/5 hover:brightness-[0.99] transition-all"
                              style={{ borderLeft: `3px solid ${cfg.color}`, backgroundColor: cfg.bgColor }}
                              onClick={() => scrollToBatchMatch(e)}
                            >
                              <span className="text-caption font-medium" style={{ color: cfg.textColor }}>
                                {textTypes.find(t => t.id === e.type)?.name ?? getEntityTypeName(e.type)}
                              </span>
                              <span className="block text-xs break-all mt-0.5" style={{ color: cfg.textColor }}>
                                {e.text}
                              </span>
                              {repl != null && (
                                <span className="block text-2xs mt-0.5 truncate opacity-90" style={{ color: cfg.textColor }}>
                                  → {repl}
                                </span>
                              )}
                            </button>
                          );
                        })}
                        {reviewEntities.length === 0 && (
                          <p className="text-xs text-gray-400 text-center py-6 px-2">
                            无识别实体，可直接确认（将不做文本替换）
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )}
                <div className="shrink-0 flex flex-wrap items-center gap-2 pt-3">
                  <button
                    type="button"
                    onClick={confirmCurrentReview}
                    disabled={reviewExecuteLoading}
                    className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-50"
                  >
                    {reviewExecuteLoading ? '处理中…' : '确认本文件并脱敏'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 5 导出 */}
        {step === 5 && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
            <h3 className="font-semibold text-gray-900">⑤ 导出</h3>
            <p className="text-xs text-gray-500">勾选文件后打包下载；脱敏 ZIP 仅包含已在第 4 步「审阅确认」中完成脱敏的文件。</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => goStep(4)} className="px-4 py-2 text-sm border rounded-lg">
                返回审阅
              </button>
              <button
                type="button"
                onClick={() => downloadZip(false)}
                disabled={zipLoading || !selectedIds.length}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40"
              >
                {zipLoading ? '处理中…' : '下载原始 ZIP'}
              </button>
              <button
                type="button"
                onClick={() => downloadZip(true)}
                disabled={zipLoading || !selectedIds.length}
                className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 bg-white disabled:opacity-40"
              >
                下载脱敏 ZIP
              </button>
            </div>
            <div className="border border-gray-100 rounded-lg divide-y max-h-72 overflow-y-auto">
              {rows.map(r => (
                <div key={r.file_id} className="px-4 py-2 flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    className={formCheckboxClass('md')}
                    checked={selected.has(r.file_id)}
                    onChange={() => toggle(r.file_id)}
                  />
                  <span className="flex-1 truncate">{r.original_filename}</span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      r.has_output ? 'bg-emerald-50 text-emerald-800' : 'bg-gray-100 text-gray-500'
                    }`}
                  >
                    {r.has_output ? '已脱敏' : '未脱敏'}
                  </span>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => {
                batchGroupIdRef.current = null;
                setRows([]);
                setSelected(new Set());
                setFurthestStep(1);
                setStep(1);
                setAnalyzeDoneCount(0);
                setMsg(null);
              }}
              className="text-sm text-gray-500 hover:text-gray-800"
            >
              清空本批并回到步骤 1
            </button>
          </div>
        )}

        {showLeaveConfirmModal && (
          <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/40"
            role="dialog"
            aria-modal="true"
            aria-labelledby="batch-leave-review-title"
            onClick={e => {
              if (e.target === e.currentTarget) handleCancelLeaveReview();
            }}
          >
            <div
              className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 border border-gray-200"
              onClick={e => e.stopPropagation()}
            >
              <h2 id="batch-leave-review-title" className="text-base font-semibold text-gray-900">
                离开审阅？
              </h2>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                当前步骤的审阅尚未保存到文件（未点「确认并脱敏」前，修改仅在前端有效）。离开本页或切换到其它步骤后将丢失这些修改。
              </p>
              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={handleCancelLeaveReview}
                  className="px-4 py-2 text-sm rounded-lg border border-gray-200 bg-white hover:bg-gray-50"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={handleConfirmLeaveReview}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white hover:bg-[#262626]"
                >
                  离开
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Batch;
