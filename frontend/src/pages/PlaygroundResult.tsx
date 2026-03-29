import React from 'react';
import ImageBBoxEditor from '../components/ImageBBoxEditor';
import { getEntityRiskConfig } from '../config/entityTypes';
import { downloadFile } from '../services/api';
import type {
  FileInfo,
  Entity,
  BoundingBox,
  VisionTypeConfig,
} from './playground-types';

export interface PlaygroundResultProps {
  fileInfo: FileInfo | null;
  content: string;
  entities: Entity[];
  entityMap: Record<string, string>;
  redactedCount: number;
  redactionReport: any;
  reportOpen: boolean;
  setReportOpen: React.Dispatch<React.SetStateAction<boolean>>;
  versionHistory: any[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: React.Dispatch<React.SetStateAction<boolean>>;
  isImageMode: boolean;
  imageUrl: string;
  redactedImageUrl?: string;
  boundingBoxes: BoundingBox[];
  visibleBoxes: BoundingBox[];
  visionTypes: VisionTypeConfig[];
  getVisionTypeConfig: (typeId: string) => { name: string; color: string };
  replacementMode: string;
  onBackToEdit: () => void;
  onReset: () => void;
}

export const PlaygroundResult: React.FC<PlaygroundResultProps> = ({
  fileInfo,
  content,
  entities,
  entityMap,
  redactedCount,
  redactionReport,
  reportOpen,
  setReportOpen,
  versionHistory,
  versionHistoryOpen,
  setVersionHistoryOpen,
  isImageMode,
  imageUrl,
  redactedImageUrl: redactedImageUrlProp,
  visibleBoxes,
  visionTypes,
  getVisionTypeConfig,
  onBackToEdit,
  onReset,
}) => {
  // 共享分段：按 entityMap keys 把原文切段，每段记录 { origKey, matchIdx }
  const buildSegments = (text: string, map: Record<string, string>) => {
    if (!text || Object.keys(map).length === 0) return [{ text, isMatch: false as const }];
    const sortedKeys = Object.keys(map).sort((a, b) => b.length - a.length);
    const regex = new RegExp(`(${sortedKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
    const parts = text.split(regex);
    const counters: Record<string, number> = {};
    return parts.map(part => {
      if (map[part] !== undefined) {
        const safeKey = part.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
        const idx = counters[safeKey] || 0;
        counters[safeKey] = idx + 1;
        return { text: part, isMatch: true as const, origKey: part, safeKey, matchIdx: idx };
      }
      return { text: part, isMatch: false as const };
    });
  };

  const segments = buildSegments(content, entityMap);

  /** 原文片段 → 实体类型（与 ENTITY_PALETTE 四套统一色一致） */
  const origToTypeId = new Map<string, string>();
  for (const e of entities) {
    if (!e.selected) continue;
    if (entityMap[e.text] === undefined) continue;
    const tid = String(e.type);
    origToTypeId.set(e.text, tid);
    if (typeof e.start === 'number' && typeof e.end === 'number' && e.end <= (content || '').length) {
      const sl = (content || '').slice(e.start, e.end);
      if (sl && sl !== e.text) origToTypeId.set(sl, tid);
    }
  }

  const markStyleForOrig = (origKey: string): React.CSSProperties => {
    const tid = origToTypeId.get(origKey) ?? '';
    const cfg = getEntityRiskConfig(tid || 'CUSTOM');
    return {
      backgroundColor: cfg.bgColor,
      color: cfg.textColor,
      boxShadow: `inset 0 -2px 0 ${cfg.color}55`,
    };
  };

  const renderOriginal = () => (
    <>{segments.map((seg, i) =>
      seg.isMatch
        ? <mark key={i} data-match-key={seg.safeKey} data-match-idx={seg.matchIdx}
            style={markStyleForOrig(seg.origKey)}
            className="result-mark-orig px-0.5 rounded-md transition-all duration-300">{seg.text}</mark>
        : <span key={i}>{seg.text}</span>
    )}</>
  );

  const renderRedacted = () => (
    <>{segments.map((seg, i) =>
      seg.isMatch
        ? <mark key={i} data-match-key={seg.safeKey} data-match-idx={seg.matchIdx}
            style={markStyleForOrig(seg.origKey)}
            className="result-mark-redacted px-0.5 rounded-md transition-all duration-300">{entityMap[seg.origKey]}</mark>
        : <span key={i}>{seg.text}</span>
    )}</>
  );

  // 每个映射项的点击计数器（循环切换出现位置）
  const clickCounterRef: Record<string, number> = {};

  // 点击映射项 → 两列同时滚动到第N次出现
  const scrollToMatch = (orig: string, _repl: string) => {
    const safeKey = orig.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
    // 查找所有匹配的原文标记
    const origMarks = document.querySelectorAll(`.result-mark-orig[data-match-key="${safeKey}"]`);
    const redactedMarks = document.querySelectorAll(`.result-mark-redacted[data-match-key="${safeKey}"]`);
    const total = Math.max(origMarks.length, redactedMarks.length);
    if (total === 0) return;
    // 循环索引
    const idx = (clickCounterRef[safeKey] || 0) % total;
    clickCounterRef[safeKey] = idx + 1;
    // 清除所有旧高亮
    document.querySelectorAll('.result-mark-active').forEach(el => {
      el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    });
    // 滚动原文
    const origEl = origMarks[Math.min(idx, origMarks.length - 1)] as HTMLElement;
    if (origEl) {
      origEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      origEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    }
    // 滚动脱敏结果
    const redEl = redactedMarks[Math.min(idx, redactedMarks.length - 1)] as HTMLElement;
    if (redEl) {
      redEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      redEl.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    }
    // 2秒后清除
    setTimeout(() => {
      document.querySelectorAll('.result-mark-active').forEach(el => {
        el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
      });
    }, 2500);
  };

  return (
        <div className="flex-1 flex flex-col min-h-0 min-w-0 overflow-hidden">
          {/* 顶部状态栏 */}
          <div className="flex-shrink-0 mx-3 sm:mx-4 mt-3 sm:mt-4 mb-2 sm:mb-3">
            <div className="bg-black rounded-2xl px-6 py-4 flex items-center justify-between shadow-md shadow-black/25">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center">
                  <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <div>
                  <p className="text-white text-sm font-semibold">脱敏完成</p>
                  <p className="text-white/70 text-xs">{redactedCount} 处敏感信息已处理</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={onBackToEdit} className="px-3 py-1.5 text-xs text-white/90 hover:text-white bg-white/15 hover:bg-white/25 rounded-lg transition-all">返回编辑</button>
                <button onClick={onReset} className="px-3 py-1.5 text-xs text-white/90 hover:text-white bg-white/15 hover:bg-white/25 rounded-lg transition-all">新文件</button>
                {fileInfo && (
                  <button type="button" onClick={() => downloadFile(
                    `/api/v1/files/${fileInfo.file_id}/download?redacted=true`,
                    `redacted_${fileInfo.filename}`
                  ).catch(() => {})} className="px-4 py-1.5 text-xs font-medium text-black bg-white hover:bg-zinc-200 rounded-lg transition-all">下载文件</button>
                )}
              </div>
            </div>
          </div>

          {/* 脱敏质量报告（可折叠） */}
          {redactionReport && (
            <div className="flex-shrink-0 mx-3 sm:mx-4 mb-2">
              <button
                onClick={() => setReportOpen(v => !v)}
                className="w-full flex items-center justify-between bg-white border border-gray-200/80 rounded-2xl px-5 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight flex items-center gap-2">
                  <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                  脱敏质量报告
                </span>
                <svg className={`w-4 h-4 text-gray-400 transition-transform ${reportOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
              </button>
              {reportOpen && (() => {
                const r = redactionReport;
                const maxTypeCount = Math.max(1, ...Object.values(r.entity_type_distribution || {}) as number[]);
                const maxSourceCount = Math.max(1, ...Object.values(r.source_distribution || {}) as number[]);
                const confTotal = Math.max(1, (r.confidence_distribution?.high || 0) + (r.confidence_distribution?.medium || 0) + (r.confidence_distribution?.low || 0));
                return (
                  <div className="bg-white border border-t-0 border-gray-200/80 rounded-b-2xl -mt-3 pt-3 px-5 pb-4 space-y-4">
                    <div className="flex gap-6 flex-wrap">
                      <div className="flex flex-col">
                        <span className="text-2xs text-gray-400 uppercase tracking-wider">识别实体总数</span>
                        <span className="text-lg font-bold text-[#1d1d1f] tabular-nums">{r.total_entities}</span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-2xs text-gray-400 uppercase tracking-wider">已脱敏数</span>
                        <span className="text-lg font-bold text-[#1d1d1f] tabular-nums">{r.redacted_entities}</span>
                      </div>
                      <div className="flex flex-col min-w-[160px] flex-1 max-w-xs">
                        <span className="text-2xs text-gray-400 uppercase tracking-wider mb-1">覆盖率</span>
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                            <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, r.coverage_rate)}%`, backgroundColor: r.coverage_rate >= 80 ? '#22c55e' : r.coverage_rate >= 50 ? '#f59e0b' : '#ef4444' }} />
                          </div>
                          <span className="text-xs font-semibold tabular-nums text-[#1d1d1f]">{r.coverage_rate}%</span>
                        </div>
                      </div>
                      {r.redaction_mode && (
                        <div className="flex flex-col">
                          <span className="text-2xs text-gray-400 uppercase tracking-wider">替换模式</span>
                          <span className="text-xs font-medium text-[#1d1d1f] mt-0.5">{r.redaction_mode}</span>
                        </div>
                      )}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div>
                        <p className="text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-2">实体类型分布</p>
                        <div className="space-y-1.5">
                          {Object.entries(r.entity_type_distribution || {}).sort(([,a]: any, [,b]: any) => b - a).map(([type, count]: any) => (
                            <div key={type} className="flex items-center gap-2">
                              <span className="text-2xs text-gray-600 w-16 truncate flex-shrink-0">{type}</span>
                              <div className="flex-1 h-3 bg-gray-100 rounded-sm overflow-hidden">
                                <div className="h-full bg-indigo-400 rounded-sm" style={{ width: `${(count / maxTypeCount) * 100}%` }} />
                              </div>
                              <span className="text-2xs text-gray-500 tabular-nums w-6 text-right">{count}</span>
                            </div>
                          ))}
                          {Object.keys(r.entity_type_distribution || {}).length === 0 && <p className="text-2xs text-gray-400">无文本实体</p>}
                        </div>
                      </div>
                      <div>
                        <p className="text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-2">置信度分布</p>
                        <div className="space-y-1.5">
                          {[
                            { key: 'high', label: '高 (>0.8)', color: '#22c55e' },
                            { key: 'medium', label: '中 (0.5-0.8)', color: '#f59e0b' },
                            { key: 'low', label: '低 (<0.5)', color: '#ef4444' },
                          ].map(({ key, label, color }) => {
                            const cnt = r.confidence_distribution?.[key] || 0;
                            return (
                              <div key={key} className="flex items-center gap-2">
                                <span className="text-2xs text-gray-600 w-20 flex-shrink-0">{label}</span>
                                <div className="flex-1 h-3 bg-gray-100 rounded-sm overflow-hidden">
                                  <div className="h-full rounded-sm" style={{ width: `${(cnt / confTotal) * 100}%`, backgroundColor: color }} />
                                </div>
                                <span className="text-2xs text-gray-500 tabular-nums w-6 text-right">{cnt}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      <div>
                        <p className="text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-2">来源分布</p>
                        <div className="space-y-1.5">
                          {Object.entries(r.source_distribution || {}).sort(([,a]: any, [,b]: any) => b - a).map(([src, count]: any) => (
                            <div key={src} className="flex items-center gap-2">
                              <span className="text-2xs text-gray-600 w-16 truncate flex-shrink-0">{src}</span>
                              <div className="flex-1 h-3 bg-gray-100 rounded-sm overflow-hidden">
                                <div className="h-full bg-violet-400 rounded-sm" style={{ width: `${(count / maxSourceCount) * 100}%` }} />
                              </div>
                              <span className="text-2xs text-gray-500 tabular-nums w-6 text-right">{count}</span>
                            </div>
                          ))}
                          {Object.keys(r.source_distribution || {}).length === 0 && <p className="text-2xs text-gray-400">无来源信息</p>}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {/* 三列主体 */}
          {isImageMode ? (
            <div className="flex-1 flex gap-2 sm:gap-3 px-3 sm:px-4 pb-3 sm:pb-4 min-h-0 min-w-0">
              {/* 左：原始图片（与右侧同高视口、同底色，只读无工具栏） */}
              <div className="flex-1 min-w-0 min-h-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">原始图片</span>
                </div>
                <div className="flex-1 min-h-0 min-w-0 flex flex-col">
                  {fileInfo && (
                    <ImageBBoxEditor
                      readOnly
                      imageSrc={imageUrl}
                      boxes={visibleBoxes}
                      onBoxesChange={() => {}}
                      getTypeConfig={getVisionTypeConfig}
                      availableTypes={visionTypes.map(t => ({ id: t.id, name: t.name, color: '#6366F1' }))}
                      defaultType={visionTypes[0]?.id || 'CUSTOM'}
                    />
                  )}
                </div>
              </div>
              {/* 中：脱敏后图片（与左侧相同 flex 视口 + object-contain，缩放一致） */}
              <div className="flex-1 min-w-0 min-h-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏结果</span>
                </div>
                <div className="flex-1 min-h-0 min-w-0 flex items-center justify-center bg-[#f0f0f2] overflow-hidden">
                  {fileInfo && (
                    <img
                      src={redactedImageUrlProp || `/api/v1/files/${fileInfo.file_id}/download?redacted=true`}
                      alt="redacted"
                      className="max-w-full max-h-full w-auto h-auto object-contain select-none block"
                    />
                  )}
                </div>
              </div>
              {/* 右：映射表 */}
              <div className="w-52 sm:w-60 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden min-h-0 min-w-0">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏记录</span>
                  <span className="text-2xs text-[#a3a3a3] tabular-nums">{Object.keys(entityMap).length}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  {Object.entries(entityMap).map(([orig, repl], i) => {
                    const cfg = getEntityRiskConfig(origToTypeId.get(orig) ?? 'CUSTOM');
                    return (
                      <button
                        key={i}
                        onClick={() => scrollToMatch(orig, repl)}
                        className="w-full text-left px-3 py-2.5 mx-1.5 my-1.5 rounded-xl border border-black/[0.06] shadow-sm shadow-violet-900/5 hover:brightness-[0.99] transition-all"
                        style={{ borderLeft: `3px solid ${cfg.color}`, backgroundColor: cfg.bgColor }}
                      >
                        <div className="text-caption font-medium truncate" style={{ color: cfg.textColor }}>{orig}</div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <svg className="w-2.5 h-2.5 opacity-40 flex-shrink-0" style={{ color: cfg.color }} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
                          <span className="text-caption truncate opacity-90" style={{ color: cfg.textColor }}>{repl}</span>
                        </div>
                      </button>
                    );
                  })}
                  {Object.keys(entityMap).length === 0 && <p className="text-xs text-[#a3a3a3] text-center py-6">暂无记录</p>}
                </div>
                {/* 版本历史 (image mode) */}
                {versionHistory.length > 0 && (
                  <div className="border-t border-gray-100">
                    <button
                      onClick={() => setVersionHistoryOpen(v => !v)}
                      className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 transition-colors"
                    >
                      <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">版本历史</span>
                      <div className="flex items-center gap-1.5">
                        <span className="text-2xs text-[#a3a3a3] tabular-nums">{versionHistory.length}</span>
                        <svg className={`w-3 h-3 text-[#a3a3a3] transition-transform ${versionHistoryOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </button>
                    {versionHistoryOpen && (
                      <div className="px-3 pb-3 space-y-1.5">
                        {versionHistory.map((v: any) => (
                          <div
                            key={v.version}
                            className="px-3 py-2 rounded-lg border border-black/[0.06] bg-[#fafafa]"
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-medium text-[#1d1d1f]">v{v.version}</span>
                              <span className="text-2xs text-[#a3a3a3] tabular-nums">
                                {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-2xs text-[#737373]">{v.redacted_count} 处</span>
                              <span className="text-2xs text-[#a3a3a3]">{v.mode}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex gap-2 sm:gap-3 px-3 sm:px-4 pb-3 sm:pb-4 min-h-0 min-w-0">
              {/* 左：原始文档 */}
              <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">原始文档</span>
                </div>
                <div className="flex-1 overflow-auto p-4" id="original-scroll">
                  <div className="text-sm leading-relaxed text-[#262626] whitespace-pre-wrap font-[system-ui]">
                    {renderOriginal()}
                  </div>
                </div>
              </div>
              {/* 中：脱敏后文档 */}
              <div className="flex-1 min-w-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏结果</span>
                </div>
                <div className="flex-1 overflow-auto p-4" id="redacted-scroll">
                  <div className="text-sm leading-relaxed text-[#262626] whitespace-pre-wrap font-[system-ui]">
                    {renderRedacted()}
                  </div>
                </div>
              </div>
              {/* 右：映射列表 */}
              <div className="w-64 flex-shrink-0 bg-white rounded-2xl border border-gray-200/80 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                  <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">脱敏记录</span>
                  <span className="text-2xs text-[#a3a3a3] tabular-nums">{Object.keys(entityMap).length}</span>
                </div>
                <div className="flex-1 overflow-auto">
                  {Object.entries(entityMap).map(([orig, repl], i) => {
                    const count = (content || '').split(orig).length - 1;
                    const cfg = getEntityRiskConfig(origToTypeId.get(orig) ?? 'CUSTOM');
                    return (
                      <button
                        key={i}
                        onClick={() => scrollToMatch(orig, repl)}
                        className="w-full text-left px-3 py-2.5 mx-1.5 my-1.5 rounded-xl border border-black/[0.06] shadow-sm shadow-violet-900/5 hover:brightness-[0.99] transition-all"
                        style={{ borderLeft: `3px solid ${cfg.color}`, backgroundColor: cfg.bgColor }}
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-caption font-medium truncate flex-1" style={{ color: cfg.textColor }}>{orig}</span>
                          {count > 1 && (
                            <span
                              className="text-2xs rounded px-1 flex-shrink-0 tabular-nums"
                              style={{ backgroundColor: `${cfg.color}22`, color: cfg.textColor }}
                            >
                              {count}处
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <svg className="w-2.5 h-2.5 opacity-40 flex-shrink-0" style={{ color: cfg.color }} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
                          <span className="text-caption truncate opacity-90" style={{ color: cfg.textColor }}>{repl}</span>
                        </div>
                      </button>
                    );
                  })}
                  {Object.keys(entityMap).length === 0 && <p className="text-xs text-[#a3a3a3] text-center py-8">暂无记录</p>}
                </div>
                {/* 版本历史 */}
                {versionHistory.length > 0 && (
                  <div className="border-t border-gray-100">
                    <button
                      onClick={() => setVersionHistoryOpen(v => !v)}
                      className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 transition-colors"
                    >
                      <span className="text-xs font-semibold text-[#1d1d1f] tracking-tight">版本历史</span>
                      <div className="flex items-center gap-1.5">
                        <span className="text-2xs text-[#a3a3a3] tabular-nums">{versionHistory.length}</span>
                        <svg className={`w-3 h-3 text-[#a3a3a3] transition-transform ${versionHistoryOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </button>
                    {versionHistoryOpen && (
                      <div className="px-3 pb-3 space-y-1.5">
                        {versionHistory.map((v: any) => (
                          <div
                            key={v.version}
                            className="px-3 py-2 rounded-lg border border-black/[0.06] bg-[#fafafa]"
                          >
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-medium text-[#1d1d1f]">v{v.version}</span>
                              <span className="text-2xs text-[#a3a3a3] tabular-nums">
                                {v.created_at ? new Date(v.created_at).toLocaleString() : ''}
                              </span>
                            </div>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-2xs text-[#737373]">{v.redacted_count} 处</span>
                              <span className="text-2xs text-[#a3a3a3]">{v.mode}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
  );
};

export default PlaygroundResult;
