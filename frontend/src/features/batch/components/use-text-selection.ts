// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type React from 'react';
import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { getSelectionOffsets, clampPopoverInCanvas } from '@/utils/domSelection';
import type { ReviewEntity, TextEntityType } from '../types';

interface UseTextSelectionOptions {
  reviewTextContent: string;
  reviewTextContentRef: React.RefObject<HTMLDivElement | null>;
  reviewTextScrollRef: React.RefObject<HTMLDivElement | null>;
  cardRef: React.RefObject<HTMLDivElement | null>;
  textTypes: TextEntityType[];
  reviewFileReadOnly: boolean;
  applyReviewEntities: (updater: ReviewEntity[] | ((prev: ReviewEntity[]) => ReviewEntity[])) => void;
}

export function useTextSelection({
  reviewTextContent,
  reviewTextContentRef,
  reviewTextScrollRef,
  cardRef,
  textTypes,
  reviewFileReadOnly,
  applyReviewEntities,
}: UseTextSelectionOptions) {
  const [selectedText, setSelectedText] = useState<{ text: string; start: number; end: number } | null>(null);
  const [selectionPos, setSelectionPos] = useState<{ left: number; top: number } | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const selectionRangeRef = useRef<Range | null>(null);

  const clearTextSelection = useCallback(() => {
    setSelectedText(null);
    setSelectionPos(null);
    selectionRangeRef.current = null;
  }, []);

  const handleTextSelect = useCallback(() => {
    if (reviewFileReadOnly) return;

    const selection = window.getSelection();
    if (!selection || !reviewTextContentRef.current) {
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
    if (!reviewTextContentRef.current.contains(range.commonAncestorContainer)) {
      clearTextSelection();
      return;
    }

    const offsets = getSelectionOffsets(range, reviewTextContentRef.current);
    const start = offsets?.start ?? reviewTextContent.indexOf(text);
    const end = offsets?.end ?? (start + text.length);
    if (start < 0 || end < 0) {
      clearTextSelection();
      return;
    }

    try {
      selectionRangeRef.current = range.cloneRange();
    } catch {
      clearTextSelection();
      return;
    }

    if (!selectedTypeId) {
      const fallbackType = textTypes[0]?.id;
      if (fallbackType) setSelectedTypeId(fallbackType);
    }

    setSelectionPos(null);
    setSelectedText({ text, start, end });
  }, [clearTextSelection, reviewFileReadOnly, reviewTextContent, reviewTextContentRef, selectedText, selectedTypeId, selectionPos, textTypes]);

  // Position the popover after selectedText changes
  useLayoutEffect(() => {
    if (!selectedText) {
      selectionRangeRef.current = null;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing position with DOM layout
      setSelectionPos(null);
      return;
    }

    const card = cardRef.current;
    if (!card) return;

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

      const cardRect = card.getBoundingClientRect();
      const clamped = clampPopoverInCanvas(rect, cardRect, 240, 240);
      setSelectionPos({ left: clamped.left - cardRect.left, top: clamped.top - cardRect.top });
    };

    update();

    const scrollEl = reviewTextScrollRef.current;
    window.addEventListener('resize', update);
    scrollEl?.addEventListener('scroll', update, { passive: true });
    return () => {
      window.removeEventListener('resize', update);
      scrollEl?.removeEventListener('scroll', update);
    };
  }, [selectedText, reviewTextScrollRef, cardRef]);

  const addManualAnnotation = useCallback(() => {
    if (!selectedText || !selectedTypeId) return;
    const newEntity: ReviewEntity = {
      id: `manual_${Date.now()}`,
      text: selectedText.text,
      type: selectedTypeId,
      start: selectedText.start,
      end: selectedText.end,
      selected: true,
      source: 'manual',
      page: 0,
      confidence: 1,
    };
    applyReviewEntities(prev => [...prev, newEntity]);
    clearTextSelection();
    window.getSelection()?.removeAllRanges();
  }, [selectedText, selectedTypeId, applyReviewEntities, clearTextSelection]);

  return {
    selectedText,
    selectionPos,
    selectedTypeId,
    setSelectedTypeId,
    clearTextSelection,
    handleTextSelect,
    addManualAnnotation,
  };
}
