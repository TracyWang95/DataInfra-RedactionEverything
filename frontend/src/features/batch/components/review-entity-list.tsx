// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type React from 'react';
import { useCallback, useMemo, useRef } from 'react';
import { useT } from '@/i18n';
import { ENTITY_HIGHLIGHT_DURATION_MS } from '@/constants/timing';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import type { ReviewEntity, TextEntityType } from '../types';

interface ReviewEntityListProps {
  reviewEntities: ReviewEntity[];
  selectedReviewEntityCount: number;
  textTypes: TextEntityType[];
  applyReviewEntities: (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => void;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  previewScrollRef: React.RefObject<HTMLDivElement | null>;
}

export function ReviewEntityList({
  reviewEntities,
  selectedReviewEntityCount,
  textTypes,
  applyReviewEntities,
  reviewTextContentRef,
  reviewTextScrollRef,
  previewScrollRef,
}: ReviewEntityListProps) {
  const t = useT();

  const entityGroups = useMemo(() => {
    const map = new Map<string, { type: string; text: string; ids: string[]; selected: number; total: number }>();
    reviewEntities.forEach(e => {
      const key = `${e.type}::${e.text}`;
      const g = map.get(key) || { type: e.type, text: e.text, ids: [], selected: 0, total: 0 };
      g.ids.push(e.id);
      g.total++;
      if (e.selected !== false) g.selected++;
      map.set(key, g);
    });
    return Array.from(map.values());
  }, [reviewEntities]);

  const scrollIndexRef = useRef<Map<string, number>>(new Map());

  const scrollToEntityGroup = useCallback((ids: string[]) => {
    if (!ids.length) return;
    const key = ids.join(',');
    const prevIdx = scrollIndexRef.current.get(key) ?? -1;
    const nextIdx = (prevIdx + 1) % ids.length;
    scrollIndexRef.current.set(key, nextIdx);

    const targetId = ids[nextIdx];
    const el = reviewTextContentRef.current?.querySelector(`[data-review-entity-id="${CSS.escape(targetId)}"]`) as HTMLElement | null;
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-primary');
      setTimeout(() => el.classList.remove('ring-2', 'ring-primary'), ENTITY_HIGHLIGHT_DURATION_MS);

      const origScroll = reviewTextScrollRef.current;
      const prevScroll = previewScrollRef.current;
      if (origScroll && prevScroll) {
        const ratio = origScroll.scrollHeight > origScroll.clientHeight
          ? origScroll.scrollTop / (origScroll.scrollHeight - origScroll.clientHeight)
          : 0;
        prevScroll.scrollTop = ratio * (prevScroll.scrollHeight - prevScroll.clientHeight);
      }
    }
  }, [reviewTextContentRef, reviewTextScrollRef, previewScrollRef]);

  return (
    <Card className="min-h-0 flex flex-col overflow-hidden">
      <div className="shrink-0 px-3 py-2 border-b flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold">{t('batchWizard.step4.entityList')}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground tabular-nums">
            {selectedReviewEntityCount}/{reviewEntities.length}
          </span>
          <Button
            variant="outline" size="sm" className="text-xs h-6"
            onClick={() => applyReviewEntities(prev => prev.map(e => ({ ...e, selected: true })))}
            data-testid="select-all-entities"
          >
            {t('batchWizard.step4.selectAll')}
          </Button>
          <Button
            variant="outline" size="sm" className="text-xs h-6"
            onClick={() => applyReviewEntities(prev => prev.map(e => ({ ...e, selected: false })))}
            data-testid="deselect-all-entities"
          >
            {t('batchWizard.step4.deselectAll')}
          </Button>
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
        {entityGroups.map(g => {
          const risk = getEntityRiskConfig(g.type);
          const allSelected = g.selected === g.total;
          const noneSelected = g.selected === 0;
          return (
            <div
              key={`${g.type}::${g.text}`}
              className="rounded-xl border shadow-sm px-3 py-2 cursor-pointer transition-colors hover:bg-accent/30"
              style={{ backgroundColor: noneSelected ? undefined : risk.bgColor, borderLeft: `3px solid ${risk.color}` }}
              onClick={() => scrollToEntityGroup(g.ids)}
            >
              <div className="flex items-start gap-2">
                <Checkbox
                  checked={allSelected ? true : noneSelected ? false : 'indeterminate'}
                  onCheckedChange={() => {
                    const newSelected = !allSelected;
                    applyReviewEntities(prev =>
                      prev.map(e => g.ids.includes(e.id) ? { ...e, selected: newSelected } : e),
                    );
                  }}
                  className="mt-0.5"
                  data-testid={`entity-group-toggle-${g.type}-${g.text}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium" style={{ color: risk.textColor }}>
                      {textTypes.find(tt => tt.id === g.type)?.name ?? getEntityTypeName(g.type)}
                    </span>
                    {g.total > 1 && (
                      <Badge variant="secondary" className="rounded-full px-1.5 py-0 text-[10px] leading-4">
                        &times;{g.total}
                      </Badge>
                    )}
                  </div>
                  <span className="block text-xs break-all mt-0.5" style={{ color: risk.textColor }}>
                    {g.text}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
        {reviewEntities.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">
            {t('batchWizard.step4.noEntities')}
          </p>
        )}
      </div>
    </Card>
  );
}
