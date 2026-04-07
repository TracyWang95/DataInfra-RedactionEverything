// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { useState, useCallback, useEffect, useRef } from 'react';
import { useUndoRedo } from '@/hooks/useUndoRedo';
import {
  authenticatedBlobUrl,
  revokeObjectUrl,
} from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { localizeErrorMessage } from '@/utils/localizeError';
import { runVisionDetection } from '../utils';
import type { FileInfo, BoundingBox, VisionTypeConfig } from '../types';

export interface UsePlaygroundImageOptions {
  fileInfo: FileInfo | null;
}

export function usePlaygroundImage(options: UsePlaygroundImageOptions) {
  const { fileInfo } = options;

  const [boundingBoxes, setBoundingBoxes] = useState<BoundingBox[]>([]);
  const [imageUrl, setImageUrl] = useState('');
  const [redactedImageUrl, setRedactedImageUrl] = useState('');
  const imageHistory = useUndoRedo<BoundingBox[]>();

  const imageObjectUrlRef = useRef<string | null>(null);
  const redactedImageObjectUrlRef = useRef<string | null>(null);
  const popoutChannelRef = useRef<BroadcastChannel | null>(null);
  const popoutTimerRef = useRef<number | null>(null);

  const visibleBoxes = boundingBoxes;

  // --- Cleanup on unmount ---
  useEffect(() => {
    return () => {
      if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
      popoutChannelRef.current?.close();
      revokeObjectUrl(imageObjectUrlRef.current);
      revokeObjectUrl(redactedImageObjectUrlRef.current);
    };
  }, []);

  // --- Image URL resolution ---
  const imageUrlRaw = fileInfo ? `/api/v1/files/${fileInfo.file_id}/download` : '';
  useEffect(() => {
    let cancelled = false;
    if (!imageUrlRaw) {
      revokeObjectUrl(imageObjectUrlRef.current);
      imageObjectUrlRef.current = null;
      setImageUrl('');
      return;
    }
    authenticatedBlobUrl(imageUrlRaw)
      .then((url) => {
        if (cancelled) {
          revokeObjectUrl(url);
          return;
        }
        revokeObjectUrl(imageObjectUrlRef.current);
        imageObjectUrlRef.current = url;
        setImageUrl(url);
      })
      .catch(() => {
        if (cancelled) return;
        revokeObjectUrl(imageObjectUrlRef.current);
        imageObjectUrlRef.current = null;
        setImageUrl(imageUrlRaw);
      });
    return () => {
      cancelled = true;
    };
  }, [imageUrlRaw]);

  // --- Redacted image URL resolution ---
  useEffect(() => {
    let cancelled = false;
    if (!fileInfo) {
      revokeObjectUrl(redactedImageObjectUrlRef.current);
      redactedImageObjectUrlRef.current = null;
      setRedactedImageUrl('');
      return;
    }
    const raw = `/api/v1/files/${fileInfo.file_id}/download?redacted=true`;
    authenticatedBlobUrl(raw)
      .then((url) => {
        if (cancelled) {
          revokeObjectUrl(url);
          return;
        }
        revokeObjectUrl(redactedImageObjectUrlRef.current);
        redactedImageObjectUrlRef.current = url;
        setRedactedImageUrl(url);
      })
      .catch(() => {
        if (cancelled) return;
        revokeObjectUrl(redactedImageObjectUrlRef.current);
        redactedImageObjectUrlRef.current = null;
        setRedactedImageUrl(raw);
      });
    return () => {
      cancelled = true;
    };
  }, [fileInfo]);

  // --- Box operations ---
  const toggleBox = useCallback((id: string) => {
    setBoundingBoxes(prev => prev.map(b => b.id === id ? { ...b, selected: !b.selected } : b));
  }, []);

  const selectAllBoxes = useCallback((allSelectedVisionTypes: string[]) => {
    setBoundingBoxes(prev => prev.map(b => ({
      ...b,
      selected: allSelectedVisionTypes.includes(b.type),
    })));
  }, []);

  const deselectAllBoxes = useCallback(() => {
    setBoundingBoxes(prev => prev.map(b => ({ ...b, selected: false })));
  }, []);

  const mergeVisibleBoxes = useCallback((nextBoxes: BoundingBox[], prevBoxes: BoundingBox[] = []) => {
    const ids = new Set([...nextBoxes, ...prevBoxes].map(b => b.id));
    const otherBoxes = boundingBoxes.filter(b => !ids.has(b.id));
    return [...otherBoxes, ...nextBoxes];
  }, [boundingBoxes]);

  // --- Re-run vision recognition ---
  const visionAbortRef = useRef<AbortController | null>(null);

  // Abort vision on unmount
  useEffect(() => () => { visionAbortRef.current?.abort(); }, []);

  const handleRerunNerImage = useCallback(async (
    fileId: string,
    ocrHasTypes: string[],
    hasImageTypes: string[],
    setIsLoading: (v: boolean) => void,
    setLoadingMessage: (v: string) => void,
  ) => {
    // Abort any in-flight vision request before starting a new one
    visionAbortRef.current?.abort();
    const controller = new AbortController();
    visionAbortRef.current = controller;

    const o = ocrHasTypes.length > 0;
    const g = hasImageTypes.length > 0;
    setIsLoading(true);
    setLoadingMessage(
      o && g ? '重新识别中（OCR+HaS 与 HaS Image 并行）...'
        : o ? '重新识别中（OCR+HaS）...'
          : g ? '重新识别中（HaS Image）...'
            : '重新识别中...',
    );
    try {
      const result = await runVisionDetection(fileId, ocrHasTypes, hasImageTypes, controller.signal);
      if (controller.signal.aborted) return;
      setBoundingBoxes(result.boxes);
      imageHistory.reset();
      showToast(`重新识别完成：${result.boxes.length} 个区域`, 'success');
    } catch (err) {
      if (controller.signal.aborted) return;
      showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false);
        setLoadingMessage('');
      }
    }
  }, [imageHistory]);

  // --- Popout support ---
  const openPopout = useCallback((
    visionTypes: VisionTypeConfig[],
  ) => {
    popoutChannelRef.current?.close();
    const ch = new BroadcastChannel('playground-image-popout');
    popoutChannelRef.current = ch;

    const sendInit = () => {
      ch.postMessage({
        type: 'init',
        imageUrl,
        boxes: boundingBoxes,
        visionTypes: visionTypes.map(vt => ({ id: vt.id, name: vt.name, color: '#6366F1' })),
        defaultType: visionTypes[0]?.id || 'CUSTOM',
      });
    };

    ch.onmessage = (e: MessageEvent) => {
      const d = e.data;
      if (d?.type === 'popout-ready') sendInit();
      if (d?.type === 'boxes-sync') setBoundingBoxes(d.boxes);
      if (d?.type === 'boxes-commit') {
        const prevAll = mergeVisibleBoxes(d.prevBoxes, d.nextBoxes);
        const nextAll = mergeVisibleBoxes(d.nextBoxes, d.prevBoxes);
        imageHistory.save(prevAll);
        setBoundingBoxes(nextAll);
      }
    };

    const w = window.open('/playground/image-editor', '_blank', 'width=1200,height=900,scrollbars=yes,resizable=yes');
    if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
    popoutTimerRef.current = window.setInterval(() => {
      if (w && w.closed) {
        if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
        popoutTimerRef.current = null;
        ch.close();
        popoutChannelRef.current = null;
      }
    }, 1000);
  }, [imageUrl, boundingBoxes, mergeVisibleBoxes, imageHistory]);

  return {
    boundingBoxes,
    setBoundingBoxes,
    visibleBoxes,
    imageUrl,
    redactedImageUrl,
    imageHistory,
    toggleBox,
    selectAllBoxes,
    deselectAllBoxes,
    mergeVisibleBoxes,
    handleRerunNerImage,
    openPopout,
  };
}
