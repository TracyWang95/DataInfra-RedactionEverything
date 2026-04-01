import React from 'react';
import {
  selectableCardClassCompact,
  selectableCheckboxClass,
  textGroupKeyToVariant,
  type SelectionVariant,
} from '../ui/selectionClasses';
import type { RecognitionPreset } from '../services/presetsApi';
import type {
  EntityTypeConfig,
  VisionTypeConfig,
  PipelineConfig,
} from './playground-types';

/** 上传/预览侧栏：紧凑气泡，减轻 16 寸屏纵向滚动 */
const pgTypeBubbleClass = (selected: boolean, variant: SelectionVariant) =>
  `${selectableCardClassCompact(selected, variant)} flex items-center gap-1 px-1.5 py-1 text-2xs leading-tight cursor-pointer min-w-0 !rounded-lg`;

export interface PlaygroundUploadProps {
  // Dropzone
  getRootProps: () => any;
  getInputProps: () => any;
  isDragActive: boolean;
  // Type config
  typeTab: 'text' | 'vision';
  setTypeTab: (tab: 'text' | 'vision') => void;
  entityTypes: EntityTypeConfig[];
  selectedTypes: string[];
  setSelectedTypes: React.Dispatch<React.SetStateAction<string[]>>;
  visionTypes: VisionTypeConfig[];
  pipelines: PipelineConfig[];
  selectedOcrHasTypes: string[];
  selectedHasImageTypes: string[];
  toggleVisionType: (typeId: string, pipelineMode: 'ocr_has' | 'has_image') => void;
  updateOcrHasTypes: (types: string[]) => void;
  updateHasImageTypes: (types: string[]) => void;
  // Preset
  textPresetsPg: RecognitionPreset[];
  visionPresetsPg: RecognitionPreset[];
  playgroundPresetTextId: string | null;
  playgroundPresetVisionId: string | null;
  selectPlaygroundTextPresetById: (id: string) => void;
  selectPlaygroundVisionPresetById: (id: string) => void;
  saveTextPresetFromPlayground: () => void;
  saveVisionPresetFromPlayground: () => void;
  clearPlaygroundTextPresetTracking: () => void;
  clearPlaygroundVisionPresetTracking: () => void;
  // Groups
  sortedEntityTypes: EntityTypeConfig[];
  playgroundTextGroups: { key: 'regex' | 'llm' | 'other'; label: string; types: EntityTypeConfig[] }[];
  setPlaygroundTextTypeGroupSelection: (ids: string[], turnOn: boolean) => void;
}

export const PlaygroundUpload: React.FC<PlaygroundUploadProps> = ({
  getRootProps,
  getInputProps,
  isDragActive,
  typeTab,
  setTypeTab,
  entityTypes,
  selectedTypes,
  setSelectedTypes,
  pipelines,
  selectedOcrHasTypes,
  selectedHasImageTypes,
  toggleVisionType,
  updateOcrHasTypes,
  updateHasImageTypes,
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
}) => {
  return (
        <div className="flex-1 flex flex-col lg:flex-row gap-3 lg:gap-5 p-3 lg:p-5 min-h-0 min-w-0 overflow-hidden">
          {/* 上传区域 */}
          <div className="flex-1 flex items-center justify-center min-h-0 min-w-0">
            <div className="w-full max-w-lg">
              <div
                {...getRootProps()}
                className={`playground-drop-card border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all bg-white dark:bg-gray-800 ${
                  isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400'
                }`}
              >
                <input {...getInputProps()} />
                <div className="w-14 h-14 mx-auto mb-4 rounded-xl bg-blue-100 dark:bg-[#1c2940] flex items-center justify-center">
                  <svg className="w-7 h-7 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                  </svg>
                </div>
                <p className="text-base font-medium text-[#1d1d1f] dark:text-[#eef3fb] mb-1">拖拽文件到此处上传</p>
                <p className="text-sm text-[#737373] dark:text-[#94a0af] mb-4">支持 .doc .docx .pdf .jpg .png</p>
              </div>
            </div>
          </div>

          {/* 类型配置面板 */}
          <div className="playground-side-surface w-full lg:w-[min(100%,400px)] xl:w-[420px] 2xl:w-[460px] shrink-0 max-h-[min(52vh,480px)] lg:max-h-none lg:self-stretch bg-white/90 dark:bg-gray-800/90 backdrop-blur-2xl rounded-2xl border border-black/[0.06] dark:border-gray-700 flex flex-col shadow-[0_2px_16px_rgba(0,0,0,0.06)] min-h-0 overflow-hidden">
            {/* 头部 */}
            <div className="px-3 py-2 border-b border-gray-100/80 dark:border-gray-700 space-y-1.5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[#1d1d1f] dark:text-[#eef3fb] tracking-tight">识别类型</h3>
                <div className="playground-tab-strip flex bg-gray-100 dark:bg-gray-700 rounded-lg p-0.5">
                  <button onClick={() => setTypeTab('text')} className={`playground-tab-button text-caption px-2.5 py-1 rounded-md font-medium transition-all ${typeTab === 'text' ? 'playground-tab-button-active bg-white text-[#1d1d1f] shadow-sm' : 'text-[#737373]'}`}>文本</button>
                  <button onClick={() => setTypeTab('vision')} className={`playground-tab-button text-caption px-2.5 py-1 rounded-md font-medium transition-all ${typeTab === 'vision' ? 'playground-tab-button-active bg-white text-[#1d1d1f] shadow-sm' : 'text-[#737373]'}`}>图像</button>
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-0.5">
                  <span className="text-2xs text-[#737373]">文本脱敏配置清单</span>
                  <div className="flex items-center gap-1.5 min-w-0">
                    <select
                      className="text-2xs flex-1 min-w-0 border border-gray-200 rounded-md px-1.5 py-1 bg-white dark:bg-[#0f141c] dark:border-white/[0.08]"
                      value={playgroundPresetTextId ?? ''}
                      onChange={e => selectPlaygroundTextPresetById(e.target.value)}
                    >
                      <option value="">默认</option>
                      {textPresetsPg.map(p => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                          {p.kind === 'full' ? '（组合）' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void saveTextPresetFromPlayground()}
                      className="text-2xs shrink-0 px-1.5 py-1 rounded-md border border-gray-200 hover:bg-gray-50 dark:border-white/[0.08] dark:hover:bg-white/[0.06] whitespace-nowrap"
                    >
                      另存为文本预设
                    </button>
                  </div>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-2xs text-[#737373]">图像脱敏配置清单</span>
                  <div className="flex items-center gap-1.5 min-w-0">
                    <select
                      className="text-2xs flex-1 min-w-0 border border-gray-200 rounded-md px-1.5 py-1 bg-white dark:bg-[#0f141c] dark:border-white/[0.08]"
                      value={playgroundPresetVisionId ?? ''}
                      onChange={e => selectPlaygroundVisionPresetById(e.target.value)}
                    >
                      <option value="">默认</option>
                      {visionPresetsPg.map(p => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                          {p.kind === 'full' ? '（组合）' : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void saveVisionPresetFromPlayground()}
                      className="text-2xs shrink-0 px-1.5 py-1 rounded-md border border-gray-200 hover:bg-gray-50 dark:border-white/[0.08] dark:hover:bg-white/[0.06] whitespace-nowrap"
                    >
                      另存为图像预设
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* 内容区 */}
            <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
              {typeTab === 'vision' ? (
                pipelines.length === 0 ? (
                  <p className="text-caption text-[#a3a3a3] text-center py-8">加载中...</p>
                ) : (
                  <div className="p-2 space-y-3">
                    {pipelines.map(pipeline => {
                      const isHasImage = pipeline.mode === 'has_image';
                      const types = pipeline.types.filter(t => t.enabled);
                      const selectedSet = isHasImage ? selectedHasImageTypes : selectedOcrHasTypes;
                      const allSelected = types.length > 0 && types.every(t => selectedSet.includes(t.id));

                      const presetGroups = isHasImage
                        ? [
                            {
                              label: '视觉元素',
                              ids: [
                                'SIGNATURE',
                                'FINGERPRINT',
                                'PHOTO',
                                'QR_CODE',
                                'HANDWRITING',
                                'WATERMARK',
                                'CHAT_BUBBLE',
                                'SENSITIVE_TABLE',
                              ],
                            },
                          ]
                        : [];
                      const allPresetIds = new Set(presetGroups.flatMap(g => g.ids));
                      const customTypes = isHasImage ? types.filter(t => !allPresetIds.has(t.id)) : [];
                      const visionGroups =
                        isHasImage && customTypes.length > 0
                          ? [...presetGroups, { label: '自定义', ids: customTypes.map(t => t.id) }]
                          : isHasImage
                            ? presetGroups
                            : [];

                      return (
                        <div key={pipeline.mode}>
                          <div className="flex items-center justify-between mb-1.5 pb-1 border-b border-gray-200/90 dark:border-gray-700">
                            <span
                              className={`text-2xs font-semibold text-[#1d1d1f] pl-2 border-l-[3px] ${
                                isHasImage ? 'border-[#AF52DE]' : 'border-[#34C759]'
                              }`}
                            >
                              {isHasImage ? '图像特征' : '图片类文本'}
                            </span>
                            <button onClick={() => {
                              clearPlaygroundVisionPresetTracking();
                              const ids = types.map(t => t.id);
                              if (allSelected) { if (isHasImage) updateHasImageTypes([]); else updateOcrHasTypes([]); }
                              else { if (isHasImage) updateHasImageTypes(ids); else updateOcrHasTypes(ids); }
                            }} className="text-2xs text-[#a3a3a3] hover:text-[#737373] transition-colors">
                              {allSelected ? '清空' : '全选'}
                            </button>
                          </div>
                          <div className="space-y-2">
                            {!isHasImage ? (
                              <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
                                {types.map(type => {
                                  const checked = selectedSet.includes(type.id);
                                  const v: SelectionVariant = 'ner';
                                  return (
                                    <label
                                      key={type.id}
                                      className={pgTypeBubbleClass(checked, v)}
                                      title={type.description || type.name}
                                    >
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                                        className={`shrink-0 ${selectableCheckboxClass(v)}`}
                                      />
                                      <span className="min-w-0 break-words">{type.name}</span>
                                    </label>
                                  );
                                })}
                              </div>
                            ) : (
                              visionGroups.map(group => {
                                const groupTypes = types.filter(t => group.ids.includes(t.id));
                                if (groupTypes.length === 0) return null;
                                return (
                                  <div key={group.label}>
                                    <div className="text-2xs text-[#737373] font-medium mb-0.5 pl-0.5">{group.label}</div>
                                    <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
                                      {groupTypes.map(type => {
                                        const checked = selectedSet.includes(type.id);
                                        const v: SelectionVariant = 'yolo';
                                        return (
                                          <label
                                            key={type.id}
                                            className={pgTypeBubbleClass(checked, v)}
                                            title={type.description || type.name}
                                          >
                                            <input
                                              type="checkbox"
                                              checked={checked}
                                              onChange={() => toggleVisionType(type.id, pipeline.mode as 'ocr_has' | 'has_image')}
                                              className={`shrink-0 ${selectableCheckboxClass(v)}`}
                                            />
                                            <span className="min-w-0 break-words">{type.name}</span>
                                          </label>
                                        );
                                      })}
                                    </div>
                                  </div>
                                );
                              })
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )
              ) : sortedEntityTypes.length === 0 ? (
                <p className="text-caption text-[#a3a3a3] text-center py-8">加载中...</p>
              ) : (
                <div className="p-2 space-y-3">
                  {playgroundTextGroups.map(group => {
                    const ids = group.types.map(t => t.id);
                    const allOn = ids.length > 0 && ids.every(id => selectedTypes.includes(id));
                    return (
                      <div key={group.key}>
                        <div className="flex items-center justify-between mb-1.5 pb-1 border-b border-gray-200/90 dark:border-gray-700">
                          <span
                            className={`text-2xs font-semibold text-[#1d1d1f] pl-2 border-l-[3px] ${
                              group.key === 'regex'
                                ? 'border-[#007AFF]'
                                : group.key === 'llm'
                                  ? 'border-[#34C759]'
                                  : 'border-violet-300/60'
                            }`}
                          >
                            {group.label}
                          </span>
                          <button
                            type="button"
                            onClick={() => setPlaygroundTextTypeGroupSelection(ids, !allOn)}
                            className="text-2xs text-[#a3a3a3] hover:text-[#737373] transition-colors"
                          >
                            {allOn ? '清空' : '全选'}
                          </button>
                        </div>
                        <div className="space-y-2">
                          <div className="grid grid-cols-2 lg:grid-cols-3 gap-1.5">
                            {group.types.map(type => {
                              const checked = selectedTypes.includes(type.id);
                              const v = textGroupKeyToVariant(group.key);
                              return (
                                <label
                                  key={`${group.key}-${type.id}`}
                                  className={pgTypeBubbleClass(checked, v)}
                                  title={type.description || type.name}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => {
                                      clearPlaygroundTextPresetTracking();
                                      setSelectedTypes(prev =>
                                        checked ? prev.filter(t => t !== type.id) : [...prev, type.id]
                                      );
                                    }}
                                    className={`shrink-0 ${selectableCheckboxClass(v)}`}
                                  />
                                  <span className="min-w-0 break-words">{type.name}</span>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 底部 */}
            <div className="px-3 py-1.5 border-t border-gray-100/80 dark:border-gray-700 shrink-0">
              <div className="text-2xs text-[#a3a3a3] text-center leading-tight">
                {typeTab === 'vision'
                  ? `OCR ${selectedOcrHasTypes.length} · HaS图像 ${selectedHasImageTypes.length}`
                  : `${selectedTypes.length} / ${entityTypes.length} 已选`}
              </div>
            </div>
          </div>
        </div>
  );
};

export default PlaygroundUpload;
