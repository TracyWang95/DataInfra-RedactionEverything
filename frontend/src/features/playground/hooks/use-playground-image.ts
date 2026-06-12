// Copyright 2026 DataInfra-RedactionEverything Contributors

import { startTransition, useState, useCallback, useEffect, useRef } from 'react';
import { useUndoRedo } from '@/hooks/useUndoRedo';
import { authFetch, authenticatedBlobUrl, revokeObjectUrl } from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import { runVisionDetectionPages, safeJson } from '../utils';
import type { FileInfo, BoundingBox, VisionTypeConfig } from '../types';

export interface UsePlaygroundImageOptions {
  fileInfo: FileInfo | null;
  redactionVersion?: number;
  showRedactedPreview?: boolean;
}

interface PreviewImageResponse {
  image_base64?: string;
}

function asPngDataUrl(imageBase64: string | undefined): string {
  if (!imageBase64) return '';
  return imageBase64.startsWith('data:') ? imageBase64 : `data:image/png;base64,${imageBase64}`;
}

function isTiffFilename(filename: string | undefined): boolean {
  return /\.(?:tif|tiff)$/i.test(filename || '');
}

// Cap for the base64 page-image caches below. Without a cap the redacted
// cache (key includes version + box signature) grows unbounded.
const PAGE_IMAGE_CACHE_LIMIT = 24;

function setCacheWithLimit(cache: Map<string, string>, key: string, value: string): void {
  if (cache.has(key)) cache.delete(key);
  cache.set(key, value);
  while (cache.size > PAGE_IMAGE_CACHE_LIMIT) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
}

export function usePlaygroundImage(options: UsePlaygroundImageOptions) {
  const { fileInfo, redactionVersion = 0, showRedactedPreview } = options;

  const [boundingBoxes, setBoundingBoxes] = useState<BoundingBox[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [imageUrl, setImageUrl] = useState('');
  const [redactedImageUrl, setRedactedImageUrl] = useState('');
  const [redactedImageError, setRedactedImageError] = useState<string | null>(null);
  const imageHistory = useUndoRedo<BoundingBox[]>();

  const imageObjectUrlRef = useRef<string | null>(null);
  const redactedImageObjectUrlRef = useRef<string | null>(null);
  const popoutChannelRef = useRef<BroadcastChannel | null>(null);
  const popoutTimerRef = useRef<number | null>(null);
  const visionAbortRef = useRef<AbortController | null>(null);
  const currentPageRef = useRef(currentPage);
  const boundingBoxesRef = useRef<BoundingBox[]>([]);
  // Per-page cached original image (data URL). Switches pages instantly and
  // avoids the blank-flash while the POST /preview-image is in flight.
  const pageImageCacheRef = useRef<Map<string, string>>(new Map());
  const pageImageRequestRef = useRef<Map<string, Promise<string>>>(new Map());
  const redactedPageImageCacheRef = useRef<Map<string, string>>(new Map());
  const redactedPageImageRequestRef = useRef<Map<string, Promise<string>>>(new Map());

  const totalPages = Math.max(1, Number(fileInfo?.page_count || 1));
  const isScannedPdfMode =
    !!fileInfo &&
    (fileInfo.file_type === 'pdf_scanned' ||
      (fileInfo.file_type === 'pdf' && !!fileInfo.is_scanned));
  const isTiffImageMode =
    !!fileInfo && fileInfo.file_type === 'image' && isTiffFilename(fileInfo.filename);
  const needsBrowserSafeImagePreview = isScannedPdfMode || isTiffImageMode;
  const shouldLoadRedactedPreview = showRedactedPreview ?? redactionVersion > 0;
  const visibleBoxes = boundingBoxes.filter((box) => Number(box.page || 1) === currentPage);

  useEffect(() => {
    setCurrentPage(1);
    pageImageCacheRef.current.clear();
    pageImageRequestRef.current.clear();
    redactedPageImageCacheRef.current.clear();
    redactedPageImageRequestRef.current.clear();
  }, [fileInfo?.file_id]);

  // --- Image URL resolution ---
  const imageUrlRaw = fileInfo ? `/api/v1/files/${fileInfo.file_id}/download` : '';

  const loadOriginalPreviewPage = useCallback((fileId: string, page: number) => {
    const key = `${fileId}:${page}`;
    const cached = pageImageCacheRef.current.get(key);
    if (cached) return Promise.resolve(cached);

    const pending = pageImageRequestRef.current.get(key);
    if (pending) return pending;

    const request = authFetch(`/api/v1/redaction/${fileId}/preview-image?page=${page}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bounding_boxes: [],
        config: {
          replacement_mode: 'structured',
          entity_types: [],
          custom_replacements: {},
        },
      }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await safeJson<PreviewImageResponse>(res);
        const resolved = asPngDataUrl(data.image_base64);
        if (!resolved) throw new Error('Missing image_base64');
        setCacheWithLimit(pageImageCacheRef.current, key, resolved);
        return resolved;
      })
      .finally(() => {
        pageImageRequestRef.current.delete(key);
      });

    pageImageRequestRef.current.set(key, request);
    return request;
  }, []);

  const loadRedactedPreviewPage = useCallback(
    (
      fileId: string,
      page: number,
      selectedPageBoxes: BoundingBox[],
      version: number,
    ): Promise<string> => {
      const boxSignature = selectedPageBoxes
        .map((box) =>
          [
            box.id,
            box.type,
            box.x,
            box.y,
            box.width,
            box.height,
            box.selected === false ? '0' : '1',
          ].join(':'),
        )
        .join('|');
      const key = `${fileId}:${page}:${version}:${boxSignature}`;
      const cached = redactedPageImageCacheRef.current.get(key);
      if (cached) return Promise.resolve(cached);

      const pending = redactedPageImageRequestRef.current.get(key);
      if (pending) return pending;

      const request = authFetch(`/api/v1/redaction/${fileId}/preview-image?page=${page}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bounding_boxes: selectedPageBoxes,
          config: {
            replacement_mode: 'structured',
            entity_types: [],
            custom_replacements: {},
          },
        }),
      })
        .then(async (res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await safeJson<PreviewImageResponse>(res);
          const resolved = asPngDataUrl(data.image_base64);
          if (!resolved) throw new Error('Missing image_base64');
          setCacheWithLimit(redactedPageImageCacheRef.current, key, resolved);
          return resolved;
        })
        .finally(() => {
          redactedPageImageRequestRef.current.delete(key);
        });

      redactedPageImageRequestRef.current.set(key, request);
      return request;
    },
    [],
  );

  const prefetchPage = useCallback(
    (fileId: string, page: number) => {
      if (page < 1 || page > totalPages) return;
      const key = `${fileId}:${page}`;
      if (pageImageCacheRef.current.has(key)) return;
      if (pageImageRequestRef.current.has(key)) return;
      loadOriginalPreviewPage(fileId, page).catch(() => {
        /* silent prefetch failure */
      });
    },
    [loadOriginalPreviewPage, totalPages],
  );

  const scheduleNeighborPrefetch = useCallback(
    (fileId: string, page: number) => {
      // Defer to idle time so the active page's fetch/render isn't contended.
      const defer =
        (window as unknown as { requestIdleCallback?: (cb: () => void) => number })
          .requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
      defer(() => prefetchPage(fileId, page - 1));
      defer(() => prefetchPage(fileId, page + 1));
    },
    [prefetchPage],
  );

  useEffect(() => {
    setCurrentPage((prev) => Math.min(Math.max(1, prev), totalPages));
  }, [totalPages]);

  useEffect(() => {
    currentPageRef.current = currentPage;
  }, [currentPage]);

  useEffect(() => {
    boundingBoxesRef.current = boundingBoxes;
  }, [boundingBoxes]);

  // --- Cleanup on unmount ---
  useEffect(() => {
    return () => {
      if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
      popoutChannelRef.current?.close();
      visionAbortRef.current?.abort();
      revokeObjectUrl(imageObjectUrlRef.current);
      revokeObjectUrl(redactedImageObjectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!imageUrlRaw) {
      revokeObjectUrl(imageObjectUrlRef.current);
      imageObjectUrlRef.current = null;
      setImageUrl('');
      return;
    }

    if (needsBrowserSafeImagePreview && fileInfo) {
      const cacheKey = `${fileInfo.file_id}:${currentPage}`;
      const cached = pageImageCacheRef.current.get(cacheKey);
      if (cached) {
        revokeObjectUrl(imageObjectUrlRef.current);
        imageObjectUrlRef.current = null;
        setImageUrl(cached);
        // Kick off neighbor prefetch without blocking the UI.
        scheduleNeighborPrefetch(fileInfo.file_id, currentPage);
        return;
      }

      loadOriginalPreviewPage(fileInfo.file_id, currentPage)
        .then((resolved) => {
          if (cancelled) return;
          revokeObjectUrl(imageObjectUrlRef.current);
          imageObjectUrlRef.current = null;
          setImageUrl(resolved);
          scheduleNeighborPrefetch(fileInfo.file_id, currentPage);
        })
        .catch(() => {
          // PDF page renders and TIFF browser-safe previews are already the
          // fallback path. Keep the previous image instead of showing a broken
          // image icon when preview rendering fails.
        });
      return () => {
        cancelled = true;
      };
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
  }, [
    imageUrlRaw,
    needsBrowserSafeImagePreview,
    fileInfo,
    currentPage,
    scheduleNeighborPrefetch,
    loadOriginalPreviewPage,
  ]);

  // --- Redacted image URL resolution ---
  useEffect(() => {
    let cancelled = false;
    const isRawImageMode = fileInfo?.file_type === 'image';
    const isVisualResult = Boolean(fileInfo && (isScannedPdfMode || isRawImageMode));
    if (!fileInfo || !isVisualResult || !shouldLoadRedactedPreview) {
      revokeObjectUrl(redactedImageObjectUrlRef.current);
      redactedImageObjectUrlRef.current = null;
      setRedactedImageUrl('');
      setRedactedImageError(null);
      return;
    }

    if (needsBrowserSafeImagePreview) {
      const selectedPageBoxes = boundingBoxes
        .filter((box) => Number(box.page || 1) === currentPage && box.selected !== false)
        .map((box) => ({
          ...box,
          page: Number(box.page || currentPage),
        }));

      loadRedactedPreviewPage(fileInfo.file_id, currentPage, selectedPageBoxes, redactionVersion)
        .then((resolved) => {
          if (!cancelled) {
            setRedactedImageUrl(resolved);
            setRedactedImageError(null);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setRedactedImageUrl('');
            setRedactedImageError(t('playground.redactedPreviewFailed'));
          }
        });
      return () => {
        cancelled = true;
      };
    }

    if (redactionVersion <= 0) {
      revokeObjectUrl(redactedImageObjectUrlRef.current);
      redactedImageObjectUrlRef.current = null;
      setRedactedImageUrl('');
      setRedactedImageError(null);
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
        setRedactedImageError(null);
      })
      .catch(() => {
        if (cancelled) return;
        revokeObjectUrl(redactedImageObjectUrlRef.current);
        redactedImageObjectUrlRef.current = null;
        setRedactedImageUrl('');
        setRedactedImageError(t('playground.redactedPreviewFailed'));
      });
    return () => {
      cancelled = true;
    };
  }, [
    fileInfo,
    isScannedPdfMode,
    needsBrowserSafeImagePreview,
    boundingBoxes,
    currentPage,
    redactionVersion,
    shouldLoadRedactedPreview,
    loadRedactedPreviewPage,
  ]);

  // --- Box operations ---
  const toggleBox = useCallback((id: string) => {
    setBoundingBoxes((prev) =>
      prev.map((b) => (b.id === id ? { ...b, selected: !b.selected } : b)),
    );
  }, []);

  const selectAllBoxes = useCallback(
    (allSelectedVisionTypes: string[]) => {
      setBoundingBoxes((prev) =>
        prev.map((b) => ({
          ...b,
          selected:
            Number(b.page || 1) === currentPage
              ? allSelectedVisionTypes.includes(b.type)
              : b.selected,
        })),
      );
    },
    [currentPage],
  );

  const deselectAllBoxes = useCallback(() => {
    setBoundingBoxes((prev) =>
      prev.map((b) => ({
        ...b,
        selected: Number(b.page || 1) === currentPage ? false : b.selected,
      })),
    );
  }, [currentPage]);

  const mergeBoxesForPage = useCallback(
    (
      sourceBoxes: BoundingBox[],
      nextBoxes: BoundingBox[],
      prevBoxes: BoundingBox[] = [],
      page = currentPageRef.current,
    ) => {
      const normalizedNext = nextBoxes.map((box) => ({ ...box, page: Number(box.page || page) }));
      const normalizedPrev = prevBoxes.map((box) => ({ ...box, page: Number(box.page || page) }));
      const ids = new Set([...normalizedNext, ...normalizedPrev].map((b) => b.id));
      const otherBoxes = sourceBoxes.filter((b) => !ids.has(b.id));
      return [...otherBoxes, ...normalizedNext];
    },
    [],
  );

  const mergeVisibleBoxes = useCallback(
    (nextBoxes: BoundingBox[], prevBoxes: BoundingBox[] = []) =>
      mergeBoxesForPage(boundingBoxes, nextBoxes, prevBoxes, currentPage),
    [boundingBoxes, currentPage, mergeBoxesForPage],
  );

  const cancelRerunNerImage = useCallback(() => {
    visionAbortRef.current?.abort();
    visionAbortRef.current = null;
  }, []);

  // --- Re-run vision recognition ---
  const handleRerunNerImage = useCallback(
    async (
      fileId: string,
      ocrHasTypes: string[],
      visualFeatureTypes: string[],
      setIsLoading: (v: boolean) => void,
      setLoadingMessage: (v: string) => void,
    ) => {
      if (visionAbortRef.current) return;
      const controller = new AbortController();
      visionAbortRef.current = controller;
      const previousBoxes = boundingBoxesRef.current;

      setIsLoading(true);
      setLoadingMessage(t('playground.loading.vision'));
      try {
        const pages = Math.max(1, totalPages);
        const { boxes: nextBoxes, totalBoxes } = await runVisionDetectionPages({
          fileId,
          ocrHasTypes,
          visualFeatureTypes,
          totalPages: pages,
          signal: controller.signal,
          force: true,
          label: t('playground.loading.vision'),
          setLoadingMessage,
          onPageComplete: ({ page, pageBoxes }) => {
            startTransition(() => {
              setBoundingBoxes((prev) => [
                ...prev.filter((box) => Number(box.page || 1) !== page),
                ...pageBoxes,
              ]);
            });
          },
        });
        if (controller.signal.aborted) {
          setBoundingBoxes(previousBoxes);
          return;
        }
        setBoundingBoxes(nextBoxes);
        imageHistory.reset();
        showToast(
          t('playground.toast.detectedRegions').replace('{count}', String(totalBoxes)),
          'success',
        );
      } catch (err) {
        setBoundingBoxes(previousBoxes);
        if (controller.signal.aborted) return;
        showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
      } finally {
        if (visionAbortRef.current === controller) {
          visionAbortRef.current = null;
        }
        if (!controller.signal.aborted) {
          setIsLoading(false);
          setLoadingMessage('');
        }
      }
    },
    [imageHistory, totalPages],
  );

  // --- Popout support ---
  const openPopout = useCallback(
    (visionTypes: VisionTypeConfig[]) => {
      popoutChannelRef.current?.close();
      const ch = new BroadcastChannel('playground-image-popout');
      popoutChannelRef.current = ch;
      const popoutImageUrl = needsBrowserSafeImagePreview ? imageUrl : imageUrlRaw;

      const sendInit = () => {
        ch.postMessage({
          type: 'init',
          imageUrl: popoutImageUrl,
          rawImageUrl: popoutImageUrl,
          currentPage,
          totalPages,
          boxes: visibleBoxes,
          visionTypes: visionTypes.map((vt) => ({ id: vt.id, name: vt.name, color: '#6366F1' })),
        });
      };

      ch.onmessage = (event: MessageEvent) => {
        const data = event.data;
        if (data?.type === 'popout-ready') sendInit();
        if (data?.type === 'boxes-sync') {
          setBoundingBoxes((prev) => {
            const activePage = currentPageRef.current;
            const visiblePrev = prev.filter((box) => Number(box.page || 1) === activePage);
            return mergeBoxesForPage(prev, data.boxes ?? [], visiblePrev, activePage);
          });
        }
        if (data?.type === 'boxes-commit') {
          const activePage = currentPageRef.current;
          // Compute prev/next outside the setState updater so the updater stays
          // pure (StrictMode double-invokes updaters, which would double-push
          // onto the undo stack).
          const sourceBoxes = boundingBoxesRef.current;
          const prevAll = mergeBoxesForPage(
            sourceBoxes,
            data.prevBoxes ?? [],
            data.nextBoxes ?? [],
            activePage,
          );
          const nextAll = mergeBoxesForPage(
            sourceBoxes,
            data.nextBoxes ?? [],
            data.prevBoxes ?? [],
            activePage,
          );
          imageHistory.save(prevAll);
          setBoundingBoxes(nextAll);
        }
        if (data?.type === 'page-change') {
          const nextPage = Number(data.page || 1);
          setCurrentPage(Math.min(Math.max(1, nextPage), totalPages));
        }
      };

      const popup = window.open(
        '/playground/image-editor',
        '_blank',
        'width=1200,height=900,scrollbars=yes,resizable=yes',
      );
      if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
      popoutTimerRef.current = window.setInterval(() => {
        if (popup && popup.closed) {
          if (popoutTimerRef.current !== null) clearInterval(popoutTimerRef.current);
          popoutTimerRef.current = null;
          ch.close();
          popoutChannelRef.current = null;
        }
      }, 1000);
    },
    [
      needsBrowserSafeImagePreview,
      imageUrl,
      imageUrlRaw,
      visibleBoxes,
      currentPage,
      totalPages,
      mergeBoxesForPage,
      imageHistory,
    ],
  );

  useEffect(() => {
    const channel = popoutChannelRef.current;
    if (!channel) return;
    channel.postMessage({ type: 'boxes-update', boxes: visibleBoxes });
  }, [visibleBoxes]);

  useEffect(() => {
    const channel = popoutChannelRef.current;
    if (!channel) return;
    channel.postMessage({ type: 'page-update', currentPage, totalPages });
  }, [currentPage, totalPages]);

  useEffect(() => {
    const channel = popoutChannelRef.current;
    if (!channel) return;
    channel.postMessage({
      type: 'image-update',
      imageUrl: needsBrowserSafeImagePreview ? imageUrl : imageUrlRaw || imageUrl,
    });
  }, [imageUrlRaw, imageUrl, needsBrowserSafeImagePreview]);

  return {
    boundingBoxes,
    setBoundingBoxes,
    visibleBoxes,
    currentPage,
    setCurrentPage,
    totalPages,
    imageUrl,
    redactedImageUrl,
    redactedImageError,
    imageHistory,
    toggleBox,
    selectAllBoxes,
    deselectAllBoxes,
    mergeVisibleBoxes,
    handleRerunNerImage,
    cancelRerunNerImage,
    openPopout,
  };
}
