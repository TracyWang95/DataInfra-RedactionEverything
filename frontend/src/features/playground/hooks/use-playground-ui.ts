// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import {
  type MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { showToast } from '@/components/Toast';
import { useT } from '@/i18n';
import { clampPopoverInCanvas } from '../utils';
import { getSelectionOffsets } from '@/utils/domSelection';
import type { Entity, EntityTypeConfig } from '../types';

export interface UsePlaygroundUIOptions {
  isImageMode: boolean;
  content: string;
  entities: Entity[];
  entityTypes: EntityTypeConfig[];
  selectedTypes: string[];
  applyEntities: (next: Entity[]) => void;
  getTypeConfig: (typeId: string) => { name: string; color: string };
}

export function usePlaygroundUI(options: UsePlaygroundUIOptions) {
  const {
    isImageMode,
    content,
    entities,
    entityTypes,
    selectedTypes,
    applyEntities,
    getTypeConfig,
  } = options;

  const t = useT();

  // --- Selection state ---
  const [selectedText, setSelectedText] = useState<{
    text: string;
    start: number;
    end: number;
  } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState('');
  const [selectedOverlapIds, setSelectedOverlapIds] = useState<string[]>([]);

  // --- Clicked entity state ---
  const [clickedEntity, setClickedEntity] = useState<Entity | null>(null);
  const [entityPopupPos, setEntityPopupPos] = useState<{ left: number; top: number } | null>(null);

  // --- Refs ---
  const contentRef = useRef<HTMLDivElement>(null);
  const textScrollRef = useRef<HTMLDivElement>(null);
  const selectionRangeRef = useRef<Range | null>(null);

  // --- Default type selection ---
  useEffect(() => {
    if (!selectedTypeId && entityTypes.length > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- initializing default from loaded entity types
      setSelectedTypeId(entityTypes[0].id);
    }
  }, [entityTypes, selectedTypeId]);

  // --- Clear text selection ---
  const clearTextSelection = useCallback(() => {
    selectionRangeRef.current = null;
    setSelectedText(null);
    setSelectionPos(null);
    setSelectedOverlapIds([]);
  }, []);

  // --- Handle text select ---
  const handleTextSelect = useCallback(() => {
    if (isImageMode || clickedEntity) return;

    const selection = window.getSelection();
    if (!selection || !contentRef.current) {
      clearTextSelection();
      return;
    }

    if (selection.isCollapsed) {
      if (!selectedText || !selectionPos) clearTextSelection();
      return;
    }

    const text = selection.toString().trim();
    if (!text || text.length < 2) {
      clearTextSelection();
      return;
    }

    const range = selection.getRangeAt(0);
    if (!contentRef.current.contains(range.commonAncestorContainer)) {
      clearTextSelection();
      return;
    }

    const offsets = getSelectionOffsets(range, contentRef.current);
    const start = offsets?.start ?? content.indexOf(text);
    const end = offsets?.end ?? start + text.length;
    if (start < 0 || end < 0) {
      clearTextSelection();
      return;
    }

    const overlaps = entities.filter(
      (entity) =>
        (entity.start <= start && entity.end > start) || (entity.start < end && entity.end >= end),
    );

    try {
      selectionRangeRef.current = range.cloneRange();
    } catch {
      clearTextSelection();
      return;
    }

    setSelectedOverlapIds(overlaps.map((entity) => entity.id));
    if (overlaps.length > 0) {
      setSelectedTypeId(overlaps[0].type);
    } else if (!selectedTypeId) {
      const fallbackType =
        entityTypes.find((entityType) => selectedTypes.includes(entityType.id))?.id ||
        entityTypes[0]?.id;
      if (fallbackType) setSelectedTypeId(fallbackType);
    }

    setSelectionPos(null);
    setSelectedText({ text, start, end });
  }, [
    clearTextSelection,
    clickedEntity,
    content,
    entities,
    entityTypes,
    isImageMode,
    selectedText,
    selectedTypeId,
    selectedTypes,
    selectionPos,
  ]);

  // --- Selection popover position tracking ---
  useLayoutEffect(() => {
    if (!selectedText) {
      selectionRangeRef.current = null;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing position with DOM layout
      setSelectionPos(null);
      return;
    }

    const root = contentRef.current;
    if (!root) return;

    const update = () => {
      const range = selectionRangeRef.current;
      if (!range || range.collapsed) {
        setSelectionPos(null);
        return;
      }

      let rect: DOMRect;
      try {
        rect = range.getBoundingClientRect();
      } catch {
        setSelectionPos(null);
        return;
      }

      if (rect.width === 0 && rect.height === 0) return;
      setSelectionPos(clampPopoverInCanvas(rect, root.getBoundingClientRect(), 320, 280));
    };

    update();

    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [selectedText]);

  // --- Entity popup position tracking ---
  useLayoutEffect(() => {
    if (!clickedEntity) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing position with DOM layout
      setEntityPopupPos(null);
      return;
    }

    const root = contentRef.current;
    if (!root) return;

    const update = () => {
      let element: HTMLElement | null = null;
      try {
        element = root.querySelector(`[data-entity-id="${CSS.escape(clickedEntity.id)}"]`);
      } catch {
        element = null;
      }

      if (!element) return;
      setEntityPopupPos(
        clampPopoverInCanvas(
          element.getBoundingClientRect(),
          root.getBoundingClientRect(),
          240,
          120,
        ),
      );
    };

    update();

    const scrollEl = textScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [clickedEntity]);

  // --- Manual entity add ---
  const addManualEntity = useCallback(
    (typeId: string) => {
      if (!selectedText) return;

      const newEntity: Entity = {
        id: `manual_${Date.now()}`,
        text: selectedText.text,
        type: typeId,
        start: selectedText.start,
        end: selectedText.end,
        selected: true,
        source: 'manual',
      };

      const nextEntities = entities
        .filter((entity) => !selectedOverlapIds.includes(entity.id))
        .concat(newEntity)
        .sort((left, right) => left.start - right.start);

      applyEntities(nextEntities);
      showToast(
        selectedOverlapIds.length > 0
          ? t('playground.toast.updated')
          : t('playground.toast.added').replace('{name}', getTypeConfig(typeId).name),
        'success',
      );
      clearTextSelection();
      window.getSelection()?.removeAllRanges();
    },
    [
      applyEntities,
      clearTextSelection,
      entities,
      getTypeConfig,
      selectedOverlapIds,
      selectedText,
      t,
    ],
  );

  // --- Remove selected entities ---
  const removeSelectedEntities = useCallback(() => {
    if (selectedOverlapIds.length === 0) return;
    applyEntities(entities.filter((entity) => !selectedOverlapIds.includes(entity.id)));
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
    showToast(t('playground.toast.removed'), 'info');
  }, [applyEntities, clearTextSelection, entities, selectedOverlapIds, t]);

  // --- Handle entity click ---
  const handleEntityClick = useCallback(
    (entity: Entity, event: ReactMouseEvent) => {
      event.stopPropagation();
      clearTextSelection();
      setClickedEntity(entity);
      setSelectedTypeId(entity.type);
    },
    [clearTextSelection],
  );

  // --- Confirm remove entity ---
  const confirmRemoveEntity = useCallback(() => {
    if (clickedEntity) {
      applyEntities(entities.filter((entity) => entity.id !== clickedEntity.id));
      showToast(t('playground.toast.removed'), 'info');
    }
    setClickedEntity(null);
    setEntityPopupPos(null);
  }, [applyEntities, clickedEntity, entities, t]);

  return {
    // Selection state
    selectedText,
    selectionPos,
    selectedTypeId,
    setSelectedTypeId,
    selectedOverlapIds,
    // Clicked entity state
    clickedEntity,
    setClickedEntity,
    entityPopupPos,
    setEntityPopupPos,
    getTypeConfig,
    // Refs
    contentRef,
    textScrollRef,
    // Handlers
    clearTextSelection,
    handleTextSelect,
    addManualEntity,
    removeSelectedEntities,
    handleEntityClick,
    confirmRemoveEntity,
  };
}
