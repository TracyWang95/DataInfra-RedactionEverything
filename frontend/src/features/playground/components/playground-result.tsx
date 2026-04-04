/**
 * Playground result view: original vs redacted text/image, mapping table.
 */
import { type FC, useState, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { t } from '@/i18n';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import { getEntityRiskConfig } from '@/config/entityTypes';
import type { FileInfo, Entity, BoundingBox, VisionTypeConfig } from '../types';
import type { VersionHistoryEntry } from '@/types';

export interface PlaygroundResultProps {
  fileInfo: FileInfo | null;
  content: string;
  entities: Entity[];
  entityMap: Record<string, string>;
  redactedCount: number;
  redactionReport: Record<string, unknown> | null;
  reportOpen: boolean;
  setReportOpen: React.Dispatch<React.SetStateAction<boolean>>;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: React.Dispatch<React.SetStateAction<boolean>>;
  isImageMode: boolean;
  imageUrl: string;
  redactedImageUrl?: string;
  visibleBoxes: BoundingBox[];
  visionTypes: VisionTypeConfig[];
  getVisionTypeConfig: (typeId: string) => { name: string; color: string };
  onBackToEdit: () => void;
  onReset: () => void;
  onDownload: () => void;
}

export const PlaygroundResult: FC<PlaygroundResultProps> = ({
  fileInfo, content, entities, entityMap, redactedCount,
  redactionReport, reportOpen, setReportOpen,
  versionHistory, versionHistoryOpen, setVersionHistoryOpen,
  isImageMode, imageUrl, redactedImageUrl,
  visibleBoxes, visionTypes, getVisionTypeConfig,
  onBackToEdit, onReset, onDownload,
}) => {
  const [mobileTab, setMobileTab] = useState<'original' | 'redacted' | 'mapping'>('original');
  const clickCounterRef = useRef<Record<string, number>>({});

  // Build text segments from entity map
  const origToTypeId = new Map<string, string>();
  for (const e of entities) {
    if (!e.selected || entityMap[e.text] === undefined) continue;
    origToTypeId.set(e.text, String(e.type));
    if (typeof e.start === 'number' && typeof e.end === 'number' && e.end <= (content || '').length) {
      const sl = (content || '').slice(e.start, e.end);
      if (sl && sl !== e.text) origToTypeId.set(sl, String(e.type));
    }
  }

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

  const markStyleForOrig = (origKey: string): React.CSSProperties => {
    const tid = origToTypeId.get(origKey) ?? '';
    const cfg = getEntityRiskConfig(tid || 'CUSTOM');
    return { backgroundColor: cfg.bgColor, color: cfg.textColor, boxShadow: `inset 0 -2px 0 ${cfg.color}55` };
  };

  const scrollToMatch = (orig: string) => {
    const safeKey = orig.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_');
    const origMarks = document.querySelectorAll(`.result-mark-orig[data-match-key="${safeKey}"]`);
    const redactedMarks = document.querySelectorAll(`.result-mark-redacted[data-match-key="${safeKey}"]`);
    const total = Math.max(origMarks.length, redactedMarks.length);
    if (total === 0) return;
    const idx = (clickCounterRef.current[safeKey] || 0) % total;
    clickCounterRef.current[safeKey] = idx + 1;
    document.querySelectorAll('.result-mark-active').forEach(el => el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105'));
    const origEl = origMarks[Math.min(idx, origMarks.length - 1)] as HTMLElement | undefined;
    origEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    origEl?.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    const redEl = redactedMarks[Math.min(idx, redactedMarks.length - 1)] as HTMLElement | undefined;
    redEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    redEl?.classList.add('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105');
    setTimeout(() => {
      document.querySelectorAll('.result-mark-active').forEach(el => el.classList.remove('result-mark-active', 'ring-2', 'ring-offset-1', 'ring-blue-400/80', 'scale-105'));
    }, 2500);
  };

  const renderOrig = () => segments.map((seg, i) =>
    seg.isMatch
      ? <mark key={i} data-match-key={seg.safeKey} data-match-idx={seg.matchIdx} style={markStyleForOrig(seg.origKey)} className="result-mark-orig px-0.5 rounded-md transition-all duration-300">{seg.text}</mark>
      : <span key={i}>{seg.text}</span>,
  );

  const renderRedacted = () => segments.map((seg, i) =>
    seg.isMatch
      ? <mark key={i} data-match-key={seg.safeKey} data-match-idx={seg.matchIdx} style={markStyleForOrig(seg.origKey)} className="result-mark-redacted px-0.5 rounded-md transition-all duration-300">{entityMap[seg.origKey]}</mark>
      : <span key={i}>{seg.text}</span>,
  );

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-0 overflow-hidden" data-testid="playground-result">
      {/* Status bar */}
      <div className="flex-shrink-0 mx-3 sm:mx-4 mt-3 sm:mt-4 mb-2 sm:mb-3">
        <Card className="bg-primary text-primary-foreground border-0">
          <CardContent className="px-6 py-4 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-primary-foreground/15 flex items-center justify-center">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
              </div>
              <div>
                <p className="text-sm font-semibold">{t('playground.redactComplete') || '脱敏完成'}</p>
                <p className="text-xs opacity-70">{redactedCount} {t('playground.itemsProcessed') || '处敏感信息已处理'}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={onBackToEdit} data-testid="playground-back-edit">{t('playground.backToEdit') || '返回编辑'}</Button>
              <Button variant="secondary" size="sm" onClick={onReset}>{t('playground.newFile') || '新文件'}</Button>
              {fileInfo && <Button size="sm" onClick={onDownload} data-testid="playground-download">{t('playground.downloadFile') || '下载文件'}</Button>}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Report (collapsible) */}
      {redactionReport && <RedactionReportSection report={redactionReport} open={reportOpen} onToggle={() => setReportOpen(v => !v)} />}

      {/* Mobile tabs */}
      <div className="flex md:hidden border-b bg-background px-2 gap-1 shrink-0 mx-3 rounded-t-xl">
        {([['original', '原文'], ['redacted', '脱敏结果'], ['mapping', '脱敏记录']] as const).map(([key, label]) => (
          <button key={key} onClick={() => setMobileTab(key)} className={cn('px-3 py-2 text-xs font-medium border-b-2 transition-colors', mobileTab === key ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground')}>
            {label}
          </button>
        ))}
      </div>

      {/* Main content */}
      {isImageMode ? (
        <ImageResultView fileInfo={fileInfo} imageUrl={imageUrl} redactedImageUrl={redactedImageUrl} visibleBoxes={visibleBoxes} visionTypes={visionTypes} getVisionTypeConfig={getVisionTypeConfig} entityMap={entityMap} origToTypeId={origToTypeId} scrollToMatch={scrollToMatch} mobileTab={mobileTab} versionHistory={versionHistory} versionHistoryOpen={versionHistoryOpen} setVersionHistoryOpen={setVersionHistoryOpen} />
      ) : (
        <TextResultView renderOrig={renderOrig} renderRedacted={renderRedacted} content={content} entityMap={entityMap} origToTypeId={origToTypeId} scrollToMatch={scrollToMatch} mobileTab={mobileTab} versionHistory={versionHistory} versionHistoryOpen={versionHistoryOpen} setVersionHistoryOpen={setVersionHistoryOpen} />
      )}
    </div>
  );
};

/* --- Private sub-components --- */

const RedactionReportSection: FC<{ report: Record<string, unknown>; open: boolean; onToggle: () => void }> = ({ report, open, onToggle }) => {
  const r = report as Record<string, number | string | Record<string, number>>;
  return (
    <div className="flex-shrink-0 mx-3 sm:mx-4 mb-2">
      <Button variant="outline" className="w-full justify-between rounded-2xl px-5 py-3 h-auto" onClick={onToggle}>
        <span className="text-xs font-semibold flex items-center gap-2">{t('playground.qualityReport') || '脱敏质量报告'}</span>
        <svg className={cn('w-4 h-4 transition-transform', open && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
      </Button>
      {open && (
        <Card className="rounded-t-none -mt-1 px-5 pb-4 pt-3">
          <CardContent className="p-0 flex gap-6 flex-wrap text-xs">
            <div className="flex flex-col"><span className="text-[10px] text-muted-foreground uppercase">{t('playground.totalEntities') || '识别实体总数'}</span><span className="text-lg font-bold tabular-nums">{String(r.total_entities ?? '')}</span></div>
            <div className="flex flex-col"><span className="text-[10px] text-muted-foreground uppercase">{t('playground.redactedEntities') || '已脱敏数'}</span><span className="text-lg font-bold tabular-nums">{String(r.redacted_entities ?? '')}</span></div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const MappingColumn: FC<{
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  content?: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: React.Dispatch<React.SetStateAction<boolean>>;
  className?: string;
  mobileTab: string;
}> = ({ entityMap, origToTypeId, scrollToMatch, content, versionHistory, versionHistoryOpen, setVersionHistoryOpen, className, mobileTab }) => (
  <div className={cn('bg-background rounded-2xl border flex flex-col overflow-hidden min-h-0 min-w-0', mobileTab === 'mapping' ? '' : 'hidden', 'md:flex', className)}>
    <div className="flex-shrink-0 px-4 py-2.5 border-b flex items-center justify-between bg-muted/40">
      <span className="text-xs font-semibold">{t('playground.mappingRecords') || '脱敏记录'}</span>
      <span className="text-[10px] text-muted-foreground tabular-nums">{Object.keys(entityMap).length}</span>
    </div>
    <ScrollArea className="flex-1">
      {Object.entries(entityMap).map(([orig, repl], i) => {
        const cfg = getEntityRiskConfig(origToTypeId.get(orig) ?? 'CUSTOM');
        const count = content ? (content.split(orig).length - 1) : 0;
        return (
          <button key={i} onClick={() => scrollToMatch(orig)} className="w-full text-left px-3 py-2.5 mx-1.5 my-1.5 rounded-xl border shadow-sm hover:brightness-[0.99] transition-all" style={{ borderLeft: `3px solid ${cfg.color}`, backgroundColor: cfg.bgColor }} data-testid={`playground-mapping-${i}`}>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] font-medium truncate flex-1" style={{ color: cfg.textColor }}>{orig}</span>
              {count > 1 && <span className="text-[10px] rounded px-1 tabular-nums" style={{ backgroundColor: `${cfg.color}22`, color: cfg.textColor }}>{count}处</span>}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <svg className="w-2.5 h-2.5 opacity-40 flex-shrink-0" style={{ color: cfg.color }} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" /></svg>
              <span className="text-[10px] truncate opacity-90" style={{ color: cfg.textColor }}>{repl}</span>
            </div>
          </button>
        );
      })}
      {Object.keys(entityMap).length === 0 && <p className="text-xs text-muted-foreground text-center py-8">{t('playground.noRecords') || '暂无记录'}</p>}
    </ScrollArea>
    {versionHistory.length > 0 && (
      <div className="border-t">
        <Button variant="ghost" className="w-full justify-between px-4 py-2.5 h-auto" onClick={() => setVersionHistoryOpen(v => !v)}>
          <span className="text-xs font-semibold">{t('playground.versionHistory') || '版本历史'}</span>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground tabular-nums">{versionHistory.length}</span>
            <svg className={cn('w-3 h-3 transition-transform', versionHistoryOpen && 'rotate-180')} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </div>
        </Button>
        {versionHistoryOpen && (
          <div className="px-3 pb-3 space-y-1.5">
            {versionHistory.map((v, idx) => (
              <div key={idx} className="px-3 py-2 rounded-lg border bg-muted/30">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">v{idx + 1}</span>
                  <span className="text-[10px] text-muted-foreground tabular-nums">{v.created_at ? new Date(v.created_at).toLocaleString() : ''}</span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-muted-foreground">{v.redacted_count} 处</span>
                  <span className="text-[10px] text-muted-foreground">{v.mode}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )}
  </div>
);

const TextResultView: FC<{
  renderOrig: () => React.ReactNode[];
  renderRedacted: () => React.ReactNode[];
  content: string;
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  mobileTab: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: React.Dispatch<React.SetStateAction<boolean>>;
}> = ({ renderOrig, renderRedacted, content, entityMap, origToTypeId, scrollToMatch, mobileTab, versionHistory, versionHistoryOpen, setVersionHistoryOpen }) => (
  <div className="flex-1 flex gap-2 sm:gap-3 px-3 sm:px-4 pb-3 sm:pb-4 min-h-0 min-w-0">
    <div className={cn('flex-1 min-w-0 bg-background rounded-2xl border flex flex-col overflow-hidden', mobileTab === 'original' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 px-4 py-2.5 border-b bg-muted/40"><span className="text-xs font-semibold">{t('playground.originalDoc') || '原始文档'}</span></div>
      <ScrollArea className="flex-1 p-4"><div className="text-sm leading-relaxed whitespace-pre-wrap font-[system-ui]">{renderOrig()}</div></ScrollArea>
    </div>
    <div className={cn('flex-1 min-w-0 bg-background rounded-2xl border flex flex-col overflow-hidden', mobileTab === 'redacted' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 px-4 py-2.5 border-b bg-muted/40"><span className="text-xs font-semibold">{t('playground.redactedResult') || '脱敏结果'}</span></div>
      <ScrollArea className="flex-1 p-4"><div className="text-sm leading-relaxed whitespace-pre-wrap font-[system-ui]">{renderRedacted()}</div></ScrollArea>
    </div>
    <MappingColumn entityMap={entityMap} origToTypeId={origToTypeId} scrollToMatch={scrollToMatch} content={content} className="md:w-64 md:flex-shrink-0 w-full" mobileTab={mobileTab} versionHistory={versionHistory} versionHistoryOpen={versionHistoryOpen} setVersionHistoryOpen={setVersionHistoryOpen} />
  </div>
);

const ImageResultView: FC<{
  fileInfo: FileInfo | null;
  imageUrl: string;
  redactedImageUrl?: string;
  visibleBoxes: BoundingBox[];
  visionTypes: VisionTypeConfig[];
  getVisionTypeConfig: (typeId: string) => { name: string; color: string };
  entityMap: Record<string, string>;
  origToTypeId: Map<string, string>;
  scrollToMatch: (orig: string) => void;
  mobileTab: string;
  versionHistory: VersionHistoryEntry[];
  versionHistoryOpen: boolean;
  setVersionHistoryOpen: React.Dispatch<React.SetStateAction<boolean>>;
}> = ({ fileInfo, imageUrl, redactedImageUrl, visibleBoxes, visionTypes, getVisionTypeConfig, entityMap, origToTypeId, scrollToMatch, mobileTab, versionHistory, versionHistoryOpen, setVersionHistoryOpen }) => (
  <div className="flex-1 flex gap-2 sm:gap-3 px-3 sm:px-4 pb-3 sm:pb-4 min-h-0 min-w-0">
    <div className={cn('flex-1 min-w-0 min-h-0 bg-background rounded-2xl border flex flex-col overflow-hidden', mobileTab === 'original' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 px-4 py-2.5 border-b bg-muted/40"><span className="text-xs font-semibold">{t('playground.originalImage') || '原始图片'}</span></div>
      <div className="flex-1 min-h-0 min-w-0 flex flex-col">
        {fileInfo && <ImageBBoxEditor readOnly imageSrc={imageUrl} boxes={visibleBoxes} onBoxesChange={() => {}} getTypeConfig={getVisionTypeConfig} availableTypes={visionTypes.map(vt => ({ id: vt.id, name: vt.name, color: '#6366F1' }))} defaultType={visionTypes[0]?.id || 'CUSTOM'} />}
      </div>
    </div>
    <div className={cn('flex-1 min-w-0 min-h-0 bg-background rounded-2xl border flex flex-col overflow-hidden', mobileTab === 'redacted' ? '' : 'hidden', 'md:flex')}>
      <div className="flex-shrink-0 px-4 py-2.5 border-b bg-muted/40"><span className="text-xs font-semibold">{t('playground.redactedResult') || '脱敏结果'}</span></div>
      <div className="flex-1 min-h-0 min-w-0 flex items-center justify-center bg-muted/20 overflow-hidden">
        {fileInfo && <img src={redactedImageUrl || `/api/v1/files/${fileInfo.file_id}/download?redacted=true`} alt="redacted" className="max-w-full max-h-full w-auto h-auto object-contain select-none block" />}
      </div>
    </div>
    <MappingColumn entityMap={entityMap} origToTypeId={origToTypeId} scrollToMatch={scrollToMatch} className="md:w-52 md:flex-shrink-0 w-full" mobileTab={mobileTab} versionHistory={versionHistory} versionHistoryOpen={versionHistoryOpen} setVersionHistoryOpen={setVersionHistoryOpen} />
  </div>
);
