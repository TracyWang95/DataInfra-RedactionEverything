// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type React from 'react';
import { memo, useCallback, useId, useMemo, useRef } from 'react';
import { useT } from '@/i18n';
import { ENTITY_HIGHLIGHT_DURATION_MS } from '@/constants/timing';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { getEntityRiskConfig, getEntityTypeName } from '@/config/entityTypes';
import type { ReviewEntity, TextEntityType } from '../types';

export interface ReviewEntityOccurrenceGroup {
  type: string;
  text: string;
  entityIds: string[];
  occurrenceIds: string[];
  selected: number;
  total: number;
}

interface ReviewEntityListProps {
  reviewEntities: ReviewEntity[];
  selectedReviewEntityCount: number;
  displaySelectedCount?: number;
  displayTotalCount?: number;
  occurrenceGroups?: ReviewEntityOccurrenceGroup[];
  textTypes: TextEntityType[];
  applyReviewEntities: (
    updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[]),
  ) => void;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  previewScrollRef: React.RefObject<HTMLDivElement | null>;
}

interface EntityGroup {
  type: string;
  text: string;
  ids: string[];
  jumpIds: string[];
  idsKey: string;
  selected: number;
  total: number;
}

interface EntityGroupRowProps {
  group: EntityGroup;
  countId: string;
  typeName: string;
  t: ReturnType<typeof useT>;
  applyReviewEntities: ReviewEntityListProps['applyReviewEntities'];
  scrollToEntityGroup: (ids: string[]) => void;
}

function EntityGroupRowInner({
  group,
  countId,
  typeName,
  t,
  applyReviewEntities,
  scrollToEntityGroup,
}: EntityGroupRowProps) {
  const risk = getEntityRiskConfig(group.type);
  const allSelected = group.selected === group.total;
  const noneSelected = group.selected === 0;
  const groupLabel = useMemo(
    () =>
      t('batchWizard.step4.entityGroupLabel')
        .replace('{type}', typeName)
        .replace('{text}', group.text)
        .replace('{selected}', String(group.selected))
        .replace('{total}', String(group.total)),
    [group.selected, group.text, group.total, t, typeName],
  );
  const toggleLabel = useMemo(
    () =>
      t('batchWizard.step4.entityGroupToggleLabel')
        .replace('{type}', typeName)
        .replace('{text}', group.text)
        .replace('{selected}', String(group.selected))
        .replace('{total}', String(group.total)),
    [group.selected, group.text, group.total, t, typeName],
  );
  const cardStyle = useMemo<React.CSSProperties>(
    () => ({
      backgroundColor: noneSelected ? undefined : risk.bgColor,
      borderLeft: `3px solid ${risk.color}`,
    }),
    [noneSelected, risk.bgColor, risk.color],
  );
  const textStyle = useMemo<React.CSSProperties>(
    () => ({ color: risk.textColor }),
    [risk.textColor],
  );

  const handleJump = useCallback(() => {
    scrollToEntityGroup(group.jumpIds.length > 0 ? group.jumpIds : group.ids);
  }, [group.ids, group.jumpIds, scrollToEntityGroup]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      scrollToEntityGroup(group.jumpIds.length > 0 ? group.jumpIds : group.ids);
    },
    [group.ids, group.jumpIds, scrollToEntityGroup],
  );

  const handleToggle = useCallback(() => {
    if (group.ids.length === 0) return;
    const newSelected = !allSelected;
    const idSet = new Set(group.ids);
    applyReviewEntities((prev) =>
      prev.map((entity) => {
        if (!idSet.has(entity.id)) return entity;
        const currentlySelected = entity.selected !== false;
        return currentlySelected === newSelected ? entity : { ...entity, selected: newSelected };
      }),
    );
  }, [allSelected, applyReviewEntities, group.ids]);

  const stopCheckboxClick = useCallback((event: React.MouseEvent) => {
    event.stopPropagation();
  }, []);

  return (
    <div role="listitem">
      <div
        role="button"
        tabIndex={0}
        aria-label={groupLabel}
        aria-describedby={countId}
        className="cursor-pointer rounded-xl border px-3 py-2 shadow-sm transition-colors hover:bg-accent/30"
        style={cardStyle}
        onClick={handleJump}
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-start gap-2">
          <Checkbox
            checked={allSelected ? true : noneSelected ? false : 'indeterminate'}
            aria-label={toggleLabel}
            disabled={group.ids.length === 0}
            onClick={stopCheckboxClick}
            onCheckedChange={handleToggle}
            className="mt-0.5"
            data-testid={`entity-group-toggle-${group.type}-${group.text}`}
          />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-xs font-medium" style={textStyle}>
                {typeName}
              </span>
              {group.total > 1 && (
                <Badge
                  variant="secondary"
                  className="rounded-full px-1.5 py-0 text-[10px] leading-4"
                >
                  &times;{group.total}
                </Badge>
              )}
            </div>
            <span className="mt-0.5 block truncate text-xs" style={textStyle} title={group.text}>
              {group.text}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

const EntityGroupRow = memo(EntityGroupRowInner, (prev, next) => {
  const prevGroup = prev.group;
  const nextGroup = next.group;
  return (
    prev.countId === next.countId &&
    prev.typeName === next.typeName &&
    prev.t === next.t &&
    prev.applyReviewEntities === next.applyReviewEntities &&
    prev.scrollToEntityGroup === next.scrollToEntityGroup &&
    prevGroup.type === nextGroup.type &&
    prevGroup.text === nextGroup.text &&
    prevGroup.idsKey === nextGroup.idsKey &&
    prevGroup.selected === nextGroup.selected &&
    prevGroup.total === nextGroup.total
  );
});

function ReviewEntityListInner({
  reviewEntities,
  selectedReviewEntityCount,
  displaySelectedCount,
  displayTotalCount,
  occurrenceGroups,
  textTypes,
  applyReviewEntities,
  reviewTextContentRef,
  reviewTextScrollRef,
  previewScrollRef,
}: ReviewEntityListProps) {
  const t = useT();
  const headingId = useId();
  const countId = useId();

  const entityGroups = useMemo(() => {
    if (occurrenceGroups && occurrenceGroups.length > 0) {
      return occurrenceGroups.map((group) => {
        const ids = Array.from(new Set(group.entityIds));
        return {
          type: group.type,
          text: group.text,
          ids,
          jumpIds: group.occurrenceIds,
          idsKey: `${ids.join('\u001f')}::${group.occurrenceIds.join('\u001f')}`,
          selected: group.selected,
          total: group.total,
        };
      });
    }

    const map = new Map<string, EntityGroup>();
    reviewEntities.forEach((e) => {
      const key = `${e.type}::${e.text}`;
      const g = map.get(key) || {
        type: e.type,
        text: e.text,
        ids: [],
        jumpIds: [],
        idsKey: '',
        selected: 0,
        total: 0,
      };
      g.ids.push(e.id);
      g.total++;
      if (e.selected !== false) g.selected++;
      map.set(key, g);
    });
    return Array.from(map.values()).map((group) => ({
      ...group,
      jumpIds: group.ids,
      idsKey: group.ids.join('\u001f'),
    }));
  }, [occurrenceGroups, reviewEntities]);
  const textTypeNameById = useMemo(
    () => new Map(textTypes.map((textType) => [textType.id, textType.name])),
    [textTypes],
  );
  const hasEntities = entityGroups.length > 0;
  const hasToggleableEntities = reviewEntities.length > 0;
  const shownSelectedCount = displaySelectedCount ?? selectedReviewEntityCount;
  const shownTotalCount = displayTotalCount ?? reviewEntities.length;

  const scrollIndexRef = useRef<Map<string, number>>(new Map());

  const scrollToEntityGroup = useCallback(
    (ids: string[]) => {
      if (!ids.length) return;
      const key = ids.join(',');
      const prevIdx = scrollIndexRef.current.get(key) ?? -1;
      const nextIdx = (prevIdx + 1) % ids.length;
      scrollIndexRef.current.set(key, nextIdx);

      const targetId = ids[nextIdx];
      const el = reviewTextContentRef.current?.querySelector(
        `[data-review-occurrence-id="${CSS.escape(targetId)}"], [data-review-entity-id="${CSS.escape(targetId)}"]`,
      ) as HTMLElement | null;
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-2', 'ring-primary');
        setTimeout(
          () => el.classList.remove('ring-2', 'ring-primary'),
          ENTITY_HIGHLIGHT_DURATION_MS,
        );

        const origScroll = reviewTextScrollRef.current;
        const prevScroll = previewScrollRef.current;
        if (origScroll && prevScroll) {
          const ratio =
            origScroll.scrollHeight > origScroll.clientHeight
              ? origScroll.scrollTop / (origScroll.scrollHeight - origScroll.clientHeight)
              : 0;
          prevScroll.scrollTop = ratio * (prevScroll.scrollHeight - prevScroll.clientHeight);
        }
      }
    },
    [reviewTextContentRef, reviewTextScrollRef, previewScrollRef],
  );

  const selectAllEntities = useCallback(() => {
    applyReviewEntities((prev) =>
      prev.map((e) => (e.selected !== false ? e : { ...e, selected: true })),
    );
  }, [applyReviewEntities]);

  const deselectAllEntities = useCallback(() => {
    applyReviewEntities((prev) =>
      prev.map((e) => (e.selected === false ? e : { ...e, selected: false })),
    );
  }, [applyReviewEntities]);

  return (
    <Card
      className="page-surface border-border/70 shadow-[var(--shadow-sm)]"
      role="region"
      aria-labelledby={headingId}
      aria-describedby={countId}
    >
      <div className="flex shrink-0 flex-nowrap items-center justify-between gap-2 border-b px-3 py-2">
        <span id={headingId} className="truncate text-xs font-semibold">
          {t('batchWizard.step4.entityList')}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <span
            id={countId}
            className="text-xs text-muted-foreground tabular-nums"
            aria-live="polite"
            aria-atomic="true"
            aria-label={t('batchWizard.step4.entitySelectionSummary')
              .replace('{selected}', String(shownSelectedCount))
              .replace('{total}', String(shownTotalCount))}
          >
            {shownSelectedCount}/{shownTotalCount}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="h-6 whitespace-nowrap text-xs"
            disabled={!hasToggleableEntities || selectedReviewEntityCount === reviewEntities.length}
            onClick={selectAllEntities}
            data-testid="select-all-entities"
          >
            {t('batchWizard.step4.selectAll')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-6 whitespace-nowrap text-xs"
            disabled={!hasToggleableEntities || selectedReviewEntityCount === 0}
            onClick={deselectAllEntities}
            data-testid="deselect-all-entities"
          >
            {t('batchWizard.step4.deselectAll')}
          </Button>
        </div>
      </div>
      <div
        className="flex flex-1 flex-col gap-2 overflow-y-auto p-2"
        role="list"
        aria-label={t('batchWizard.step4.entityList')}
      >
        {entityGroups.map((group) => (
          <EntityGroupRow
            key={`${group.type}::${group.text}`}
            group={group}
            countId={countId}
            typeName={textTypeNameById.get(group.type) ?? getEntityTypeName(group.type)}
            t={t}
            applyReviewEntities={applyReviewEntities}
            scrollToEntityGroup={scrollToEntityGroup}
          />
        ))}
        {!hasEntities && (
          <div
            className="rounded-xl border border-dashed border-border bg-muted/20 px-3 py-6 text-center"
            data-testid="review-entity-empty"
          >
            <p className="text-sm font-medium text-foreground">
              {t('batchWizard.step4.noEntities')}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {t('batchWizard.step4.redactedPreview')} - {t('batchWizard.step4.noEntities')}
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

export const ReviewEntityList = memo(ReviewEntityListInner);
