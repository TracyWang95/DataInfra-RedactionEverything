import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Navigate, useLocation, useParams, useBlocker, useSearchParams } from 'react-router-dom';
import { fetchWithTimeout } from '../utils/fetchWithTimeout';
import { useDropzone } from 'react-dropzone';
import ImageBBoxEditor, { type BoundingBox as EditorBox } from '../components/ImageBBoxEditor';
import { EntityTypeGroupPicker } from '../components/EntityTypeGroupPicker';
import { getEntityRiskConfig, getEntityTypeName } from '../config/entityTypes';
import { fileApi, authenticatedBlobUrl } from '../services/api';
import type { FileListItem } from '../types';
import { FileType, ReplacementMode } from '../types';
import {
  batchGetFileRaw,
  batchHybridNer,
  batchParse,
  batchPreviewEntityMap,
  batchPreviewImage,
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
import { resolveRedactionState, REDACTION_STATE_LABEL, REDACTION_STATE_CLASS } from '../utils/redactionState';
import {
  createJob,
  getJob,
  submitJob as apiSubmitJob,
  updateJobDraft,
  commitItemReview,
  getItemReviewDraft,
  putItemReviewDraft,
  requeueFailed,
} from '../services/jobsApi';
import { effectiveWizardFurthestStep, parseWizardFurthestFromUnknown } from '../utils/jobPrimaryNavigation';
import { clampPopoverInCanvas } from './playground-utils';
// Step sub-components available for further decomposition:
import { BatchStep1Config } from './batch/BatchStep1Config';
import { BatchStep2Upload } from './batch/BatchStep2Upload';
import { BatchStep3Review } from './batch/BatchStep3Review';

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
  analyzeStatus: 'pending' | 'parsing' | 'analyzing' | 'awaiting_review' | 'review_approved' | 'redacting' | 'completed' | 'failed';
  analyzeError?: string;
  isImageMode?: boolean;
  reviewConfirmed?: boolean;
}

/** 识别已完成、可进入审阅/已审阅的状态集合 */
const RECOGNITION_DONE_STATUSES: ReadonlySet<BatchRow['analyzeStatus']> = new Set([
  'awaiting_review', 'review_approved', 'redacting', 'completed',
]);

/** 后端 item.status → 前端 analyzeStatus */
function mapBackendStatus(status: string): BatchRow['analyzeStatus'] {
  switch (status) {
    case 'failed':
    case 'cancelled':
      return 'failed';
    case 'awaiting_review':
      return 'awaiting_review';
    case 'review_approved':
      return 'review_approved';
    case 'redacting':
      return 'redacting';
    case 'completed':
      return 'completed';
    case 'processing':  // 新简化状态：合并 parsing/ner/vision/redacting
    case 'parsing':
    case 'ner':
    case 'vision':
      return 'analyzing';
    default: // pending, queued, draft …
      return 'pending';
  }
}

/** 从后端 item 字段推算 reviewConfirmed（hydration / 轮询 / 刷新统一使用） */
function deriveReviewConfirmed(item: { status: string; has_output?: boolean | null }): boolean {
  if (item.status === 'completed') {
    return item.has_output !== false;
  }
  return item.status === 'review_approved' || item.status === 'redacting';
}

// ANALYZE_STATUS_LABEL moved to ./batch/batchTypes.ts

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
  replacement?: string;
};

const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: '任务与配置' },
  { n: 2, label: '上传' },
  { n: 3, label: '批量识别' },
  { n: 4, label: '审阅确认' },
  { n: 5, label: '导出' },
];

/** 同步到 Job 草稿 config，供后台 Worker 识别 / 脱敏使用；wizard_furthest_step 仅前端恢复用，Worker 可忽略 */
function buildJobConfigForWorker(
  c: BatchWizardPersistedConfig,
  wizardMode: BatchWizardMode,
  wizardFurthestStep: Step
): Record<string, unknown> {
  return {
    entity_type_ids: c.selectedEntityTypeIds,
    ocr_has_types: c.ocrHasTypes,
    has_image_types: c.hasImageTypes,
    replacement_mode: c.replacementMode,
    image_redaction_method: c.imageRedactionMethod,
    image_redaction_strength: c.imageRedactionStrength,
    image_fill_color: c.imageFillColor,
    batch_wizard_mode: wizardMode,
    preferred_execution: c.executionDefault === 'local' ? 'local' : 'queue',
    wizard_furthest_step: wizardFurthestStep,
  };
}

function mergeJobConfigIntoWizardCfg(
  c: BatchWizardPersistedConfig,
  jc: Record<string, unknown>
): BatchWizardPersistedConfig {
  return {
    ...c,
    selectedEntityTypeIds:
      Array.isArray(jc.entity_type_ids) && (jc.entity_type_ids as string[]).length
        ? (jc.entity_type_ids as string[])
        : c.selectedEntityTypeIds,
    ocrHasTypes:
      Array.isArray(jc.ocr_has_types) && (jc.ocr_has_types as string[]).length
        ? (jc.ocr_has_types as string[])
        : c.ocrHasTypes,
    hasImageTypes:
      Array.isArray(jc.has_image_types) && (jc.has_image_types as string[]).length
        ? (jc.has_image_types as string[])
        : c.hasImageTypes,
    replacementMode:
      jc.replacement_mode === 'smart' || jc.replacement_mode === 'mask' || jc.replacement_mode === 'structured'
        ? (jc.replacement_mode as BatchWizardPersistedConfig['replacementMode'])
        : c.replacementMode,
    imageRedactionMethod:
      jc.image_redaction_method === 'mosaic' ||
      jc.image_redaction_method === 'blur' ||
      jc.image_redaction_method === 'fill'
        ? jc.image_redaction_method
        : c.imageRedactionMethod,
    imageRedactionStrength:
      typeof jc.image_redaction_strength === 'number'
        ? jc.image_redaction_strength
        : c.imageRedactionStrength,
    imageFillColor: typeof jc.image_fill_color === 'string' ? jc.image_fill_color : c.imageFillColor,
  };
}

/** localStorage：跨标签页共享；sessionStorage 只在单标签内有效，易导致「批量页一标签、任务中心另一标签」丢进度 */
const BATCH_WIZ_FURTHEST_LS_PREFIX = 'lr_batch_wiz_furthest_';

function readLocalWizardMaxStep(jobId: string): Step | null {
  try {
    const v = localStorage.getItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId);
    return parseWizardFurthestFromUnknown(v);
  } catch {
    return null;
  }
}

function writeLocalWizardMaxStep(jobId: string, step: Step) {
  try {
    const prev = readLocalWizardMaxStep(jobId);
    const merged = Math.max(step, prev ?? 1) as Step;
    if (merged >= 2) localStorage.setItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId, String(merged));
  } catch {
    /* ignore */
  }
}

function clearLocalWizardMaxStep(jobId: string) {
  try {
    localStorage.removeItem(BATCH_WIZ_FURTHEST_LS_PREFIX + jobId);
  } catch {
    /* ignore */
  }
}

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
    executionDefault: 'queue',
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
  const visible = entities.filter(e => e.selected !== false);
  const payload = buildPreviewPayload(visible);
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

/** Smart 模式右侧：Tab 切换文本/图像详情（只读展示） */
function SmartDetailTabs({
  cfg,
  textTypes,
  pipelines,
  presets,
  setCfg,
}: {
  cfg: BatchWizardPersistedConfig;
  textTypes: TextEntityType[];
  pipelines: PipelineCfg[];
  presets: RecognitionPreset[];
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
}) {
  const [tab, setTab] = React.useState<'text' | 'image'>('text');
  return (
    <>
      <div className="flex border-b border-gray-200 dark:border-gray-700 shrink-0">
        <button
          type="button"
          onClick={() => setTab('text')}
          className={`flex-1 px-4 py-2.5 text-xs font-medium transition-colors ${
            tab === 'text'
              ? 'text-[#1d1d1f] border-b-2 border-[#1d1d1f] bg-white'
              : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
          }`}
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5 align-middle" />
          文本识别详情
        </button>
        <button
          type="button"
          onClick={() => setTab('image')}
          className={`flex-1 px-4 py-2.5 text-xs font-medium transition-colors ${
            tab === 'image'
              ? 'text-[#1d1d1f] border-b-2 border-[#1d1d1f] bg-white'
              : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
          }`}
        >
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-violet-500 mr-1.5 align-middle" />
          图像识别详情
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-2">
        <PresetDetailBlock
          cfg={cfg}
          textTypes={textTypes}
          pipelines={pipelines}
          allPresets={presets}
          scope={tab}
          onReplacementModeChange={m =>
            setCfg(c => ({ ...c, presetTextId: null, replacementMode: m }))
          }
          onVisionImagePatch={patch =>
            setCfg(c => ({ ...c, presetVisionId: null, ...patch }))
          }
        />
      </div>
    </>
  );
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
    <div className="text-xs text-[#1d1d1f] dark:text-gray-100 space-y-2 border border-black/[0.06] dark:border-gray-700 rounded-xl p-2.5 bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      {(scope === 'text' ? textPresetLabel : visionPresetLabel) && (
        <div className="text-2xs text-gray-500 dark:text-gray-400 space-y-0.5 pb-2 border-b border-gray-100">
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
          <div className="text-2xs text-gray-500 dark:text-gray-400 space-y-0.5 leading-snug">
            <p>
              <span className="text-gray-600 font-medium">structured</span>：语义占位
              <span className="text-[#a3a3a3] font-mono ml-1">张三 → &lt;人物[001].个人.姓名&gt;</span>
            </p>
            <p>
              <span className="text-gray-600 font-medium">smart</span>：中文类别编号
              <span className="text-[#a3a3a3] font-mono ml-1">张三 → [当事人一]</span>
            </p>
            <p>
              <span className="text-gray-600 font-medium">mask</span>：部分打星
              <span className="text-[#a3a3a3] font-mono ml-1">张三 → 张**</span>
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
          <div className="text-2xs text-gray-500 dark:text-gray-400 space-y-0.5 leading-snug">
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
                  <span className="text-2xs text-gray-500 dark:text-gray-400 tabular-nums w-7 text-right shrink-0">
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
          <div className="text-xs font-semibold text-[#1d1d1f] dark:text-gray-100 tracking-tight leading-tight">
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
            <div className="text-xs font-semibold text-[#1d1d1f] dark:text-gray-100 mb-1 pl-2 border-l-[3px] border-[#34C759] tracking-tight leading-tight">
              图片类文本（OCR+HaS）· {cfg.ocrHasTypes.length} 项
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7 gap-1">
              {cfg.ocrHasTypes.map(id => (
                <ReadonlyTypeBubble key={`ocr-${id}`} name={visionName('ocr_has', id)} variant="ner" />
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-semibold text-[#1d1d1f] dark:text-gray-100 mb-1 pl-2 border-l-[3px] border-[#AF52DE] tracking-tight leading-tight">
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
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const modeValid = batchMode === 'text' || batchMode === 'image' || batchMode === 'smart';
  // 统一使用 smart 模式，text / image 保留兼容但实际行为一致
  const mode: BatchWizardMode = 'smart';
  const sessionJobKey = `lr_batch_job_id_${mode}`;

  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(sessionJobKey);
    } catch {
      return null;
    }
  });
  const [jobSkipItemReview, setJobSkipItemReview] = useState(false);
  const itemIdByFileIdRef = useRef<Record<string, string>>({});
  const hydratedFromUrlRef = useRef(false);
  /** effect 重跑或 StrictMode 卸载时递增，丢弃上一轮 getJob/Promise.all，避免依赖 step 导致「乐观 setStep → cleanup cancel → 永远完不成 hydrate」 */
  const batchHydrateGenRef = useRef(0);
  const urlHydrateKeyRef = useRef('');
  /** 仅 jobId|itemId 变化不够：同任务从 step=1 链到 step=2 时须重新 hydrate，否则 hydrated 仍为 true 直接跳过 */
  const prevHydrateUrlStepRef = useRef<string | null>(null);
  /** 当步骤变化由向导内部导航触发时（非外部深链），跳过重新 hydrate，避免后端 pending 覆盖本地识别结果 */
  const internalStepNavRef = useRef(false);
  /** 避免步骤 1 反复 PUT 相同 config */
  const lastSavedJobConfigJson = useRef<string>('');
  /** 与 furthestStep 同步：仅在「前进」时立即 PUT，配置变更仍靠下方防抖 */
  const prevFurthestForImmediateSaveRef = useRef<Step>(1);

  useEffect(() => {
    try {
      if (activeJobId) sessionStorage.setItem(sessionJobKey, activeJobId);
      else sessionStorage.removeItem(sessionJobKey);
    } catch {
      /* ignore */
    }
  }, [activeJobId, sessionJobKey]);

  /** URL 中的 jobId 优先于 session，避免深链与本地缓存双主源不一致 */
  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid) return;
    setActiveJobId(prev => (prev === jid ? prev : jid));
  }, [searchParams]);

  useEffect(() => {
    lastSavedJobConfigJson.current = '';
  }, [activeJobId]);

  useEffect(() => {
    prevFurthestForImmediateSaveRef.current = 1;
  }, [activeJobId]);

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
  const [reviewDraftSaving, setReviewDraftSaving] = useState(false);
  const [reviewDraftError, setReviewDraftError] = useState<string | null>(null);
  const [reviewImagePreview, setReviewImagePreview] = useState('');
  const [reviewImagePreviewLoading, setReviewImagePreviewLoading] = useState(false);
  const [reviewOrigImageBlobUrl, setReviewOrigImageBlobUrl] = useState('');
  const [reviewTextUndoStack, setReviewTextUndoStack] = useState<ReviewEntity[][]>([]);
  const [reviewTextRedoStack, setReviewTextRedoStack] = useState<ReviewEntity[][]>([]);
  const [reviewImageUndoStack, setReviewImageUndoStack] = useState<EditorBox[][]>([]);
  const [reviewImageRedoStack, setReviewImageRedoStack] = useState<EditorBox[][]>([]);
  const [reviewSelectedText, setReviewSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [reviewSelectedOverlapIds, setReviewSelectedOverlapIds] = useState<string[]>([]);
  const [reviewSelectionPos, setReviewSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [reviewSelectedTypeId, setReviewSelectedTypeId] = useState('');
  const [reviewClickedEntity, setReviewClickedEntity] = useState<ReviewEntity | null>(null);
  const [reviewEntityPopupPos, setReviewEntityPopupPos] = useState<{ left: number; top: number } | null>(null);
  /** 文本类第 4 步：与 Playground 一致的原文展示 */
  const [reviewTextContent, setReviewTextContent] = useState('');
  /** 后端 preview-map，与「确认脱敏」执行时 entity_map 一致 */
  const [previewEntityMap, setPreviewEntityMap] = useState<Record<string, string>>({});
  /** 识别项点击跳转：与 Playground 一致，同 key 多处分次循环定位 */
  const reviewTextContentRef = useRef<HTMLDivElement | null>(null);
  const reviewTextScrollRef = useRef<HTMLDivElement | null>(null);
  const reviewSelectionRangeRef = useRef<Range | null>(null);
  const reviewAutosaveTimerRef = useRef<number | null>(null);
  const reviewLastSavedJsonRef = useRef('');
  const reviewDraftInitializedRef = useRef(false);
  const reviewDraftDirtyRef = useRef(false);
  const batchScrollCountersRef = useRef<Record<string, number>>({});
  const reviewLoadSeqRef = useRef(0);
  /** 步骤 1 显式确认（避免默认全选时未阅读即可进入上传） */
  const [confirmStep1, setConfirmStep1] = useState(false);
  /** 任务优先级 */
  const [jobPriority, setJobPriority] = useState<number>(0);

  /** 已绑定工单且仍为草稿时，将配置与 wizard_furthest_step 防抖同步（PUT）；非 draft 时接口 400，忽略即可 */
  useEffect(() => {
    if (!configLoaded || !activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    const timer = window.setTimeout(() => {
      if (j === lastSavedJobConfigJson.current) return;
      void (async () => {
        try {
          await updateJobDraft(activeJobId, { config: payload });
          lastSavedJobConfigJson.current = j;
        } catch {
          /* 仅 draft 可写；下一步或提交时仍会重试 */
        }
      })();
    }, 900);
    return () => window.clearTimeout(timer);
  }, [cfg, mode, activeJobId, configLoaded, furthestStep]);

  /** furthestStep 变大时立即持久化 wizard_furthest_step（不等待 900ms），避免离开页面前未写入任务 config */
  useEffect(() => {
    if (!configLoaded || !activeJobId) return;
    const prev = prevFurthestForImmediateSaveRef.current;
    if (furthestStep < 2) {
      prevFurthestForImmediateSaveRef.current = furthestStep;
      return;
    }
    if (furthestStep <= prev) {
      prevFurthestForImmediateSaveRef.current = furthestStep;
      return;
    }
    prevFurthestForImmediateSaveRef.current = furthestStep;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    void (async () => {
      try {
        await updateJobDraft(activeJobId, { config: payload });
        lastSavedJobConfigJson.current = j;
      } catch {
        /* 仅 draft 可写 */
      }
    })();
  }, [furthestStep, cfg, mode, activeJobId, configLoaded]);

  useEffect(() => {
    const urlJobId = searchParams.get('jobId');
    if (!activeJobId || furthestStep < 2) return;
    // 防止 Job ID 切换时旧 furthestStep 错写到新任务
    if (activeJobId !== urlJobId) return;
    writeLocalWizardMaxStep(activeJobId, furthestStep);
  }, [activeJobId, furthestStep, searchParams]);

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
          executionDefault: persisted?.executionDefault === 'local' ? 'local' : 'queue',
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
        if (!pt && persisted === null) {
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
        if (!pv && persisted === null) {
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

  /** 任务详情深链：?jobId=&itemId=&step= 恢复单文件审阅 */
  useEffect(() => {
    const jobId = searchParams.get('jobId');
    const itemId = searchParams.get('itemId');
    const stepRaw = searchParams.get('step');
    const isNewlyCreated = searchParams.get('new') === '1';
    /** jobId|itemId 与 URL 的 step 分离：step 变化时清 hydrated，避免「继续上传」深链仍当已恢复而跳过 */
    const jobItemKey = `${jobId ?? ''}|${itemId ?? ''}`;
    if (urlHydrateKeyRef.current !== jobItemKey) {
      urlHydrateKeyRef.current = jobItemKey;
      hydratedFromUrlRef.current = false;
      prevHydrateUrlStepRef.current = null;
    }
    const stepKey = stepRaw ?? '';
    if (prevHydrateUrlStepRef.current !== null && prevHydrateUrlStepRef.current !== stepKey) {
      if (internalStepNavRef.current) {
        // 内部步骤切换（用户在向导内点击）：保留 hydrated 状态，不重新从后端拉取
        internalStepNavRef.current = false;
      } else {
        hydratedFromUrlRef.current = false;
      }
    }
    prevHydrateUrlStepRef.current = stepKey;

    const snUrl = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
    const urlStepParsed = Number.isFinite(snUrl) ? (Math.min(5, Math.max(1, snUrl)) as Step) : null;
    /** 仅处理「深链要求更靠前但 UI 仍落后」（含 hydrated 误 true）；勿在 step>URL 时清（用户已前进、URL 同步稍晚） */
    if (hydratedFromUrlRef.current && urlStepParsed !== null && step < urlStepParsed) {
      hydratedFromUrlRef.current = false;
    }

    if (!configLoaded || !jobId || hydratedFromUrlRef.current) return;
    const hydrateGen = ++batchHydrateGenRef.current;
    (async () => {
      try {
        const detail = await getJob(jobId);
        if (hydrateGen !== batchHydrateGenRef.current) return;
        // 兼容旧 text_batch / image_batch 任务，统一按 smart 处理
        const validTypes: string[] = ['smart_batch', 'text_batch', 'image_batch'];
        if (!validTypes.includes(detail.job_type)) {
          setMsg({ text: '该任务类型与当前批量向导不匹配，请从任务中心打开对应入口', tone: 'warn' });
          return;
        }
        setActiveJobId(jobId);
        const jc = detail.config as Record<string, unknown>;
        const mergedCfg = mergeJobConfigIntoWizardCfg(cfg, jc);
        setCfg(mergedCfg);

        const jobTypeNav: 'smart_batch' | 'text_batch' | 'image_batch' =
          (['smart_batch', 'text_batch', 'image_batch'].includes(detail.job_type) ? detail.job_type : 'smart_batch') as 'smart_batch' | 'text_batch' | 'image_batch';
        const restoredFurthest: Step | null = effectiveWizardFurthestStep({
          jobConfig: jc,
          navHints: detail.nav_hints,
          jobType: jobTypeNav,
        });

        const persistDraftFingerprint = (furthest: Step) => {
          lastSavedJobConfigJson.current = JSON.stringify(buildJobConfigForWorker(mergedCfg!, mode, furthest));
        };

        /** 无文件项时仍须恢复步骤（如已取消/深链 step=3），避免停在默认 Step1 */
        if (detail.items.length === 0) {
          const sn = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
          const urlStep = Number.isFinite(sn) ? (Math.min(5, Math.max(1, sn)) as Step) : null;
          const sessionMax = readLocalWizardMaxStep(jobId);
          /** URL 已写明 step≥2 时，不再用 localStorage 把「继续上传」深链抬成更高步（避免旧 lr_batch_wiz_* 卡住 Step1） */
          const baseEmpty =
            urlStep !== null && urlStep >= 2
              ? Math.max(restoredFurthest ?? 1, urlStep)
              : Math.max(restoredFurthest ?? 1, sessionMax ?? 1);
          const rawNext = Math.max(urlStep ?? 1, baseEmpty) as Step;
          const beforeClamp = rawNext;
          const nextStep: Step = rawNext > 3 ? 3 : rawNext;
          if (beforeClamp > 3) {
            setMsg({
              text: '当前任务暂无文件，无法进入审阅或导出，已切换到「批量识别」步骤',
              tone: 'warn',
            });
          } else if (!isNewlyCreated) {
            setMsg({ text: '已从任务恢复', tone: 'neutral' });
          }
          itemIdByFileIdRef.current = {};
          setRows([]);
          setSelected(new Set());
          setReviewIndex(0);
          batchGroupIdRef.current = jobId;
          if (nextStep >= 2) setConfirmStep1(true);
          setStep(nextStep);
          const mergedFurthest = Math.max(restoredFurthest ?? 1, nextStep, sessionMax ?? 1) as Step;
          setFurthestStep(prev => Math.max(prev, mergedFurthest) as Step);
          persistDraftFingerprint(mergedFurthest);
          if (detail.status === 'draft') {
            const payload = buildJobConfigForWorker(mergedCfg!, mode, mergedFurthest);
            try {
              await updateJobDraft(jobId, { config: payload });
              if (hydrateGen !== batchHydrateGenRef.current) return;
              lastSavedJobConfigJson.current = JSON.stringify(payload);
            } catch {
              /* 非草稿等 */
            }
          }
          if (hydrateGen !== batchHydrateGenRef.current) return;
          hydratedFromUrlRef.current = true;
          return;
        }

        const badItemIdInUrl = Boolean(itemId && !detail.items.some(i => i.id === itemId));
        const item =
          itemId && !badItemIdInUrl
            ? detail.items.find(i => i.id === itemId)
            : detail.items[0];
        if (!item) {
          setMsg({ text: '任务中未找到对应文件项', tone: 'warn' });
          return;
        }

        const sn0 = stepRaw ? Number.parseInt(stepRaw, 10) : NaN;
        const urlStepNum0 = Number.isFinite(sn0) ? (Math.min(5, Math.max(1, sn0)) as Step) : null;
        const sessionMaxItems0 = readLocalWizardMaxStep(jobId);
        const basePersist0 =
          urlStepNum0 !== null && urlStepNum0 >= 2
            ? Math.max(restoredFurthest ?? 1, urlStepNum0)
            : Math.max(restoredFurthest ?? 1, sessionMaxItems0 ?? 1);
        let resolvedNextStep: Step;
        if (urlStepNum0 !== null) {
          resolvedNextStep = Math.max(urlStepNum0, basePersist0) as Step;
        } else if (detail.status === 'draft') {
          resolvedNextStep = Math.min(5, Math.max(2, basePersist0)) as Step;
        } else if (detail.status === 'awaiting_review') {
          resolvedNextStep = 4;
        } else {
          resolvedNextStep = Math.min(5, Math.max(3, basePersist0)) as Step;
        }
        /**
         * 有文件项时原逻辑在「拉齐所有 batchGetFileRaw」后才 setStep，慢请求期间界面一直停在默认 Step1。
         * Step2/3 不依赖文件元数据拉取完成即可展示；Step4+ 需审阅数据，仍在拉齐后再切。
         */
        if (resolvedNextStep >= 2 && resolvedNextStep <= 3) {
          setConfirmStep1(true);
          setStep(resolvedNextStep);
          setFurthestStep(prev => Math.max(prev, restoredFurthest ?? 1, resolvedNextStep) as Step);
          persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedNextStep) as Step);
        }

        const hydratedItems = await Promise.all(
          detail.items.map(async entry => {
            const info = await batchGetFileRaw(entry.file_id);
            return { item: entry, info };
          })
        );
        if (hydrateGen !== batchHydrateGenRef.current) return;
        const urlMatchIndex = Math.max(0, hydratedItems.findIndex(entry => entry.item.id === item.id));
        // 如果 URL 指向已脱敏 item，跳到第一个待审核的
        const urlMatchHasOutput = Boolean((hydratedItems[urlMatchIndex]?.info || {}).output_path);
        const firstPendingIdx = urlMatchHasOutput
          ? hydratedItems.findIndex(e => !e.info?.output_path && RECOGNITION_DONE_STATUSES.has(mapBackendStatus(e.item.status)))
          : -1;
        const currentIndex = firstPendingIdx >= 0 ? firstPendingIdx : urlMatchIndex;
        const fileIdToItemId = Object.fromEntries(hydratedItems.map(entry => [entry.item.file_id, entry.item.id]));
        const rowsFromJob: BatchRow[] = hydratedItems.map(entry => {
          const rowInfo = entry.info;
          const rowFileTypeRaw = String(rowInfo.file_type ?? entry.item.file_type ?? 'docx').toLowerCase();
          const isScanned = Boolean(rowInfo.is_scanned);
          const rowFileType: FileType =
            rowFileTypeRaw === 'image' || rowFileTypeRaw === 'jpg' || rowFileTypeRaw === 'jpeg' || rowFileTypeRaw === 'png'
              ? FileType.IMAGE
              : rowFileTypeRaw === 'pdf_scanned' || (rowFileTypeRaw === 'pdf' && isScanned)
                ? FileType.PDF_SCANNED
                : rowFileTypeRaw === 'pdf'
                  ? FileType.PDF
                  : FileType.DOCX;
          return {
            file_id: entry.item.file_id,
            original_filename: String(rowInfo.original_filename ?? entry.item.filename ?? entry.item.file_id),
            file_size: Number(rowInfo.file_size ?? 0),
            file_type: rowFileType,
            created_at: String(rowInfo.created_at ?? entry.item.created_at ?? ''),
            has_output: Boolean(rowInfo.output_path ?? entry.item.has_output),
            reviewConfirmed: deriveReviewConfirmed(entry.item),
            entity_count:
              typeof entry.item.entity_count === 'number'
                ? entry.item.entity_count
                : Array.isArray(rowInfo.entities)
                  ? rowInfo.entities.length
                  : 0,
            analyzeStatus: mapBackendStatus(entry.item.status),
            analyzeError: entry.item.status === 'failed' || entry.item.status === 'cancelled'
              ? (entry.item.error_message || '处理失败')
              : undefined,
            isImageMode: rowFileType === FileType.IMAGE || rowFileType === FileType.PDF_SCANNED,
          };
        });
        const allRowsReviewConfirmed = rowsFromJob.length > 0 && rowsFromJob.every(row => row.reviewConfirmed === true);
        const anyRecognitionDone = rowsFromJob.some(row => RECOGNITION_DONE_STATUSES.has(row.analyzeStatus));
        let resolvedStepWithGates = resolvedNextStep;
        // step 4 gate: 至少一个文件完成识别才能进入审阅
        if (resolvedStepWithGates >= 4 && !anyRecognitionDone) {
          resolvedStepWithGates = 3 as Step;
        }
        // step 5 gate: 所有文件审核确认才能进入导出
        if (resolvedStepWithGates === 5 && !allRowsReviewConfirmed) {
          resolvedStepWithGates = 4 as Step;
        }
        itemIdByFileIdRef.current = fileIdToItemId;
        setJobSkipItemReview(Boolean(detail.skip_item_review));
        setRows(rowsFromJob);
        setSelected(new Set(rowsFromJob.map(row => row.file_id)));
        setReviewIndex(currentIndex);
        batchGroupIdRef.current = jobId;
        if (resolvedStepWithGates >= 2) setConfirmStep1(true);
        setStep(resolvedStepWithGates);
        setFurthestStep(prev => Math.max(prev, restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        persistDraftFingerprint(Math.max(restoredFurthest ?? 1, resolvedStepWithGates) as Step);
        hydratedFromUrlRef.current = true;
        if (badItemIdInUrl) {
          setMsg({ text: '链接中的文件项已失效，已切换到列表中的第一个文件，可继续审阅或脱敏', tone: 'warn' });
        } else if (!isNewlyCreated) {
          setMsg({ text: '已从任务恢复，可继续审阅或脱敏', tone: 'neutral' });
        }
      } catch (e) {
        if (hydrateGen === batchHydrateGenRef.current) {
          setMsg({ text: e instanceof Error ? e.message : '加载任务失败', tone: 'err' });
        }
      }
    })();
    return () => {
      batchHydrateGenRef.current += 1;
    };
  }, [configLoaded, location.search, mode]);

  /** 有 jobId 且已完成深链恢复后，把当前 step 写回 URL，避免任务中心返回时仅靠 step=1 深链 */
  useEffect(() => {
    const jid = searchParams.get('jobId');
    if (!jid || !activeJobId || jid !== activeJobId) return;
    if (!hydratedFromUrlRef.current) return;
    const cur = searchParams.get('step');
    if (cur === String(step)) return;
    const sp = new URLSearchParams(searchParams);
    sp.set('step', String(step));
    setSearchParams(sp, { replace: true });
  }, [step, activeJobId, searchParams, setSearchParams]);

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

  /** 步骤 1 完成：已勾选确认 + 配置已加载；文本链至少选一类；图像链至少启用一路识别（可仅 OCR+HaS 或仅 HaS Image）；smart 需至少一个文本类型或一个图像类型 */
  const isStep1Complete = useMemo(() => {
    if (!confirmStep1) return false;
    if (!configLoaded) return false;
    // smart 模式：至少选一个文本类型或一个图像类型
    const anyTextSelected = cfg.selectedEntityTypeIds.length > 0;
    const anyVisionSelected = cfg.ocrHasTypes.length > 0 || cfg.hasImageTypes.length > 0;
    return anyTextSelected || anyVisionSelected;
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

  const doneRows = useMemo(() => rows.filter(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus)), [rows]);
  const failedRows = useMemo(() => rows.filter(r => r.analyzeStatus === 'failed'), [rows]);
  const reviewFile = doneRows[reviewIndex] ?? null;
  const reviewedOutputCount = useMemo(() => rows.filter(r => r.reviewConfirmed === true).length, [rows]);
  const pendingReviewCount = Math.max(0, rows.length - reviewedOutputCount);
  const allReviewConfirmed = rows.length > 0 && pendingReviewCount === 0;
  const reviewItemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
  const reviewFileReadOnly = reviewFile?.analyzeStatus === 'completed' || reviewFile?.analyzeStatus === 'redacting';

  const buildCurrentReviewDraftPayload = useCallback(() => {
    const entities = reviewEntities.map(e => ({
      id: e.id,
      text: e.text,
      type: e.type,
      start: e.start,
      end: e.end,
      page: e.page ?? 1,
      confidence: e.confidence ?? 1,
      selected: e.selected,
      source: e.source,
      coref_id: e.coref_id,
      replacement: e.replacement,
    }));
    const bounding_boxes = reviewBoxes.map(b => ({
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
      confidence: b.confidence,
    }));
    return { entities, bounding_boxes };
  }, [reviewEntities, reviewBoxes]);

  const flushCurrentReviewDraft = useCallback(async () => {
    const jid = activeJobId;
    const itemId = reviewFile ? itemIdByFileIdRef.current[reviewFile.file_id] : undefined;
    if (!jid || !itemId || !reviewDraftInitializedRef.current) return true;
    const payload = buildCurrentReviewDraftPayload();
    const json = JSON.stringify(payload);
    if (json === reviewLastSavedJsonRef.current) return true;
    setReviewDraftSaving(true);
    setReviewDraftError(null);
    try {
      const res = await putItemReviewDraft(jid, itemId, payload);
      reviewLastSavedJsonRef.current = JSON.stringify(payload);
      reviewDraftDirtyRef.current = false;
      if (res?.updated_at) {
        const nextItemId = itemId;
        setRows(prev =>
          prev.map(r =>
            itemIdByFileIdRef.current[r.file_id] === nextItemId ? { ...r } : r
          )
        );
      }
      return true;
    } catch (e) {
      setReviewDraftError(e instanceof Error ? e.message : '自动保存失败');
      return false;
    } finally {
      setReviewDraftSaving(false);
    }
  }, [activeJobId, buildCurrentReviewDraftPayload, reviewFile]);

  const pushReviewTextHistory = useCallback((prev: ReviewEntity[]) => {
    setReviewTextUndoStack(stack => [...stack, prev.map(e => ({ ...e }))]);
    setReviewTextRedoStack([]);
  }, []);

  const applyReviewEntities = useCallback((updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => {
    setReviewEntities(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      pushReviewTextHistory(prev);
      reviewDraftDirtyRef.current = true;
      return next;
    });
  }, [pushReviewTextHistory]);

  const undoReviewText = useCallback(() => {
    setReviewTextUndoStack(stack => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setReviewTextRedoStack(redo => [...redo, reviewEntities.map(e => ({ ...e }))]);
      setReviewEntities(prev.map(e => ({ ...e })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewEntities]);

  const redoReviewText = useCallback(() => {
    setReviewTextRedoStack(stack => {
      if (!stack.length) return stack;
      const next = stack[stack.length - 1];
      setReviewTextUndoStack(undo => [...undo, reviewEntities.map(e => ({ ...e }))]);
      setReviewEntities(next.map(e => ({ ...e })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewEntities]);

  const undoReviewImage = useCallback(() => {
    setReviewImageUndoStack(stack => {
      if (!stack.length) return stack;
      const prev = stack[stack.length - 1];
      setReviewImageRedoStack(redo => [...redo, reviewBoxes.map(b => ({ ...b }))]);
      setReviewBoxes(prev.map(b => ({ ...b })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewBoxes]);

  const redoReviewImage = useCallback(() => {
    setReviewImageRedoStack(stack => {
      if (!stack.length) return stack;
      const next = stack[stack.length - 1];
      setReviewImageUndoStack(undo => [...undo, reviewBoxes.map(b => ({ ...b }))]);
      setReviewBoxes(next.map(b => ({ ...b })));
      reviewDraftDirtyRef.current = true;
      return stack.slice(0, -1);
    });
  }, [reviewBoxes]);

  useEffect(() => {
    batchScrollCountersRef.current = {};
  }, [reviewFile?.file_id]);

  // Resolve authenticated blob URL for original image in review
  useEffect(() => {
    let cancelled = false;
    let currentBlobUrl = '';
    if (!reviewFile || !reviewFile.isImageMode) { setReviewOrigImageBlobUrl(''); return; }
    const raw = fileApi.getDownloadUrl(reviewFile.file_id, false);
    authenticatedBlobUrl(raw).then(u => {
      if (!cancelled) { currentBlobUrl = u; setReviewOrigImageBlobUrl(u); }
      else if (u.startsWith('blob:')) URL.revokeObjectURL(u);
    }).catch(() => { if (!cancelled) setReviewOrigImageBlobUrl(raw); });
    return () => {
      cancelled = true;
      if (currentBlobUrl.startsWith('blob:')) URL.revokeObjectURL(currentBlobUrl);
    };
  }, [reviewFile?.file_id, reviewFile?.isImageMode]);

  /** 与 loadReviewData 同帧：先置 loading，避免预览 effect 在实体加载前用空列表清空映射 */
  useLayoutEffect(() => {
    if (step !== 4 || !reviewFile) return;
    setReviewLoading(true);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode]);

  const loadReviewData = useCallback(
    async (fileId: string, isImage: boolean) => {
      const loadSeq = reviewLoadSeqRef.current + 1;
      reviewLoadSeqRef.current = loadSeq;
      setReviewLoading(true);
      setPreviewEntityMap({});
      setReviewImagePreview('');
      setReviewDraftError(null);
      setReviewEntities([]);
      setReviewBoxes([]);
      setReviewTextContent('');
      reviewDraftInitializedRef.current = false;
      reviewDraftDirtyRef.current = false;
      if (reviewAutosaveTimerRef.current !== null) {
        window.clearTimeout(reviewAutosaveTimerRef.current);
        reviewAutosaveTimerRef.current = null;
      }
      setReviewSelectedText(null);
      setReviewSelectedOverlapIds([]);
      setReviewSelectionPos(null);
      setReviewClickedEntity(null);
      setReviewEntityPopupPos(null);
      try {
        const info = await batchGetFileRaw(fileId);
        if (loadSeq !== reviewLoadSeqRef.current) return;
        const linkedItemId = itemIdByFileIdRef.current[fileId];
        let draft:
          | {
              exists?: boolean;
              entities?: Array<Record<string, unknown>>;
              bounding_boxes?: Array<Record<string, unknown>>;
            }
          | null = null;
        if (activeJobId && linkedItemId) {
          try {
            const loadedDraft = await getItemReviewDraft(activeJobId, linkedItemId);
            if (loadSeq !== reviewLoadSeqRef.current) return;
            if (loadedDraft.exists) {
              draft = loadedDraft;
            }
          } catch {
            /* ignore */
          }
        }
        if (isImage) {
          setReviewTextContent('');
          const raw =
            draft?.bounding_boxes && draft.bounding_boxes.length > 0
              ? draft.bounding_boxes
              : flattenBoundingBoxesFromStore(info.bounding_boxes);
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
          setReviewImageUndoStack([]);
          setReviewImageRedoStack([]);
          reviewLastSavedJsonRef.current = JSON.stringify({
            entities: [],
            bounding_boxes: boxes.map(b => ({
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
              confidence: b.confidence,
            })),
          });
        } else {
          setReviewEntities([]);
          setReviewTextContent('');
          const ents = ((draft?.entities as ReviewEntity[] | undefined) ?? (info.entities as ReviewEntity[]) ?? []);
          const mapped = ents.map((e, i) =>
            normalizeReviewEntity({
              id: e.id || `ent_${i}`,
              text: e.text,
              type: typeof e.type === 'string' ? e.type : String(e.type ?? 'CUSTOM'),
              start: typeof e.start === 'number' ? e.start : Number(e.start),
              end: typeof e.end === 'number' ? e.end : Number(e.end),
              selected: e.selected !== false,
              page: e.page ?? 1,
              confidence: e.confidence,
              source: e.source,
              coref_id: e.coref_id,
              replacement: e.replacement,
            })
          );
          setReviewBoxes([]);
          const c = info.content;
          const contentStr = typeof c === 'string' ? c : '';
          setReviewEntities(mapped);
          setReviewTextContent(contentStr);
          setReviewSelectedTypeId(mapped[0]?.type ?? cfg.selectedEntityTypeIds[0] ?? textTypes[0]?.id ?? 'CUSTOM');
          setReviewTextUndoStack([]);
          setReviewTextRedoStack([]);
          const map = await fetchBatchPreviewMap(mapped, cfg.replacementMode);
          if (loadSeq !== reviewLoadSeqRef.current) return;
          setPreviewEntityMap(map);
          reviewLastSavedJsonRef.current = JSON.stringify({
            entities: mapped.map(e => ({
              id: e.id,
              text: e.text,
              type: e.type,
              start: e.start,
              end: e.end,
              page: e.page ?? 1,
              confidence: e.confidence ?? 1,
              selected: e.selected,
              source: e.source,
              coref_id: e.coref_id,
              replacement: e.replacement,
            })),
            bounding_boxes: [],
          });
        }
        reviewDraftInitializedRef.current = true;
      } finally {
        if (loadSeq === reviewLoadSeqRef.current) {
          setReviewLoading(false);
        }
      }
    },
    [activeJobId, cfg.replacementMode, cfg.selectedEntityTypeIds, textTypes]
  );

  useEffect(() => {
    if (step !== 4 || !reviewFile) return;
    const isImg = reviewFile.isImageMode === true;
    void loadReviewData(reviewFile.file_id, isImg);
  }, [step, reviewFile?.file_id, reviewFile?.isImageMode, loadReviewData]);

  useEffect(() => {
    if (reviewSelectedTypeId) return;
    const next = cfg.selectedEntityTypeIds[0] ?? textTypes[0]?.id ?? '';
    if (next) setReviewSelectedTypeId(next);
  }, [cfg.selectedEntityTypeIds, reviewSelectedTypeId, textTypes]);

  useEffect(() => {
    if (step !== 4 || !reviewFile || !reviewDraftInitializedRef.current) return;
    if (!activeJobId || !reviewItemId) return;
    const payload = buildCurrentReviewDraftPayload();
    const json = JSON.stringify(payload);
    if (json === reviewLastSavedJsonRef.current) return;
    reviewDraftDirtyRef.current = true;
    if (reviewAutosaveTimerRef.current !== null) {
      window.clearTimeout(reviewAutosaveTimerRef.current);
    }
    reviewAutosaveTimerRef.current = window.setTimeout(() => {
      void flushCurrentReviewDraft();
    }, 900);
    return () => {
      if (reviewAutosaveTimerRef.current !== null) {
        window.clearTimeout(reviewAutosaveTimerRef.current);
        reviewAutosaveTimerRef.current = null;
      }
    };
  }, [step, reviewFile?.file_id, reviewItemId, activeJobId, buildCurrentReviewDraftPayload, flushCurrentReviewDraft]);

  /** 文本批量第 4 步：配置变化时刷新替换预览（防抖；首屏映射由 loadReviewData 内联请求） */
  useEffect(() => {
    if (step !== 4 || !reviewFile || reviewLoading || reviewFile.isImageMode) return;
    if (!reviewTextContent) return;
    if (reviewEntities.length === 0) {
      setPreviewEntityMap({});
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(async () => {
      const map = await fetchBatchPreviewMap(reviewEntities, cfg.replacementMode);
      if (!cancelled) setPreviewEntityMap(map);
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [step, mode, reviewFile?.file_id, reviewEntities, reviewTextContent, reviewLoading, cfg.replacementMode]);

  useEffect(() => {
    if (step !== 4 || !reviewFile || reviewLoading || !reviewFile.isImageMode) return;
    let cancelled = false;
    const t = window.setTimeout(async () => {
      try {
        setReviewImagePreviewLoading(true);
        const imageBase64 = await batchPreviewImage({
          file_id: reviewFile.file_id,
          page: 1,
          bounding_boxes: reviewBoxes
            .filter(b => b.selected !== false)
            .map(b => ({
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
              confidence: b.confidence,
            })),
          config: {
            replacement_mode: ReplacementMode.STRUCTURED,
            entity_types: [],
            custom_replacements: {},
            image_redaction_method: cfg.imageRedactionMethod ?? 'mosaic',
            image_redaction_strength: cfg.imageRedactionStrength ?? 25,
            image_fill_color: cfg.imageFillColor ?? '#000000',
          },
        });
        if (!cancelled) setReviewImagePreview(imageBase64);
      } catch {
        if (!cancelled) setReviewImagePreview('');
      } finally {
        if (!cancelled) setReviewImagePreviewLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [
    step,
    mode,
    reviewFile?.file_id,
    reviewBoxes,
    reviewLoading,
    cfg.imageRedactionMethod,
    cfg.imageRedactionStrength,
    cfg.imageFillColor,
  ]);

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
      const riskCfg = getEntityRiskConfig(tid);
      return {
        backgroundColor: riskCfg.bgColor,
        color: riskCfg.textColor,
        boxShadow: `inset 0 ${'-2px'} 0 ${String(riskCfg.color)}50`,
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

  const getReviewSelectionOffsets = useCallback((range: Range, root: HTMLElement) => {
    let start = -1;
    let end = -1;
    let offset = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      const textLength = node.textContent?.length || 0;
      if (node === range.startContainer) {
        start = offset + range.startOffset;
      }
      if (node === range.endContainer) {
        end = offset + range.endOffset;
        break;
      }
      offset += textLength;
    }
    if (start === -1 || end === -1 || end <= start) return null;
    return { start, end };
  }, []);

  const toggleReviewEntitySelected = useCallback((entityId: string) => {
    applyReviewEntities(prev =>
      prev.map(e => (e.id === entityId ? { ...e, selected: !e.selected } : e))
    );
    setReviewClickedEntity(prev =>
      prev && prev.id === entityId ? { ...prev, selected: !prev.selected } : prev
    );
  }, [applyReviewEntities]);

  const handleReviewEntityClick = useCallback((entity: ReviewEntity, event: React.MouseEvent) => {
    event.stopPropagation();
    reviewSelectionRangeRef.current = null;
    setReviewSelectedText(null);
    setReviewSelectionPos(null);
    setReviewSelectedOverlapIds([]);
    setReviewClickedEntity(entity);
    setReviewSelectedTypeId(entity.type);
  }, []);

  const handleReviewTextSelect = useCallback(() => {
    if (step !== 4 || reviewFile?.isImageMode) return;
    if (reviewClickedEntity) return;
    const selection = window.getSelection();
    const root = reviewTextContentRef.current;
    if (!selection || !root) {
      reviewSelectionRangeRef.current = null;
      setReviewSelectedText(null);
      setReviewSelectionPos(null);
      setReviewSelectedOverlapIds([]);
      return;
    }
    if (selection.isCollapsed) {
      if (reviewSelectedText && reviewSelectionPos) return;
      reviewSelectionRangeRef.current = null;
      setReviewSelectedText(null);
      setReviewSelectionPos(null);
      setReviewSelectedOverlapIds([]);
      return;
    }
    const text = selection.toString().trim();
    if (!text || text.length < 1) {
      reviewSelectionRangeRef.current = null;
      setReviewSelectedText(null);
      setReviewSelectionPos(null);
      setReviewSelectedOverlapIds([]);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
      reviewSelectionRangeRef.current = null;
      setReviewSelectedText(null);
      setReviewSelectionPos(null);
      setReviewSelectedOverlapIds([]);
      return;
    }
    const offsets = getReviewSelectionOffsets(range, root);
    const start = offsets?.start ?? reviewTextContent.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end <= start) {
      reviewSelectionRangeRef.current = null;
      setReviewSelectedText(null);
      setReviewSelectionPos(null);
      setReviewSelectedOverlapIds([]);
      return;
    }
    const overlaps = reviewEntities.filter(e => (e.start < end && e.end > start));
    try {
      reviewSelectionRangeRef.current = range.cloneRange();
    } catch {
      reviewSelectionRangeRef.current = null;
    }
    if (overlaps[0]) {
      setReviewSelectedTypeId(overlaps[0].type);
    } else if (!reviewSelectedTypeId) {
      setReviewSelectedTypeId(cfg.selectedEntityTypeIds[0] ?? textTypes[0]?.id ?? 'CUSTOM');
    }
    setReviewSelectedOverlapIds(overlaps.map(e => e.id));
    setReviewSelectionPos(null);
    setReviewSelectedText({ text, start, end });
  }, [
    step,
    mode,
    reviewClickedEntity,
    reviewSelectedText,
    reviewSelectionPos,
    getReviewSelectionOffsets,
    reviewTextContent,
    reviewEntities,
    reviewSelectedTypeId,
    cfg.selectedEntityTypeIds,
    textTypes,
  ]);

  useLayoutEffect(() => {
    if (!reviewSelectedText) {
      reviewSelectionRangeRef.current = null;
      setReviewSelectionPos(null);
      return;
    }
    const root = reviewTextContentRef.current;
    if (!root) return;

    const update = () => {
      const range = reviewSelectionRangeRef.current;
      if (!range || range.collapsed) {
        setReviewSelectionPos(null);
        return;
      }
      try {
        const rect = range.getBoundingClientRect();
        const canvas = root.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        setReviewSelectionPos(clampPopoverInCanvas(rect, canvas, 360, 320));
      } catch {
        setReviewSelectionPos(null);
      }
    };

    update();
    const scrollEl = reviewTextScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [reviewSelectedText]);

  useLayoutEffect(() => {
    if (!reviewClickedEntity) {
      setReviewEntityPopupPos(null);
      return;
    }
    const root = reviewTextContentRef.current;
    if (!root) return;

    const update = () => {
      let el: HTMLElement | null = null;
      try {
        el = root.querySelector(`[data-review-entity-id="${CSS.escape(reviewClickedEntity.id)}"]`);
      } catch {
        el = null;
      }
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const canvas = root.getBoundingClientRect();
      setReviewEntityPopupPos(clampPopoverInCanvas(rect, canvas, 240, 240));
    };

    update();
    const scrollEl = reviewTextScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [reviewClickedEntity]);

  const addManualReviewEntity = useCallback((typeId: string) => {
    if (!reviewSelectedText) return;
    const nextEntity: ReviewEntity = normalizeReviewEntity({
      id: `manual_${Date.now()}`,
      text: reviewSelectedText.text,
      type: typeId,
      start: reviewSelectedText.start,
      end: reviewSelectedText.end,
      selected: true,
      page: 1,
      confidence: 1,
      source: 'manual',
    });
    applyReviewEntities(prev =>
      prev
        .filter(e => !reviewSelectedOverlapIds.includes(e.id))
        .concat(nextEntity)
        .sort((a, b) => a.start - b.start)
    );
    reviewSelectionRangeRef.current = null;
    setReviewSelectedText(null);
    setReviewSelectionPos(null);
    setReviewSelectedOverlapIds([]);
    window.getSelection()?.removeAllRanges();
  }, [applyReviewEntities, reviewSelectedOverlapIds, reviewSelectedText]);

  const removeSelectedReviewEntities = useCallback(() => {
    if (!reviewSelectedOverlapIds.length) return;
    applyReviewEntities(prev => prev.filter(e => !reviewSelectedOverlapIds.includes(e.id)));
    reviewSelectionRangeRef.current = null;
    setReviewSelectedText(null);
    setReviewSelectionPos(null);
    setReviewSelectedOverlapIds([]);
    window.getSelection()?.removeAllRanges();
  }, [applyReviewEntities, reviewSelectedOverlapIds]);

  const updateClickedReviewEntityType = useCallback((typeId: string) => {
    if (!reviewClickedEntity) return;
    applyReviewEntities(prev =>
      prev.map(e => (e.id === reviewClickedEntity.id ? normalizeReviewEntity({ ...e, type: typeId, source: e.source ?? 'manual' }) : e))
    );
    setReviewClickedEntity(prev => (prev ? { ...prev, type: typeId } : prev));
    setReviewSelectedTypeId(typeId);
  }, [applyReviewEntities, reviewClickedEntity]);

  const removeClickedReviewEntity = useCallback(() => {
    if (!reviewClickedEntity) return;
    applyReviewEntities(prev => prev.filter(e => e.id !== reviewClickedEntity.id));
    setReviewClickedEntity(null);
    setReviewEntityPopupPos(null);
  }, [applyReviewEntities, reviewClickedEntity]);

  const renderReviewMarkedContent = useCallback(() => {
    if (!reviewTextContent) return <p className="text-gray-400">暂无文本</p>;
    const sorted = [...reviewEntities].sort((a, b) => a.start - b.start);
    const nodes: React.ReactNode[] = [];
    const counters: Record<string, number> = {};
    let lastEnd = 0;
    sorted.forEach(entity => {
      if (entity.start < lastEnd) return;
      if (entity.start > lastEnd) {
        nodes.push(<span key={`txt-${lastEnd}`}>{reviewTextContent.slice(lastEnd, entity.start)}</span>);
      }
      const risk = getEntityRiskConfig(entity.type);
      const orig = reviewTextContent.slice(entity.start, entity.end) || entity.text;
      const safeKey = orig.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
      const matchIdx = counters[safeKey] || 0;
      counters[safeKey] = matchIdx + 1;
      nodes.push(
        <span
          key={entity.id}
          data-review-entity-id={entity.id}
          data-match-key={safeKey}
          data-match-idx={matchIdx}
          onClick={e => handleReviewEntityClick(entity, e)}
          className="result-mark-orig cursor-pointer transition-all inline-flex items-center gap-0.5 rounded px-0.5 -mx-0.5 hover:ring-2 hover:ring-offset-1 hover:ring-[#007AFF]/20"
          style={{
            backgroundColor: risk.bgColor,
            color: risk.textColor,
            opacity: entity.selected ? 1 : 0.45,
            boxShadow: `inset 0 ${'-2px'} 0 ${String(risk.color)}50`,
          }}
          title={`${getEntityTypeName(entity.type)} - 点击编辑`}
        >
          {reviewTextContent.slice(entity.start, entity.end)}
        </span>
      );
      lastEnd = entity.end;
    });
    if (lastEnd < reviewTextContent.length) {
      nodes.push(<span key="txt-end">{reviewTextContent.slice(lastEnd)}</span>);
    }
    return nodes;
  }, [reviewEntities, reviewTextContent, handleReviewEntityClick]);

  const navigateReviewIndex = useCallback(async (nextIndex: number) => {
    if (nextIndex < 0 || nextIndex >= doneRows.length || nextIndex === reviewIndex) return;
    if (reviewLoading) return; // 防止草稿加载中快速切换导致竞态
    await flushCurrentReviewDraft();
    setReviewIndex(nextIndex);
  }, [doneRows.length, flushCurrentReviewDraft, reviewIndex, reviewLoading]);

  const handleReviewBoxesCommit = useCallback((prevBoxes: EditorBox[], nextBoxes: EditorBox[]) => {
    setReviewImageUndoStack(stack => [...stack, prevBoxes.map(b => ({ ...b }))]);
    setReviewImageRedoStack([]);
    setReviewBoxes(nextBoxes.map(b => ({ ...b })));
    reviewDraftDirtyRef.current = true;
  }, []);

  const toggleReviewBoxSelected = useCallback((boxId: string) => {
    setReviewBoxes(prev => prev.map(b => (b.id === boxId ? { ...b, selected: !b.selected } : b)));
    reviewDraftDirtyRef.current = true;
  }, []);

  const reviewAvailableTextTypes = useMemo(() => {
    const selectedIds = new Set(cfg.selectedEntityTypeIds);
    const preferred = textTypes.filter(type => selectedIds.has(type.id));
    const currentIds = new Set(preferred.map(type => type.id));
    const currentTypeIds = [reviewSelectedTypeId, reviewClickedEntity?.type].filter(
      (value): value is string => Boolean(value)
    );
    const extras = textTypes.filter(type => currentTypeIds.includes(type.id) && !currentIds.has(type.id));
    return preferred.length ? [...preferred, ...extras] : textTypes;
  }, [cfg.selectedEntityTypeIds, reviewClickedEntity?.type, reviewSelectedTypeId, textTypes]);

  const reviewImagePreviewSrc = useMemo(
    () => (reviewImagePreview ? `data:image/png;base64,${reviewImagePreview}` : ''),
    [reviewImagePreview]
  );

  const selectedReviewEntityCount = useMemo(
    () => reviewEntities.filter(entity => entity.selected !== false).length,
    [reviewEntities]
  );

  const selectedReviewBoxCount = useMemo(
    () => reviewBoxes.filter(box => box.selected !== false).length,
    [reviewBoxes]
  );

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
          const r = await fileApi.upload(file, bg, activeJobId ?? undefined, 'batch');
          const ft = String(r.file_type ?? '').toLowerCase();
          const isImg = ft === 'image' || ft === 'jpg' || ft === 'jpeg' || ft === 'png' || ft === 'pdf_scanned';
          uploaded.push({
            file_id: r.file_id,
            original_filename: r.filename,
            file_size: r.file_size,
            file_type: r.file_type,
            created_at: r.created_at ?? undefined,
            has_output: false,
            reviewConfirmed: false,
            entity_count: 0,
            analyzeStatus: 'pending',
            isImageMode: isImg,
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
        if (activeJobId) {
          try {
            const d = await getJob(activeJobId);
            const m = { ...itemIdByFileIdRef.current };
            for (const it of d.items) {
              m[it.file_id] = it.id;
            }
            itemIdByFileIdRef.current = m;
          } catch {
            /* ignore */
          }
        }
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
  }, [activeJobId]);

  const submitQueueToWorker = async () => {
    if (!activeJobId) {
      setMsg({ text: '请先在「任务与配置」完成步骤 1 并进入上传，以创建或绑定任务工单', tone: 'warn' });
      return;
    }
    setMsg(null);
    try {
      const jobCfg = buildJobConfigForWorker(cfg, mode, furthestStep);
      // 尝试更新配置（非 draft 也允许更新，只有终态才拒绝）
      try {
        await updateJobDraft(activeJobId, { config: jobCfg });
        lastSavedJobConfigJson.current = JSON.stringify(jobCfg);
      } catch {
        /* 终态任务无法更新配置，继续提交 */
      }
      await apiSubmitJob(activeJobId);
      clearLocalWizardMaxStep(activeJobId);
      // 提交后将所有未完成项标记为 pending，触发轮询
      setRows(prev => prev.map(r =>
        !RECOGNITION_DONE_STATUSES.has(r.analyzeStatus) && r.analyzeStatus !== 'failed'
          ? { ...r, analyzeStatus: 'pending' as const }
          : r
      ));
      setMsg({ text: '已提交后台队列，正在轮询处理进度…', tone: 'ok' });
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : '提交队列失败', tone: 'err' });
    }
  };

  /* ── 后台队列轮询：step=3 时有未完成项则每 3s 拉取 job 状态更新 rows ── */
  const hasItemsInProgress = useMemo(
    () => rows.some(r => r.analyzeStatus === 'pending' || r.analyzeStatus === 'parsing' || r.analyzeStatus === 'analyzing'),
    [rows]
  );

  useEffect(() => {
    if (step !== 3 || !activeJobId || !hasItemsInProgress || analyzeRunning) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const detail = await getJob(activeJobId);
        if (cancelled) return;
        const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
        let doneCount = 0;
        setRows(prev =>
          prev.map(r => {
            const item = itemMap.get(r.file_id);
            if (!item) return r;
            const newStatus = mapBackendStatus(item.status);
            if (RECOGNITION_DONE_STATUSES.has(newStatus) || newStatus === 'failed') doneCount++;
            const itemFt = String(item.file_type ?? '').toLowerCase();
            const isImg = r.isImageMode ?? (itemFt === 'image' || itemFt === 'jpg' || itemFt === 'jpeg' || itemFt === 'png' || itemFt === 'pdf_scanned');
            return {
              ...r,
              analyzeStatus: newStatus,
              reviewConfirmed: deriveReviewConfirmed(item),
              has_output: Boolean(item.has_output),
              isImageMode: isImg,
              analyzeError: item.status === 'failed' || item.status === 'cancelled'
                ? (item.error_message || '处理失败')
                : undefined,
              entity_count: typeof item.entity_count === 'number' ? item.entity_count : r.entity_count,
            };
          })
        );
        setAnalyzeDoneCount(doneCount);
      } catch {
        /* 网络抖动不中断轮询 */
      }
    };
    const timer = setInterval(poll, 3000);
    poll(); // 立即执行一次
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [step, activeJobId, hasItemsInProgress, analyzeRunning]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled: loading,
    multiple: true,
  });

  const selectedIds = rows.filter(r => selected.has(r.file_id)).map(r => r.file_id);

  const anyAnalyzeDone = doneRows.length > 0;

  const canGoStep = (target: Step): boolean => {
    if (target <= 1) return true;
    // 所有文件识别完成才可进入审阅
    const allAnalyzeDone = rows.length > 0 && rows.every(r => RECOGNITION_DONE_STATUSES.has(r.analyzeStatus));
    if (target === 4) return allAnalyzeDone;
    if (target < step) return true;
    if (!isStep1Complete && target >= 2) return false;
    if (target === 2) return furthestStep >= 2;
    if (target === 3) return furthestStep >= 2 && rows.length > 0;
    // 所有文件确认脱敏后才能进入导出
    if (target === 5) {
      if (jobSkipItemReview) return furthestStep >= 5 && rows.every(r => r.has_output);
      return furthestStep >= 5 && allReviewConfirmed;
    }
    return false;
  };

  /** 仅底部「下一步：上传」调用：首次从配置进入上传，不经过步骤条 */
  const advanceToUploadStep = async () => {
    if (!isStep1Complete) {
      setMsg({
        text: !configLoaded
          ? '请等待识别配置加载完成。'
          : !confirmStep1
            ? '请在步骤 1 底部勾选「已确认上述配置」后再进入上传。'
            : '请先完成步骤 1：至少勾选一个文本实体类型或一类图像识别项。',
        tone: 'warn',
      });
      return;
    }
    try {
      const nextFurthest = Math.max(furthestStep, 2) as Step;
      const payload = buildJobConfigForWorker(cfg, mode, nextFurthest);
      let jid = activeJobId;
      if (!jid) {
        const j = await createJob({
          job_type: 'smart_batch',
          title: `批量 ${new Date().toLocaleString()}`,
          config: payload,
          priority: jobPriority,
        });
        jid = j.id;
        writeLocalWizardMaxStep(jid, nextFurthest);
        setActiveJobId(jid);
      } else {
        writeLocalWizardMaxStep(jid, nextFurthest);
        await updateJobDraft(jid, { config: payload });
      }
      lastSavedJobConfigJson.current = JSON.stringify(payload);
      internalStepNavRef.current = true;
      setStep(2);
      setFurthestStep(prev => Math.max(prev, 2) as Step);
      setMsg(null);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : '创建或更新任务失败', tone: 'err' });
    }
  };

  /** 步骤 ④ 底部「前往导出」：首次进入导出步，步骤条上的「5」在此之前不可点（不弹离开确认） */
  const advanceToExportStep = async () => {
    if (!rows.length) {
      setMsg({ text: '没有可导出的文件', tone: 'warn' });
      return;
    }
    await flushCurrentReviewDraft();
    // 先从后端刷新状态（可能有跨页面操作如 JobDetail 快速确认），再判断是否放行
    if (activeJobId) {
      try {
        const detail = await getJob(activeJobId);
        const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
        const backendFileIds = new Set(detail.items.map(it => it.file_id));
        setRows(prev => prev.filter(r => backendFileIds.has(r.file_id)).map(r => {
          const item = itemMap.get(r.file_id);
          if (!item) return r;
          return {
            ...r,
            has_output: Boolean(item.has_output),
            analyzeStatus: mapBackendStatus(item.status),
            reviewConfirmed: deriveReviewConfirmed(item),
          };
        }));
        // 用后端数据重新检查 allReviewConfirmed
        const freshConfirmed = detail.items.every(it => deriveReviewConfirmed(it));
        if (!freshConfirmed) {
          const pending = detail.items.filter(it => !deriveReviewConfirmed(it)).length;
          setMsg({
            text: `还有 ${pending} 份文件未确认审核，全部确认后才能进入导出。`,
            tone: 'warn',
          });
          return;
        }
        // 后端确认通过 → 直接进入步骤5，避免下面用过时客户端状态再判断
        internalStepNavRef.current = true;
        setStep(5);
        setFurthestStep(prev => Math.max(prev, 5) as Step);
        setMsg(null);
        return;
      } catch { /* 刷新失败时 fallback 到客户端状态判断 */ }
    }
    if (!allReviewConfirmed) {
      setMsg({
        text: `还有 ${pendingReviewCount} 份文件未确认审核，全部确认后才能进入导出。`,
        tone: 'warn',
      });
      return;
    }
    internalStepNavRef.current = true;
    setStep(5);
    setFurthestStep(prev => Math.max(prev, 5) as Step);
    setMsg(null);
  };

  const flushJobDraftFromStep1 = useCallback(async () => {
    if (!activeJobId) return;
    const payload = buildJobConfigForWorker(cfg, mode, furthestStep);
    const j = JSON.stringify(payload);
    if (j === lastSavedJobConfigJson.current) return;
    try {
      await updateJobDraft(activeJobId, { config: payload });
      lastSavedJobConfigJson.current = j;
    } catch {
      /* 与防抖 PUT 一致：失败时下一步仍会重试 */
    }
  }, [activeJobId, cfg, mode, furthestStep]);

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
            : '请先完成步骤 1：至少勾选一个文本实体类型或一类图像识别项。',
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
    if (step === 1 && s >= 2 && activeJobId) {
      void flushJobDraftFromStep1();
    }
    internalStepNavRef.current = true;
    setStep(s);
    setFurthestStep(prev => Math.max(prev, s) as Step);
    setMsg(null);
    if (s === 4) {
      const firstPending = doneRows.findIndex(r => !r.has_output);
      setReviewIndex(firstPending >= 0 ? firstPending : 0);
    }
    if (s === 5 && activeJobId) {
      void (async () => {
        try {
          const detail = await getJob(activeJobId);
          const itemMap = new Map(detail.items.map(it => [it.file_id, it]));
          setRows(prev => prev.map(r => {
            const item = itemMap.get(r.file_id);
            if (!item) return r;
            return {
              ...r,
              has_output: Boolean(item.has_output),
              analyzeStatus: mapBackendStatus(item.status),
              reviewConfirmed: deriveReviewConfirmed(item),
            };
          }));
        } catch { /* ignore refresh failure */ }
      })();
    }
  };

  /** 从第 4 步去其它步骤（除「前往导出」进入步骤 5）时先确认 */
  const goStep = (s: Step) => {
    if (step === 4 && s !== 5) {
      void (async () => {
        const ok = await flushCurrentReviewDraft();
        if (ok) applyStep(s);
      })();
      return;
    }
    applyStep(s);
  };

  const showLeaveConfirmModal =
    leaveConfirmOpen || navigationBlocker.state === 'blocked';

  const handleConfirmLeaveReview = async () => {
    const ok = await flushCurrentReviewDraft();
    if (!ok) return;
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

  useEffect(() => {
    if (navigationBlocker.state !== 'blocked') return;
    void (async () => {
      const ok = await flushCurrentReviewDraft();
      if (ok && navigationBlocker.state === 'blocked') {
        navigationBlocker.proceed();
      }
    })();
  }, [flushCurrentReviewDraft, navigationBlocker]);

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (step !== 4 || !reviewDraftDirtyRef.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [step]);

  useEffect(() => {
    if (step !== 4) return;
    const onPageHide = () => {
      void flushCurrentReviewDraft();
    };
    window.addEventListener('pagehide', onPageHide);
    return () => window.removeEventListener('pagehide', onPageHide);
  }, [flushCurrentReviewDraft, step]);

  const requeueFailedItems = async () => {
    if (!failedRows.length) return;
    // 后台队列模式：走 API
    if (activeJobId && cfg.executionDefault !== 'local') {
      setMsg(null);
      try {
        await requeueFailed(activeJobId);
        setRows(prev => prev.map(r => r.analyzeStatus === 'failed'
          ? { ...r, analyzeStatus: 'pending', analyzeError: undefined }
          : r
        ));
        setMsg({ text: `已重新排队 ${failedRows.length} 个失败项，等待后台处理`, tone: 'ok' });
      } catch (e) {
        setMsg({ text: e instanceof Error ? e.message : '重新排队失败，尝试本地重跑', tone: 'warn' });
        // fallback 到本地重跑
        await retryFailedLocally();
      }
      return;
    }
    // 本地模式：直接重新识别失败的文件
    await retryFailedLocally();
  };

  const retryFailedLocally = async () => {
    const failedIndices = rows.map((r, i) => r.analyzeStatus === 'failed' ? i : -1).filter(i => i >= 0);
    if (!failedIndices.length) return;
    setAnalyzeRunning(true);
    setMsg(null);
    const entityIds = cfg.selectedEntityTypeIds;
    const bodyNer = { entity_type_ids: entityIds };
    let successCount = 0;

    for (const i of failedIndices) {
      const row = rows[i];
      setRows(prev =>
        prev.map((r, j) => (j === i ? { ...r, analyzeStatus: 'parsing', analyzeError: undefined } : r))
      );
      try {
        const parseRes = await batchParse(row.file_id);
        const isImage = parseRes.file_type === 'image' || parseRes.is_scanned;
        setRows(prev =>
          prev.map((r, j) => (j === i ? { ...r, isImageMode: isImage, analyzeStatus: 'analyzing' } : r))
        );
        if (isImage) {
          await batchVision(row.file_id, 1, cfg.ocrHasTypes, cfg.hasImageTypes);
          const info = await batchGetFileRaw(row.file_id);
          const boxCount = flattenBoundingBoxesFromStore(info.bounding_boxes).length;
          setRows(prev =>
            prev.map((r, j) => (j === i ? { ...r, analyzeStatus: 'awaiting_review', entity_count: boxCount } : r))
          );
        } else {
          const ner = await batchHybridNer(row.file_id, bodyNer);
          setRows(prev =>
            prev.map((r, j) => (j === i ? { ...r, analyzeStatus: 'awaiting_review', entity_count: ner.entity_count } : r))
          );
        }
        successCount += 1;
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        setRows(prev =>
          prev.map((r, j) => (j === i ? { ...r, analyzeStatus: 'failed', analyzeError: err } : r))
        );
      }
    }
    setAnalyzeRunning(false);
    setMsg({
      text: successCount === failedIndices.length
        ? `${successCount} 个失败项全部重跑成功`
        : `重跑完成：${successCount} 成功，${failedIndices.length - successCount} 仍失败`,
      tone: successCount === failedIndices.length ? 'ok' : 'warn',
    });
  };

  const runBatchAnalyze = async (opts?: { advanceToReview?: boolean }) => {
    if (!rows.length) return;
    setAnalyzeRunning(true);
    setAnalyzeDoneCount(0);
    setMsg(null);
    let successCount = 0;
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
                    analyzeStatus: 'awaiting_review',
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
                    analyzeStatus: 'awaiting_review',
                    entity_count: ner.entity_count,
                  }
                : r
            )
          );
        }
        successCount += 1;
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
    if (successCount > 0) {
      setFurthestStep(prev => Math.max(prev, 4) as Step);
      if (opts?.advanceToReview) {
        internalStepNavRef.current = true;
        setStep(4);
        const firstPending = doneRows.findIndex(r => !r.has_output);
        setReviewIndex(firstPending >= 0 ? firstPending : 0);
      }
    }
    setMsg({
      text:
        successCount > 0
          ? opts?.advanceToReview
            ? '识别完成，已进入审阅。'
            : '识别已完成。'
          : '没有文件识别成功，请检查文件或配置后重试。',
      tone: successCount > 0 ? 'ok' : 'warn',
    });
  };

  const confirmCurrentReview = async () => {
    if (!reviewFile) return;
    setReviewExecuteLoading(true);
    setMsg(null);
    const currentFileId = reviewFile.file_id;
    const currentIsImage = reviewFile.isImageMode;
    try {
      const jid = activeJobId;
      const linkedItemId = itemIdByFileIdRef.current[currentFileId];
      if (!jid || !linkedItemId) {
        throw new Error('当前文件未绑定任务项，无法提交审核结果');
      }
      const entitiesPayload = reviewEntities.map(e => ({
        id: e.id,
        text: e.text,
        type: e.type,
        start: e.start,
        end: e.end,
        page: e.page ?? 1,
        confidence: e.confidence ?? 1,
        selected: e.selected,
        source: e.source,
        coref_id: e.coref_id,
        replacement: e.replacement,
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
        confidence: b.confidence,
      }));

      // ── 乐观更新：立即标记已确认 + 计数器即时 +1 ──
      setRows(prev =>
        prev.map(r =>
          r.file_id === currentFileId
            ? { ...r, reviewConfirmed: true, has_output: true, analyzeStatus: 'completed' as const }
            : r
        )
      );
      // 乐观切换到下一份（不等 API 返回）
      const isLastFile = reviewIndex >= doneRows.length - 1;
      if (!isLastFile) {
        setReviewIndex(reviewIndex + 1);
        setMsg({ text: currentIsImage ? '脱敏中，已切换到下一张…' : '脱敏中，已切换到下一份…', tone: 'ok' });
      } else {
        setMsg({ text: '正在处理最后一份…', tone: 'ok' });
      }

      // ── 后台执行 flush + commit ──
      const ok = await flushCurrentReviewDraft();
      if (!ok) {
        throw new Error(reviewDraftError || '自动保存失败，请稍后重试');
      }
      const commitResult = await commitItemReview(jid, linkedItemId, {
        entities: entitiesPayload as Array<Record<string, unknown>>,
        bounding_boxes: boxesPayload as Array<Record<string, unknown>>,
      });

      // 用后端真实状态修正乐观更新
      const committedStatus = mapBackendStatus(commitResult.status ?? 'completed');
      setRows(prev =>
        prev.map(r =>
            r.file_id === currentFileId
              ? {
                  ...r,
                  has_output: Boolean(commitResult.has_output ?? true),
                  reviewConfirmed: deriveReviewConfirmed(commitResult),
                  analyzeStatus: committedStatus,
                  entity_count:
                    typeof commitResult.entity_count === 'number'
                      ? commitResult.entity_count
                      : currentIsImage
                      ? boxesPayload.length
                      : entitiesPayload.length,
              }
            : r
        )
      );
      reviewLastSavedJsonRef.current = JSON.stringify({ entities: entitiesPayload, bounding_boxes: boxesPayload });
      reviewDraftDirtyRef.current = false;

      if (isLastFile) {
        setMsg({ text: '本批已全部审阅完成，可点击下一步进入导出。', tone: 'ok' });
        setFurthestStep(prev => Math.max(prev, 5) as Step);
      }
    } catch (e) {
      // 回滚乐观更新
      setRows(prev =>
        prev.map(r =>
          r.file_id === currentFileId
            ? { ...r, reviewConfirmed: false, has_output: false, analyzeStatus: 'awaiting_review' as const }
            : r
        )
      );
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
      // 导出完成后清理 localStorage 中的 furthestStep 持久化
      if (redacted && activeJobId) clearLocalWizardMaxStep(activeJobId);
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
    return <Navigate to="/batch" replace />;
  }

  return (
    <div className="batch-root h-full min-h-0 min-w-0 flex flex-col bg-[#fafafa] dark:bg-gray-900 overflow-hidden">
      <div
        className={`flex-1 flex flex-col min-h-0 min-w-0 w-full max-w-[min(100%,1920px)] mx-auto ${
          step === 1
            ? 'px-3 py-2 sm:px-4 sm:py-2.5 overflow-hidden'
            : step === 4 && reviewFile?.isImageMode
              ? 'px-2 py-1.5 sm:px-3 sm:py-2 flex flex-col min-h-0 overflow-hidden'
              : step === 4
                ? 'px-2 py-2 sm:px-4 sm:py-3 flex flex-col min-h-0 overflow-hidden'
                : 'px-3 py-3 sm:px-5 sm:py-4 overflow-y-auto overscroll-contain'
        }`}
      >
        <p
          className={`mb-1 flex-shrink-0 text-2xs sm:text-caption text-[#737373] leading-tight ${
            step === 4 ? 'hidden' : ''
          }`}
        >
          五步：配置 → 上传 → 批量识别 → 审阅确认 → 导出（与 Playground 无关）
        </p>

        {/* 步骤条 */}
        <div
          className={`batch-stepper flex flex-wrap items-center gap-1.5 flex-shrink-0 ${
            step === 4 ? 'mb-1' : 'mb-1.5'
          }`}
        >
          {STEPS.map((s, i) => {
            const reachable = canGoStep(s.n as Step);
            return (
            <React.Fragment key={s.n}>
              <button
                type="button"
                onClick={() => reachable && goStep(s.n as Step)}
                disabled={!reachable && step !== s.n}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all duration-200 ${
                  step === s.n
                    ? 'bg-[#1d1d1f] text-white shadow-sm'
                    : reachable
                      ? 'bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 cursor-pointer'
                      : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                } batch-step-chip`}
              >
                <span className="tabular-nums">{s.n}</span>
                {s.label}
              </button>
              {i < STEPS.length - 1 && <span className="text-gray-300 hidden sm:inline">→</span>}
            </React.Fragment>
            );
          })}
        </div>

        {msg && <div className={`text-sm rounded-lg px-3 py-2 mb-2 ${msgClass}`}>{msg.text}</div>}

        {/* 1 配置 */}
        {step === 1 && (
          <BatchStep1Config
            mode={mode}
            cfg={cfg}
            setCfg={setCfg}
            configLoaded={configLoaded}
            textTypes={textTypes}
            pipelines={pipelines}
            presets={presets}
            textPresets={textPresets}
            visionPresets={visionPresets}
            onBatchTextPresetChange={onBatchTextPresetChange}
            onBatchVisionPresetChange={onBatchVisionPresetChange}
            confirmStep1={confirmStep1}
            setConfirmStep1={setConfirmStep1}
            isStep1Complete={isStep1Complete}
            jobPriority={jobPriority}
            setJobPriority={setJobPriority}
            advanceToUploadStep={advanceToUploadStep}
            SmartDetailTabs={SmartDetailTabs}
            PresetDetailBlock={PresetDetailBlock}
          />
        )}

        {/* 2 上传 */}
        {step === 2 && (
          <BatchStep2Upload
            mode={mode}
            activeJobId={activeJobId}
            rows={rows}
            loading={loading}
            isDragActive={isDragActive}
            getRootProps={getRootProps}
            getInputProps={getInputProps}
            goStep={goStep}
          />
        )}

        {/* 3 批量识别 */}
        {step === 3 && (
          <BatchStep3Review
            rows={rows}
            analyzeRunning={analyzeRunning}
            analyzeDoneCount={analyzeDoneCount}
            activeJobId={activeJobId}
            failedRows={failedRows}
            canGoStep={canGoStep}
            goStep={goStep}
            submitQueueToWorker={submitQueueToWorker}
            requeueFailedItems={requeueFailedItems}
          />
        )}

        {/* 4 核对 · 图像：三列布局 — 原图标注 | 脱敏预览 | 标签列表 */}
        {step === 4 && reviewFile?.isImageMode && (
          <div className="flex-1 flex flex-col min-h-0 rounded-xl border border-gray-200 shadow-sm bg-white overflow-hidden">
            {/* 只读提示 */}
            {reviewFileReadOnly && (
              <div className="shrink-0 bg-emerald-50 border-b border-emerald-200 px-4 py-2 text-sm text-emerald-800">
                该文件已完成脱敏，仅供查阅。如需重新脱敏请先在任务详情驳回。
              </div>
            )}

            {!doneRows.length ? (
              <p className="p-3 text-sm text-gray-400 shrink-0">暂无已完成识别的文件，请先完成第 3 步批量识别。</p>
            ) : reviewLoading || !reviewFile ? (
              <p className="p-3 text-sm text-gray-400 shrink-0">加载中…</p>
            ) : reviewFile.isImageMode ? (
              <>
                {/* ── 顶部工具栏 ── */}
                <div className="shrink-0 flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-100 bg-[#fafafa]">
                  {/* 文件名 */}
                  <span
                    className="text-xs font-semibold text-gray-900 truncate max-w-[20rem]"
                    title={reviewFile.original_filename}
                  >
                    {reviewFile.original_filename}
                  </span>

                  {/* 翻页 */}
                  {doneRows.length > 1 && (
                    <div className="flex items-center gap-1 border-l border-gray-200 pl-2">
                      <button type="button" disabled={reviewIndex <= 0}
                        onClick={() => void navigateReviewIndex(reviewIndex - 1)}
                        className="px-2 py-0.5 text-xs rounded border border-gray-200 bg-white disabled:opacity-40">
                        上一张
                      </button>
                      <span className="text-xs text-gray-600 tabular-nums">{reviewIndex + 1}/{doneRows.length}</span>
                      <button type="button"
                        disabled={reviewIndex >= doneRows.length - 1 || !reviewFile?.reviewConfirmed}
                        onClick={() => void navigateReviewIndex(reviewIndex + 1)}
                        title={!reviewFile?.reviewConfirmed ? '请先确认当前文件脱敏' : ''}
                        className="px-2 py-0.5 text-xs rounded border border-gray-200 bg-white disabled:opacity-40">
                        下一张
                      </button>
                    </div>
                  )}

                  {/* Undo / Redo */}
                  <div className="flex items-center gap-1 border-l border-gray-200 pl-2">
                    <button type="button" onClick={undoReviewImage} disabled={!reviewImageUndoStack.length}
                      className="px-2 py-0.5 text-xs rounded border border-gray-200 bg-white disabled:opacity-40">Undo</button>
                    <button type="button" onClick={redoReviewImage} disabled={!reviewImageRedoStack.length}
                      className="px-2 py-0.5 text-xs rounded border border-gray-200 bg-white disabled:opacity-40">Redo</button>
                  </div>

                  {/* 草稿状态 */}
                  {reviewDraftSaving && <span className="text-xs text-gray-400">保存草稿…</span>}
                  {!reviewDraftSaving && reviewDraftError && <span className="text-xs text-red-500 truncate max-w-[10rem]">{reviewDraftError}</span>}

                  {/* 右侧操作 */}
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-xs text-gray-500 tabular-nums">已确认 {reviewedOutputCount}/{rows.length}</span>
                    <button type="button" onClick={confirmCurrentReview}
                      disabled={reviewLoading || reviewExecuteLoading || reviewFileReadOnly}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-[#1d1d1f] text-white hover:bg-[#2d2d2f] disabled:opacity-50 transition-all">
                      {reviewFileReadOnly ? '已完成' : reviewExecuteLoading ? '提交中…' : '确认脱敏'}
                    </button>
                    <button type="button" onClick={advanceToExportStep}
                      disabled={!allReviewConfirmed || reviewExecuteLoading}
                      className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                        allReviewConfirmed && !reviewExecuteLoading
                          ? 'bg-green-600 text-white hover:bg-green-700'
                          : 'border border-gray-200 text-gray-400 disabled:opacity-40'
                      }`}>
                      {allReviewConfirmed ? '✓ 进入导出' : '进入导出'}
                    </button>
                  </div>
                </div>

                {/* ── 三列主体（等宽） ── */}
                <div className="flex-1 min-h-0 grid grid-cols-3 overflow-hidden">
                  {/* 列 1：原图 + 标注框 */}
                  <div className="min-w-0 min-h-0 border-r border-gray-100 relative">
                    <div className="absolute inset-0">
                      <ImageBBoxEditor
                        imageSrc={reviewOrigImageBlobUrl}
                        boxes={reviewBoxes}
                        onBoxesChange={setReviewBoxes}
                        onBoxesCommit={handleReviewBoxesCommit}
                        getTypeConfig={getVisionTypeMeta}
                        availableTypes={pipelines.flatMap(p => p.types.filter(t => t.enabled))}
                        defaultType="CUSTOM"
                        viewportTopSlot={
                          <span className="text-2xs font-medium text-white bg-black/50 px-2 py-0.5 rounded backdrop-blur-sm">
                            原图 + 标注
                          </span>
                        }
                      />
                    </div>
                  </div>

                  {/* 列 2：脱敏后预览 */}
                  <div className="min-w-0 min-h-0 border-r border-gray-100 flex flex-col bg-[#fafafa]">
                    <div className="shrink-0 px-3 py-2 border-b border-gray-100 bg-white">
                      <p className="text-xs font-semibold text-gray-800">脱敏预览</p>
                      <p className="text-2xs text-gray-400">
                        {reviewImagePreviewLoading ? '生成中…' : `${selectedReviewBoxCount}/${reviewBoxes.length} 区域已选`}
                      </p>
                    </div>
                    <div className="flex-1 overflow-auto p-2 flex items-start justify-center">
                      {reviewImagePreviewSrc ? (
                        <img src={reviewImagePreviewSrc} alt="脱敏预览"
                          className="max-w-full h-auto rounded-lg border border-gray-200 bg-white shadow-sm" />
                      ) : (
                        <div className="w-full h-full min-h-[200px] flex items-center justify-center text-sm text-gray-400 rounded-lg border border-dashed border-gray-200 bg-white">
                          勾选区域后生成预览
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 列 3：检测标签列表 */}
                  <div className="min-w-0 min-h-0 flex flex-col bg-white">
                    <div className="shrink-0 px-3 py-2 border-b border-gray-100 flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-800">检测区域</span>
                      <span className="text-2xs text-gray-400 tabular-nums">{selectedReviewBoxCount}/{reviewBoxes.length}</span>
                    </div>
                    <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                      {reviewBoxes.map(box => {
                        const meta = getVisionTypeMeta(box.type);
                        return (
                          <button key={box.id} type="button"
                            onClick={() => toggleReviewBoxSelected(box.id)}
                            className="w-full text-left rounded-lg border px-2.5 py-1.5 transition hover:border-gray-300"
                            style={{
                              borderColor: box.selected !== false ? meta.color : '#e5e7eb',
                              backgroundColor: box.selected === false ? '#fafafa' : `${String(meta.color)}0d`,
                            }}>
                            <div className="flex items-center gap-2">
                              <input type="checkbox" checked={box.selected !== false}
                                onChange={() => toggleReviewBoxSelected(box.id)}
                                className={formCheckboxClass('sm')} />
                              <span className="text-xs font-medium truncate" style={{ color: meta.color }}>
                                {meta.name}
                              </span>
                              <span className="text-2xs text-gray-400 ml-auto shrink-0">
                                {Math.round(box.width * 100)}×{Math.round(box.height * 100)}%
                              </span>
                            </div>
                            {box.text && <p className="mt-0.5 text-2xs text-gray-500 truncate pl-6">{box.text}</p>}
                          </button>
                        );
                      })}
                      {reviewBoxes.length === 0 && (
                        <p className="text-xs text-gray-400 text-center py-8">暂无检测区域</p>
                      )}
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
                当前项不是图像模式，请从「图像批量」进入审阅。
              </div>
            )}
          </div>
        )}

        {step === 4 && !reviewFile?.isImageMode && (
          <div className="flex-1 flex flex-col min-h-0 rounded-xl border border-gray-200 shadow-sm bg-white overflow-hidden relative">
            {reviewFileReadOnly && (
              <div className="shrink-0 bg-emerald-50 border-b border-emerald-200 px-4 py-2 text-sm text-emerald-800">
                该文件已完成脱敏，仅供查阅。如需重新脱敏请先在任务详情驳回。
              </div>
            )}
            <div className="shrink-0 px-4 pt-3 pb-2 border-b border-gray-100/80 space-y-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="font-semibold text-gray-900 dark:text-gray-100 text-sm">文本审阅工作台</h3>
                  <p className="text-2xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">
                    划选添加标注、点击实体可改类型或删除；原文与脱敏预览联动；草稿约 900ms 自动保存到任务。
                  </p>
                </div>
                <div className="flex items-center gap-2 text-2xs">
                  {reviewDraftSaving && <span className="text-gray-500">正在保存草稿…</span>}
                  {!reviewDraftSaving && reviewDraftError && <span className="text-red-600">{reviewDraftError}</span>}
                  {!reviewDraftSaving && !reviewDraftError && step === 4 && (
                    <span className="text-emerald-600">草稿已同步</span>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {doneRows.length > 1 && (
                  <>
                    <button
                      type="button"
                      disabled={reviewIndex <= 0}
                      onClick={() => void navigateReviewIndex(reviewIndex - 1)}
                      className="px-2.5 py-1 text-xs border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 disabled:opacity-40"
                    >
                      上一份
                    </button>
                    <span className="text-xs text-gray-600 tabular-nums">
                      {reviewIndex + 1} / {doneRows.length}
                    </span>
                    <button
                      type="button"
                      disabled={reviewIndex >= doneRows.length - 1 || !reviewFile?.reviewConfirmed}
                      onClick={() => void navigateReviewIndex(reviewIndex + 1)}
                      title={!reviewFile?.reviewConfirmed ? '请先确认当前文件脱敏' : ''}
                      className="px-2.5 py-1 text-xs border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 disabled:opacity-40"
                    >
                      下一份
                    </button>
                  </>
                )}
                <button
                  type="button"
                  onClick={undoReviewText}
                  disabled={!reviewTextUndoStack.length}
                  className="px-2.5 py-1 text-xs border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 disabled:opacity-40 ml-auto"
                >
                  Undo
                </button>
                <button
                  type="button"
                  onClick={redoReviewText}
                  disabled={!reviewTextRedoStack.length}
                  className="px-2.5 py-1 text-xs border border-gray-200 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 disabled:opacity-40"
                >
                  Redo
                </button>
              </div>
            </div>

            {!doneRows.length && (
              <p className="p-4 text-sm text-gray-400 shrink-0">暂无已完成识别的文件，请先完成第 3 步批量识别。</p>
            )}

            {!!doneRows.length && reviewFile && (
              <div className="flex-1 min-h-0 grid gap-3 p-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1.1fr)_320px]">
                <div className="min-h-0 rounded-2xl border border-gray-200/80 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-3 sm:px-4 py-2 border-b border-gray-100 flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-gray-700 tracking-tight">原文</span>
                    <span className="text-2xs text-gray-500 dark:text-gray-400 tabular-nums">
                      已选 {selectedReviewEntityCount} / {reviewEntities.length}
                    </span>
                  </div>
                  <div ref={reviewTextScrollRef} className="flex-1 overflow-auto p-3 sm:p-4">
                    <div
                      ref={reviewTextContentRef}
                      className="relative text-sm leading-relaxed text-gray-800 whitespace-pre-wrap font-[system-ui]"
                      onMouseUp={handleReviewTextSelect}
                      onKeyUp={handleReviewTextSelect}
                    >
                      {renderReviewMarkedContent()}
                    </div>
                  </div>
                </div>

                <div className="min-h-0 rounded-2xl border border-gray-200/80 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col overflow-hidden">
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
                            {displayPreviewMap[seg.origKey] ?? seg.origKey}
                          </mark>
                        ) : (
                          <span key={i}>{seg.text}</span>
                        )
                      )}
                    </div>
                  </div>
                </div>

                <div className="min-h-0 rounded-2xl border border-gray-200/80 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col overflow-hidden">
                  <div className="flex-shrink-0 px-3 py-2 border-b border-gray-100 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-gray-700 tracking-tight">实体列表</span>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-2xs text-gray-500 dark:text-gray-400 tabular-nums">{selectedReviewEntityCount}/{reviewEntities.length}</span>
                      <button
                        type="button"
                        onClick={() => applyReviewEntities(prev => prev.map(e => ({ ...e, selected: true })))}
                        className="text-2xs font-medium px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50"
                      >
                        全选
                      </button>
                      <button
                        type="button"
                        onClick={() => applyReviewEntities(prev => prev.map(e => ({ ...e, selected: false })))}
                        className="text-2xs font-medium px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50"
                      >
                        全不选
                      </button>
                    </div>
                  </div>
                  <div className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-2">
                    {reviewEntities.map(e => {
                      const repl =
                        displayPreviewMap[e.text] ??
                        (typeof e.start === 'number' && typeof e.end === 'number' && e.end <= reviewTextContent.length
                          ? displayPreviewMap[reviewTextContent.slice(e.start, e.end)]
                          : undefined);
                      const risk = getEntityRiskConfig(e.type);
                      return (
                        <div
                          key={e.id}
                          className="rounded-xl border border-black/[0.06] dark:border-gray-700 shadow-sm px-3 py-2"
                          style={{ backgroundColor: e.selected === false ? '#f9fafb' : risk.bgColor, borderLeft: `3px solid ${risk.color}` }}
                        >
                          <div className="flex items-start gap-2">
                            <input
                              type="checkbox"
                              checked={e.selected !== false}
                              onChange={() => toggleReviewEntitySelected(e.id)}
                              className={formCheckboxClass('sm')}
                            />
                            <button type="button" className="min-w-0 flex-1 text-left" onClick={() => scrollToBatchMatch(e)}>
                              <span className="text-caption font-medium" style={{ color: risk.textColor }}>
                                {textTypes.find(t => t.id === e.type)?.name ?? getEntityTypeName(e.type)}
                              </span>
                              <span className="block text-xs break-all mt-0.5" style={{ color: risk.textColor }}>
                                {e.text}
                              </span>
                              {repl != null && (
                                <span className="block text-2xs mt-0.5 truncate opacity-90" style={{ color: risk.textColor }}>
                                  {repl}
                                </span>
                              )}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                    {reviewEntities.length === 0 && (
                      <p className="text-xs text-gray-400 text-center py-6 px-2">暂无识别实体</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {reviewSelectedText && reviewSelectionPos && (
              <div
                className="fixed z-50 bg-white border border-gray-200 rounded-xl shadow-2xl p-3 w-[320px]"
                style={{ left: reviewSelectionPos.left, top: reviewSelectionPos.top }}
                onMouseDown={e => e.stopPropagation()}
                onMouseUp={e => e.stopPropagation()}
              >
                <div className="mb-3">
                  <div className="text-caption text-gray-500 mb-1 font-medium">选中片段</div>
                  <div className="text-sm text-gray-900 dark:text-gray-100 bg-gray-50 rounded-lg px-3 py-2 max-w-full break-all border border-gray-100">
                    {reviewSelectedText.text}
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="text-caption text-gray-500 mb-1 font-medium">实体类型</div>
                  <EntityTypeGroupPicker
                    entityTypes={reviewAvailableTextTypes}
                    selectedTypeId={reviewSelectedTypeId}
                    onSelectType={setReviewSelectedTypeId}
                  />
                </div>
                <div className="flex gap-2 pt-3 border-t border-gray-100 mt-3">
                  <button
                    type="button"
                    onClick={() => addManualReviewEntity(reviewSelectedTypeId)}
                    disabled={!reviewSelectedTypeId}
                    className="flex-1 text-sm font-medium bg-black text-white rounded-lg px-3 py-2 disabled:opacity-50"
                  >
                    {reviewSelectedOverlapIds.length > 0 ? '替换为所选类型' : '添加标注'}
                  </button>
                  {reviewSelectedOverlapIds.length > 0 && (
                    <button
                      type="button"
                      onClick={removeSelectedReviewEntities}
                      className="text-sm font-medium text-red-700 border border-red-200 rounded-lg px-3 py-2 hover:bg-red-50"
                    >
                      移除重叠
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      reviewSelectionRangeRef.current = null;
                      setReviewSelectedText(null);
                      setReviewSelectionPos(null);
                      setReviewSelectedOverlapIds([]);
                    }}
                    className="text-sm text-gray-500 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50"
                  >
                    关闭
                  </button>
                </div>
              </div>
            )}

            {reviewClickedEntity && reviewEntityPopupPos && (
              <div
                className="fixed z-50 bg-white border border-gray-200 rounded-xl shadow-2xl p-3 w-[260px]"
                style={{ left: reviewEntityPopupPos.left, top: reviewEntityPopupPos.top }}
                onMouseDown={e => e.stopPropagation()}
                onMouseUp={e => e.stopPropagation()}
              >
                <div className="mb-3">
                  <div className="text-caption text-gray-500 mb-1 font-medium">实体文本</div>
                  <div className="text-sm font-medium px-2 py-1.5 rounded-lg break-all bg-gray-50 text-gray-900 border border-gray-100">
                    {reviewClickedEntity.text}
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="text-caption text-gray-500 mb-1 font-medium">实体类型</div>
                  <EntityTypeGroupPicker
                    entityTypes={reviewAvailableTextTypes}
                    selectedTypeId={reviewSelectedTypeId}
                    onSelectType={id => {
                      setReviewSelectedTypeId(id);
                      updateClickedReviewEntityType(id);
                    }}
                  />
                </div>
                <div className="space-y-2 pt-3 border-t border-gray-100 mt-3">
                  <button
                    type="button"
                    onClick={() => toggleReviewEntitySelected(reviewClickedEntity.id)}
                    className="w-full text-sm font-medium text-gray-800 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50"
                  >
                    {reviewClickedEntity.selected === false ? '参与脱敏' : '不参与脱敏'}
                  </button>
                  <button
                    type="button"
                    onClick={removeClickedReviewEntity}
                    className="w-full text-sm font-medium text-red-700 border border-red-200 rounded-lg px-3 py-2 hover:bg-red-50"
                  >
                    删除实体
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setReviewClickedEntity(null);
                      setReviewEntityPopupPos(null);
                    }}
                    className="w-full text-sm text-gray-500 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50"
                  >
                    关闭
                  </button>
                </div>
              </div>
            )}

{!!doneRows.length && reviewFile && (
              <div className="shrink-0 px-4 pb-4 flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs text-gray-500 dark:text-gray-400 tabular-nums">
                  已确认 {reviewedOutputCount} / {rows.length}
                  {!allReviewConfirmed && <span className="ml-2 text-amber-600">全部确认后才能进入导出</span>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={confirmCurrentReview}
                    disabled={reviewLoading || reviewExecuteLoading || reviewFileReadOnly}
                    className="min-w-[148px] px-4 py-2 text-sm font-semibold rounded-xl bg-[#1d1d1f] text-white shadow-sm hover:bg-[#2d2d2f] transition-all duration-200 disabled:opacity-50 disabled:hover:bg-[#1d1d1f]"
                  >
                    {reviewFileReadOnly ? '已完成脱敏' : reviewExecuteLoading ? '提交中…' : '确认审核并脱敏'}
                  </button>
                  <button
                    type="button"
                    onClick={advanceToExportStep}
                    disabled={!allReviewConfirmed || reviewExecuteLoading}
                    className={`min-w-[148px] px-4 py-2 text-sm font-semibold rounded-xl shadow-sm transition-all duration-200 ${
                      allReviewConfirmed && !reviewExecuteLoading
                        ? 'bg-[#1d1d1f] text-white hover:bg-[#2d2d2f] border-transparent ring-2 ring-[#1d1d1f]/20'
                        : 'border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-800 hover:bg-gray-50 disabled:opacity-40 disabled:hover:bg-white'
                    }`}
                  >
                    {allReviewConfirmed ? '✓ 进入导出' : '下一步：进入导出'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {step === 5 && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm space-y-4">
            <h3 className="font-semibold text-gray-900 dark:text-gray-100">⑤ 导出</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">勾选文件后打包下载；脱敏 ZIP 仅包含已在第 4 步「审阅确认」中完成脱敏的文件。</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => goStep(4)} className="px-4 py-2 text-sm border rounded-lg">
                返回审阅
              </button>
              <button
                type="button"
                onClick={() => downloadZip(false)}
                disabled={zipLoading || !selectedIds.length}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-[#1d1d1f] text-white disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                {zipLoading && (
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                )}
                {zipLoading ? '正在打包下载...' : '下载原始 ZIP'}
              </button>
              <button
                type="button"
                onClick={() => downloadZip(true)}
                disabled={zipLoading || !selectedIds.length}
                className="px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 disabled:opacity-40 inline-flex items-center gap-1.5"
              >
                {zipLoading && (
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                )}
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
                  {(() => { const rs = resolveRedactionState(r.has_output, r.analyzeStatus); return (
                  <span className={`text-xs px-2 py-0.5 rounded-full ${REDACTION_STATE_CLASS[rs]}`}>
                    {REDACTION_STATE_LABEL[rs]}
                  </span>
                  ); })()}
                </div>
              ))}
            </div>
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
              className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-md w-full p-5 border border-gray-200"
              onClick={e => e.stopPropagation()}
            >
              <h2 id="batch-leave-review-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
                离开审阅？
              </h2>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                当前步骤的审阅尚未保存到文件（未点「确认并脱敏」前，修改仅在前端有效）。离开本页或切换到其它步骤后将丢失这些修改。
              </p>
              <div className="mt-5 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={handleCancelLeaveReview}
                  className="px-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50"
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
