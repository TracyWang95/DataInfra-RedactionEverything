import React from 'react';
import { Link } from 'react-router-dom';
import { formCheckboxClass } from '../../ui/selectionClasses';
import type {
  BatchWizardPersistedConfig,
  BatchWizardMode,
  PipelineCfg,
  TextEntityType,
  RecognitionPreset,
} from './batchTypes';

export interface BatchStep1ConfigProps {
  mode: BatchWizardMode;
  cfg: BatchWizardPersistedConfig;
  setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  configLoaded: boolean;
  textTypes: TextEntityType[];
  pipelines: PipelineCfg[];
  presets: RecognitionPreset[];
  textPresets: RecognitionPreset[];
  visionPresets: RecognitionPreset[];
  onBatchTextPresetChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  onBatchVisionPresetChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  confirmStep1: boolean;
  setConfirmStep1: (v: boolean) => void;
  isStep1Complete: boolean;
  jobPriority: number;
  setJobPriority: (v: number) => void;
  advanceToUploadStep: () => void;
  /** Smart mode detail tabs component to render */
  SmartDetailTabs: React.ComponentType<{
    cfg: BatchWizardPersistedConfig;
    textTypes: TextEntityType[];
    pipelines: PipelineCfg[];
    presets: RecognitionPreset[];
    setCfg: React.Dispatch<React.SetStateAction<BatchWizardPersistedConfig>>;
  }>;
  /** Legacy PresetDetailBlock for non-smart modes */
  PresetDetailBlock: React.ComponentType<{
    cfg: BatchWizardPersistedConfig;
    textTypes: TextEntityType[];
    pipelines: PipelineCfg[];
    allPresets: RecognitionPreset[];
    scope: 'text' | 'image';
    onReplacementModeChange: (mode: BatchWizardPersistedConfig['replacementMode']) => void;
    onVisionImagePatch: (patch: Partial<Pick<BatchWizardPersistedConfig, 'imageRedactionMethod' | 'imageRedactionStrength' | 'imageFillColor'>>) => void;
  }>;
}

export const BatchStep1Config: React.FC<BatchStep1ConfigProps> = ({
  mode,
  cfg,
  setCfg,
  configLoaded,
  textTypes,
  pipelines,
  presets,
  textPresets,
  visionPresets,
  onBatchTextPresetChange,
  onBatchVisionPresetChange,
  confirmStep1,
  setConfirmStep1,
  isStep1Complete,
  jobPriority,
  setJobPriority,
  advanceToUploadStep,
  SmartDetailTabs,
  PresetDetailBlock,
}) => {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm flex flex-col flex-1 min-h-0 overflow-hidden p-2 sm:p-3 space-y-2">
      <h3 className="font-semibold text-gray-900 shrink-0 text-sm leading-tight">
        ① 任务与配置
      </h3>
      <p className="text-2xs text-gray-500 leading-snug">
        本步绑定当前批量任务的识别项与脱敏选项。若已从 Hub/任务中心带入工单，修改会<strong className="text-gray-700">自动同步到任务草稿</strong>
        （约 1 秒内防抖保存）；未建单时，点「下一步：上传」会创建工单并写入配置。
      </p>
      <div className="rounded-lg border border-gray-100 bg-[#f8fafc] px-2.5 py-2 space-y-1.5 shrink-0">
        <p className="text-2xs font-medium text-gray-700">默认处理路径</p>
        <div className="flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
          <label className="flex items-center gap-2 cursor-pointer text-2xs text-gray-700">
            <input
              type="radio"
              name="batch-exec-path"
              className="h-3.5 w-3.5 shrink-0 accent-[#1d1d1f]"
              checked={(cfg.executionDefault ?? 'queue') === 'queue'}
              onChange={() => setCfg(c => ({ ...c, executionDefault: 'queue' }))}
            />
            <span>
              <span className="font-medium text-gray-800">后台任务队列</span>（推荐：可关窗由 Worker 继续跑）
            </span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer text-2xs text-gray-700">
            <input
              type="radio"
              name="batch-exec-path"
              className="h-3.5 w-3.5 shrink-0 accent-[#1d1d1f]"
              checked={cfg.executionDefault === 'local'}
              onChange={() => setCfg(c => ({ ...c, executionDefault: 'local' }))}
            />
            <span>
              <span className="font-medium text-gray-800">仅本页完成</span>（浏览器内识别→核对→导出，少依赖队列）
            </span>
          </label>
        </div>
      </div>
      <p className="text-2xs text-gray-400 leading-snug">
        「处理路径」会写入任务草稿字段 <code className="text-[0.65rem]">preferred_execution</code>
        ，便于后续与 Worker 对齐；当前以本页说明为准。
      </p>
      <p className="text-2xs text-gray-500 leading-snug">
        进度与逐份确认见{' '}
        <Link to="/jobs" className="text-[#007AFF] font-medium hover:underline">
          任务中心
        </Link>
        ；处理历史见「处理历史」。
      </p>
      {!configLoaded ? (
        <p className="text-sm text-gray-400">加载类型配置中…</p>
      ) : (
        <>
          {/* ====== Smart 模式：左右双栏布局 ====== */}
          {mode === 'smart' ? (
            <div className="flex gap-3 flex-1 min-h-0 overflow-hidden">
              {/* 左侧：配置选择 */}
              <div className="w-[280px] shrink-0 flex flex-col gap-3 overflow-y-auto">
                {/* 文本配置卡 */}
                <div className="rounded-xl border border-gray-200 bg-white p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                    <label className="text-xs font-semibold text-[#1d1d1f]">文本脱敏</label>
                  </div>
                  <p className="text-2xs text-gray-500">Word / PDF 文字实体识别</p>
                  <select
                    className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-[#fafafa] dark:bg-gray-900 w-full"
                    value={cfg.presetTextId ?? ''}
                    onChange={onBatchTextPresetChange}
                  >
                    <option value="">默认（全选）</option>
                    {textPresets.map(p => (
                      <option key={p.id} value={p.id}>{p.name}{p.kind === 'full' ? '（组合）' : ''}</option>
                    ))}
                  </select>
                </div>
                {/* 图像配置卡 */}
                <div className="rounded-xl border border-gray-200 bg-white p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-violet-500 shrink-0" />
                    <label className="text-xs font-semibold text-[#1d1d1f]">图像脱敏</label>
                  </div>
                  <p className="text-2xs text-gray-500">图片 / 扫描件区域检测</p>
                  <select
                    className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-[#fafafa] dark:bg-gray-900 w-full"
                    value={cfg.presetVisionId ?? ''}
                    onChange={onBatchVisionPresetChange}
                  >
                    <option value="">默认（全选）</option>
                    {visionPresets.map(p => (
                      <option key={p.id} value={p.id}>{p.name}{p.kind === 'full' ? '（组合）' : ''}</option>
                    ))}
                  </select>
                </div>
                {/* 优先级 */}
                <div className="flex items-center gap-2 px-1">
                  <span className="text-2xs text-gray-500">优先级</span>
                  <select
                    value={jobPriority}
                    onChange={e => setJobPriority(Number(e.target.value))}
                    className="text-2xs border border-gray-200 rounded-lg px-2 py-1 bg-white"
                  >
                    <option value={0}>普通</option>
                    <option value={5}>高</option>
                    <option value={10}>紧急</option>
                  </select>
                </div>
                {/* 确认 + 下一步 */}
                <div className="space-y-2 pt-1 border-t border-gray-100">
                  <label className="flex items-start gap-2 cursor-pointer text-2xs text-gray-700 leading-snug">
                    <input
                      type="checkbox"
                      checked={confirmStep1}
                      onChange={e => setConfirmStep1(e.target.checked)}
                      className={`mt-0.5 ${formCheckboxClass()}`}
                    />
                    <span>已确认配置</span>
                  </label>
                  <button
                    type="button"
                    onClick={advanceToUploadStep}
                    disabled={!isStep1Complete}
                    className="w-full px-4 py-2 text-sm font-medium rounded-xl bg-[#1d1d1f] text-white hover:bg-[#2d2d2f] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    下一步：上传
                  </button>
                </div>
              </div>
              {/* 右侧：配置详情预览（只读 Tab 切换） */}
              <div className="flex-1 min-w-0 flex flex-col rounded-xl border border-gray-100 bg-[#fafafa] dark:bg-gray-900 overflow-hidden">
                <SmartDetailTabs
                  cfg={cfg}
                  textTypes={textTypes}
                  pipelines={pipelines}
                  presets={presets}
                  setCfg={setCfg}
                />
              </div>
            </div>
          ) : (
            /* ====== 旧模式（text / image）：原有单栏布局 ====== */
            <div className="rounded-lg border border-gray-100 bg-[#fafafa] dark:bg-gray-900 flex flex-col flex-1 min-h-0 overflow-hidden p-2 space-y-2">
              <div className="text-2xs text-gray-500 leading-snug space-y-0.5">
                <p><span className="text-gray-600">「默认」</span>与「识别项配置」中当前启用的类型一致。</p>
              </div>
              <div className="max-w-xl">
                {mode === 'text' && (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-medium text-gray-800">文本脱敏配置清单</label>
                    <select className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white w-full" value={cfg.presetTextId ?? ''} onChange={onBatchTextPresetChange}>
                      <option value="">默认</option>
                      {textPresets.map(p => <option key={p.id} value={p.id}>{p.name}{p.kind === 'full' ? '（组合）' : ''}</option>)}
                    </select>
                  </div>
                )}
                {mode === 'image' && (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-medium text-gray-800">图像脱敏配置清单</label>
                    <select className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white w-full" value={cfg.presetVisionId ?? ''} onChange={onBatchVisionPresetChange}>
                      <option value="">默认</option>
                      {visionPresets.map(p => <option key={p.id} value={p.id}>{p.name}{p.kind === 'full' ? '（组合）' : ''}</option>)}
                    </select>
                  </div>
                )}
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-black/[0.06] bg-white/80 p-2">
                <PresetDetailBlock cfg={cfg} textTypes={textTypes} pipelines={pipelines} allPresets={presets} scope={mode} onReplacementModeChange={m => setCfg(c => ({ ...c, presetTextId: null, replacementMode: m }))} onVisionImagePatch={patch => setCfg(c => ({ ...c, presetVisionId: null, ...patch }))} />
              </div>
            </div>
          )}

          {/* 旧模式：优先级 + 确认（smart 模式已内含在左侧） */}
          {mode !== 'smart' && configLoaded && (
            <>
              <div className="flex items-center gap-2 pt-1.5 mt-0.5 border-t border-gray-100 shrink-0">
                <span className="text-2xs text-gray-500">任务优先级</span>
                <select value={jobPriority} onChange={e => setJobPriority(Number(e.target.value))} className="text-2xs border border-gray-200 rounded-lg px-2 py-1 bg-white">
                  <option value={0}>普通</option>
                  <option value={5}>高</option>
                  <option value={10}>紧急</option>
                </select>
              </div>
              <label className="flex items-start gap-2 cursor-pointer text-2xs text-gray-700 mb-1 leading-snug shrink-0">
                <input type="checkbox" checked={confirmStep1} onChange={e => setConfirmStep1(e.target.checked)} className={`mt-0.5 ${formCheckboxClass()}`} />
                <span>已确认当前识别与脱敏配置；未勾选无法进入「上传」。</span>
              </label>
              <div className="flex justify-end">
                <button type="button" onClick={advanceToUploadStep} disabled={!isStep1Complete} className="px-4 py-2 text-sm font-medium rounded-xl bg-[#1d1d1f] text-white hover:bg-[#2d2d2f] disabled:opacity-40 disabled:cursor-not-allowed">下一步：上传</button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
};
