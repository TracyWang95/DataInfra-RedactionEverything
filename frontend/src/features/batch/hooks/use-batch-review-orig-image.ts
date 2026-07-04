// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useEffect, useRef } from 'react';
import { fileApi, authenticatedBlobUrl } from '@/services/api';
import { authFetch } from '@/services/api-client';
import type { ReviewDataDeps } from './use-batch-review-data';

const IMAGE_BLOB_REVOKE_DELAY_MS = 30_000;

// Cap for the per-page base64 preview cache below so it cannot grow unbounded.
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

function revokeImageBlobUrlLater(url: string) {
  if (!url.startsWith('blob:')) return;
  window.setTimeout(() => URL.revokeObjectURL(url), IMAGE_BLOB_REVOKE_DELAY_MS);
}

interface PreviewImageResponse {
  image_base64?: string;
}

function toDataImageUrl(imageBase64: string | undefined): string {
  if (!imageBase64) return '';
  return imageBase64.startsWith('data:') ? imageBase64 : `data:image/png;base64,${imageBase64}`;
}

type ReviewOrigImageDeps = Pick<
  ReviewDataDeps,
  'reviewFile' | 'reviewCurrentPage' | 'reviewTotalPages' | 'setReviewOrigImageBlobUrl'
>;

export function useReviewOrigImage(deps: ReviewOrigImageDeps): void {
  const { reviewFile, reviewCurrentPage, reviewTotalPages, setReviewOrigImageBlobUrl } = deps;

  // Per-page cached scanned-PDF preview image to eliminate blank-flash on page
  // switch. Key = `${file_id}:${page}`. Cleared when the active file changes.
  const pageImageCacheRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    pageImageCacheRef.current.clear();
  }, [reviewFile?.file_id]);

  useEffect(() => {
    let cancelled = false;
    let currentBlobUrl = '';

    if (!reviewFile || !reviewFile.isImageMode) {
      setReviewOrigImageBlobUrl('');
      return;
    }

    const rawFileType = String(reviewFile.file_type ?? '').toLowerCase();
    const isScannedPdf = rawFileType === 'pdf_scanned';
    const rawDownloadUrl = fileApi.getDownloadUrl(reviewFile.file_id, false);

    const loadFromRawDownload = () => {
      authenticatedBlobUrl(rawDownloadUrl)
        .then((blobUrl) => {
          if (!cancelled) {
            currentBlobUrl = blobUrl;
            setReviewOrigImageBlobUrl(blobUrl);
          } else if (blobUrl.startsWith('blob:')) {
            URL.revokeObjectURL(blobUrl);
          }
        })
        .catch(() => {
          if (!cancelled) setReviewOrigImageBlobUrl(rawDownloadUrl);
        });
    };

    if (isScannedPdf) {
      const cacheKey = `${reviewFile.file_id}:${reviewCurrentPage}`;
      const cached = pageImageCacheRef.current.get(cacheKey);
      const prefetch = (page: number) => {
        if (page < 1 || page > reviewTotalPages) return;
        const key = `${reviewFile.file_id}:${page}`;
        if (pageImageCacheRef.current.has(key)) return;
        authFetch(`/api/v1/redaction/${reviewFile.file_id}/preview-image?page=${page}`, {
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
            if (!res.ok) return;
            const data = (await res.json()) as PreviewImageResponse;
            const url = toDataImageUrl(data.image_base64);
            if (url) setCacheWithLimit(pageImageCacheRef.current, key, url);
          })
          .catch(() => {
            /* silent */
          });
      };
      const scheduleNeighbors = () => {
        const defer =
          (window as unknown as { requestIdleCallback?: (cb: () => void) => number })
            .requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
        defer(() => prefetch(reviewCurrentPage - 1));
        defer(() => prefetch(reviewCurrentPage + 1));
      };

      if (cached) {
        setReviewOrigImageBlobUrl(cached);
        scheduleNeighbors();
      } else {
        authFetch(
          `/api/v1/redaction/${reviewFile.file_id}/preview-image?page=${reviewCurrentPage}`,
          {
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
          },
        )
          .then(async (res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = (await res.json()) as PreviewImageResponse;
            const imageUrl = toDataImageUrl(data.image_base64);
            if (!imageUrl) throw new Error('Missing image_base64');
            if (!cancelled) {
              setCacheWithLimit(pageImageCacheRef.current, cacheKey, imageUrl);
              setReviewOrigImageBlobUrl(imageUrl);
              scheduleNeighbors();
            }
          })
          .catch(() => {
            // Scanned PDF download URL can't render in <img>; keep previous image
          });
      }
    } else {
      loadFromRawDownload();
    }

    return () => {
      cancelled = true;
      revokeImageBlobUrlLater(currentBlobUrl);
    };
  }, [reviewFile, reviewCurrentPage, reviewTotalPages, setReviewOrigImageBlobUrl]);
}
