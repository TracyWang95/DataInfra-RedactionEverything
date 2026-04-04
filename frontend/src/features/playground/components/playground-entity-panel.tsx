/**
 * Playground entity panel: entity list, selection, redaction controls.
 */
import { type FC, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { t } from '@/i18n';
import { getEntityTypeName, getEntityGroup, ENTITY_GROUPS } from '@/config/entityTypes';
import { getModePreview, computeEntityStats } from '../utils';
import type { Entity, BoundingBox } from '../types';

export interface PlaygroundEntityPanelProps {
  isImageMode: boolean;
  isLoading: boolean;
  entities: Entity[];
  visibleBoxes: BoundingBox[];
  selectedCount: number;
  replacementMode: 'structured' | 'smart' | 'mask';
  setReplacementMode: (mode: 'structured' | 'smart' | 'mask') => void;
  clearPlaygroundTextPresetTracking: () => void;
  onRerunNer: () => void;
  onRedact: () => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  onToggleBox: (id: string) => void;
  onEntityClick: (entity: Entity, event: React.MouseEvent) => void;
  onRemoveEntity: (id: string) => void;
}

export const PlaygroundEntityPanel: FC<PlaygroundEntityPanelProps> = ({
  isImageMode, isLoading, entities, visibleBoxes, selectedCount,
  replacementMode, setReplacementMode, clearPlaygroundTextPresetTracking,
  onRerunNer, onRedact, onSelectAll, onDeselectAll, onToggleBox,
  onEntityClick, onRemoveEntity,
}) => {
  const stats = useMemo(() => computeEntityStats(entities), [entities]);

  return (
    <div className="w-full min-w-0 max-w-full lg:max-w-[320px] lg:w-[300px] flex-shrink-0 flex flex-col gap-2 min-h-0 self-stretch overflow-y-auto overflow-x-hidden pr-1" data-testid="playground-entity-panel">
      {/* Re-run button */}
      <Card>
        <CardContent className="p-3 flex flex-col gap-2">
          <Button onClick={onRerunNer} disabled={isLoading} className="w-full" data-testid="playground-rerun-btn">
            {isLoading ? t('playground.recognizing') || '识别中...' : t('playground.reRecognize') || '重新识别'}
          </Button>
          <p className="text-[10px] text-muted-foreground leading-snug">
            {t('playground.rerunHint') || '类型与预设请在「识别项配置」或上传页选择；此处仅重新跑识别。'}
          </p>
        </CardContent>
      </Card>

      {/* Stats */}
      <Card>
        <CardHeader className="p-4 pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">{t('playground.results') || '识别结果'}</CardTitle>
            <span className="text-xs text-muted-foreground font-medium tabular-nums">
              {selectedCount}/{isImageMode ? visibleBoxes.length : entities.length}
            </span>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-0 space-y-3">
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" className="flex-1" onClick={onSelectAll} data-testid="playground-select-all">
              {t('playground.selectAll') || '全选'}
            </Button>
            <Button variant="outline" size="sm" className="flex-1" onClick={onDeselectAll} data-testid="playground-deselect-all">
              {t('playground.deselect') || '取消'}
            </Button>
          </div>

          {/* Replacement mode (text only) */}
          {!isImageMode && <ReplacementModeSelector
            entities={entities}
            mode={replacementMode}
            onModeChange={(m) => { clearPlaygroundTextPresetTracking(); setReplacementMode(m); }}
          />}

          {/* Type distribution */}
          {!isImageMode && Object.keys(stats).length > 0 && (
            <div className="space-y-2">
              {ENTITY_GROUPS.map(group => {
                const gs = Object.entries(stats).filter(([tid]) => group.types.some(gt => gt.id === tid));
                if (gs.length === 0) return null;
                const total = gs.reduce((s, [, c]) => s + c.total, 0);
                const selected = gs.reduce((s, [, c]) => s + c.selected, 0);
                return (
                  <div key={group.id} className="rounded-lg overflow-hidden border">
                    <div className="flex items-center justify-between px-2.5 py-1.5 bg-muted border-b">
                      <span className="text-[10px] font-semibold">{group.label}</span>
                      <span className="text-[10px] text-muted-foreground tabular-nums">{selected}/{total}</span>
                    </div>
                    <div className="px-2.5 py-1.5 space-y-0.5 bg-background">
                      {gs.map(([tid, cnt]) => (
                        <div key={tid} className="flex items-center justify-between text-[10px]">
                          <span className="text-muted-foreground">{getEntityTypeName(tid)}</span>
                          <span className="tabular-nums">{cnt.selected}/{cnt.total}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Entity / box list */}
      <Card className="flex-1 overflow-hidden flex flex-col min-h-0">
        <div className="px-4 py-2.5 border-b bg-muted/40 flex items-center justify-between">
          <span className="text-sm font-semibold">{isImageMode ? t('playground.regionList') || '区域列表' : t('playground.results') || '识别结果'}</span>
          <span className="text-xs text-muted-foreground">{t('playground.clickToEdit') || '点击可编辑/移除'}</span>
        </div>
        <ScrollArea className="flex-1">
          {isImageMode ? (
            <BoxList boxes={visibleBoxes} onToggle={onToggleBox} />
          ) : (
            <EntityList entities={entities} onClick={onEntityClick} onRemove={onRemoveEntity} />
          )}
        </ScrollArea>
      </Card>

      {/* Redact button */}
      <Button
        onClick={onRedact}
        disabled={selectedCount === 0 || isLoading}
        className={cn('py-3 text-sm font-semibold', selectedCount === 0 && 'opacity-50')}
        data-testid="playground-redact-btn"
      >
        {isLoading ? t('playground.processing') || '处理中...' : `${t('playground.startRedact') || '开始脱敏'} (${selectedCount})`}
      </Button>
    </div>
  );
};

/* --- Private sub-components --- */

const ReplacementModeSelector: FC<{
  entities: Entity[];
  mode: 'structured' | 'smart' | 'mask';
  onModeChange: (m: 'structured' | 'smart' | 'mask') => void;
}> = ({ entities, mode, onModeChange }) => {
  const sampleEntity = entities.find(e => e.text && e.text.length > 0);
  const modes: { value: 'structured' | 'smart' | 'mask'; label: string; badge?: string }[] = [
    { value: 'structured', label: '结构化语义标签', badge: '推荐' },
    { value: 'smart', label: '智能替换' },
    { value: 'mask', label: '掩码替换' },
  ];
  return (
    <div>
      <label className="block text-[10px] text-muted-foreground mb-1.5 font-medium">{t('playground.redactMode') || '脱敏方式'}</label>
      <div className="space-y-1.5">
        {modes.map(m => (
          <label
            key={m.value}
            className={cn(
              'flex flex-col px-3 py-2 rounded-lg border cursor-pointer transition-colors',
              mode === m.value ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/30',
            )}
          >
            <div className="flex items-center gap-2">
              <input type="radio" name="replacementMode" value={m.value} checked={mode === m.value} onChange={() => onModeChange(m.value)} className="accent-primary" />
              <span className="text-sm font-medium">{m.label}</span>
              {m.badge && <Badge variant="default" className="text-[10px] px-1.5 py-0">{m.badge}</Badge>}
            </div>
            <span className="text-[10px] text-muted-foreground mt-0.5 font-mono ml-6">{getModePreview(m.value, sampleEntity)}</span>
          </label>
        ))}
      </div>
    </div>
  );
};

const BoxList: FC<{ boxes: BoundingBox[]; onToggle: (id: string) => void }> = ({ boxes, onToggle }) => {
  if (boxes.length === 0) return <p className="p-4 text-center text-sm text-muted-foreground">{t('playground.noResults') || '暂无识别结果'}</p>;
  return (
    <>
      {boxes.map(box => {
        const group = getEntityGroup(box.type);
        return (
          <div key={box.id} className="px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b transition-all hover:bg-accent/50" onClick={() => onToggle(box.id)} data-testid={`playground-box-${box.id}`}>
            <Checkbox checked={box.selected} onCheckedChange={() => onToggle(box.id)} className="h-3.5 w-3.5" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-1">
                <Badge variant="secondary" className="text-[10px]">{group?.label} · {getEntityTypeName(box.type)}</Badge>
                <Badge variant="outline" className="text-[10px]">{box.source === 'ocr_has' ? 'OCR' : box.source === 'has_image' ? '图像' : '手动'}</Badge>
              </div>
              <p className="text-sm truncate">{box.text || '图像区域'}</p>
            </div>
          </div>
        );
      })}
    </>
  );
};

const EntityList: FC<{
  entities: Entity[];
  onClick: (e: Entity, ev: React.MouseEvent) => void;
  onRemove: (id: string) => void;
}> = ({ entities, onClick, onRemove }) => {
  if (entities.length === 0) return <p className="p-4 text-center text-sm text-muted-foreground">{t('playground.noResults') || '暂无识别结果'}</p>;
  return (
    <>
      {ENTITY_GROUPS.map(group => {
        const ge = entities.filter(e => group.types.some(gt => gt.id === e.type));
        if (ge.length === 0) return null;
        return (
          <div key={group.id}>
            <div className="px-3 py-2 flex items-center justify-between sticky top-0 z-10 bg-muted border-b">
              <span className="text-xs font-semibold">{group.label}</span>
              <span className="text-[10px] text-muted-foreground tabular-nums">{ge.length}</span>
            </div>
            {ge.map(entity => (
              <div key={entity.id} className="px-3 py-2.5 flex items-center gap-2 cursor-pointer border-b border-border/30 transition-all hover:bg-accent/50" onClick={(ev) => onClick(entity, ev)} data-testid={`playground-entity-${entity.id}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Badge variant="secondary" className="text-[10px]">{getEntityTypeName(entity.type)}</Badge>
                    <span className="text-[10px] text-muted-foreground">{entity.source === 'regex' ? '正则' : entity.source === 'manual' ? '手动' : 'AI'}</span>
                  </div>
                  <p className="text-sm truncate">{entity.text}</p>
                </div>
                <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 text-muted-foreground hover:text-destructive" onClick={ev => { ev.stopPropagation(); onRemove(entity.id); }} aria-label={t('playground.removeAnnotation') || '移除此标注'}>
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                </Button>
              </div>
            ))}
          </div>
        );
      })}
    </>
  );
};
