// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useCallback, useEffect, useState } from 'react';
import { authenticatedBlobUrl, revokeObjectUrl } from '@/services/api-client';
import { t } from '@/i18n';
import { fileApi, redactionApi } from '@/services/api';
import { localizeErrorMessage } from '@/utils/localizeError';
import type { CompareData, FileListItem } from '@/types';

export type HistoryPreviewItem = {
  id: string;
  label: string;
  value: string;
  meta: string;
};

export function previewMimeForRow(row: FileListItem): string {
  const ft = String(row.file_type);
  if (ft === 'pdf' || ft === 'pdf_scanned') return 'application/pdf';
  const name = row.original_filename.toLowerCase();
  if (name.endsWith('.png')) return 'image/png';
  if (name.endsWith('.webp')) return 'image/webp';
  if (name.endsWith('.gif')) return 'image/gif';
  if (name.endsWith('.bmp')) return 'image/bmp';
  return 'image/jpeg';
}

export function isBinaryPreviewRow(row: FileListItem | null): boolean {
  if (!row) return false;
  const ft = String(row.file_type);
  return ft === 'image' || ft === 'pdf' || ft === 'pdf_scanned';
}

function normalizeHistoryPreviewItems(
  fileInfo: Record<string, unknown> | null,
): HistoryPreviewItem[] {
  if (!fileInfo) return [];
  const items: HistoryPreviewItem[] = [];
  const entities = Array.isArray(fileInfo.entities) ? fileInfo.entities : [];
  const rawBoxes = fileInfo.bounding_boxes;
  const boxes = Array.isArray(rawBoxes)
    ? rawBoxes
    : rawBoxes && typeof rawBoxes === 'object'
      ? Object.values(rawBoxes).flatMap((v) => (Array.isArray(v) ? v : []))
      : [];

  for (const entity of entities) {
    if (!entity || typeof entity !== 'object') continue;
    const entry = entity as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'TEXT';
    const text =
      typeof entry.text === 'string' && entry.text.trim()
        ? entry.text.trim()
        : t('history.unnamedContent');
    items.push({
      id: String(entry.id ?? `entity-${items.length}`),
      label: type,
      value: text,
      meta: t('history.previewItemText'),
    });
  }

  for (const box of boxes) {
    if (!box || typeof box !== 'object') continue;
    const entry = box as Record<string, unknown>;
    if (entry.selected === false) continue;
    const type = typeof entry.type === 'string' && entry.type.trim() ? entry.type.trim() : 'IMAGE';
    const text =
      typeof entry.text === 'string' && entry.text.trim()
        ? entry.text.trim()
        : t('history.previewImageRegion');
    const page = typeof entry.page === 'number' ? entry.page : 1;
    items.push({
      id: String(entry.id ?? `box-${items.length}`),
      label: type,
      value: text,
      meta: t('history.previewItemPage').replace('{page}', String(page)),
    });
  }
  return items;
}

export async function blobUrlFromFileDownload(
  fileId: string,
  redacted: boolean,
  mime: string,
): Promise<string> {
  const url = fileApi.getDownloadUrl(fileId, redacted);
  return authenticatedBlobUrl(url, mime);
}

export function useHistoryCompare() {
  /* Compare modal state */
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareTarget, setCompareTarget] = useState<FileListItem | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareErr, setCompareErr] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<CompareData | null>(null);
  const [compareBlobUrls, setCompareBlobUrls] = useState<{
    original: string;
    redacted: string;
  } | null>(null);
  const [compareTab, setCompareTab] = useState<'preview' | 'text' | 'changes'>('preview');
  const [comparePreviewItems, setComparePreviewItems] = useState<HistoryPreviewItem[]>([]);
  const [comparePage, setComparePage] = useState(1);
  const [compareTotalPages, setCompareTotalPages] = useState(1);

  /* Compare helpers */

  const revokeCompareBlobs = useCallback(() => {
    setCompareBlobUrls((prev) => {
      if (prev) {
        revokeObjectUrl(prev.original);
        revokeObjectUrl(prev.redacted);
      }
      return null;
    });
  }, []);

  const closeCompareModal = useCallback(() => {
    revokeCompareBlobs();
    setCompareOpen(false);
    setCompareTarget(null);
    setCompareData(null);
    setCompareErr(null);
    setCompareLoading(false);
    setCompareTab('preview');
    setComparePreviewItems([]);
  }, [revokeCompareBlobs]);

  const isPdfRow = useCallback((row: FileListItem) => {
    const ft = String(row.file_type ?? '').toLowerCase();
    return ft === 'pdf' || ft === 'pdf_scanned';
  }, []);

  // TIFF/BMP can't render in <img>; the /page-image endpoint serves a PNG render.
  const needsServerPngPreview = useCallback((row: FileListItem) => {
    return /\.(?:tif|tiff|bmp)$/i.test(String(row.original_filename ?? ''));
  }, []);

  const fetchPageImages = useCallback(async (fileId: string, page: number) => {
    const base = `/files/${encodeURIComponent(fileId)}/page-image?page=${page}`;
    const [origRes, redRes] = await Promise.all([
      authenticatedBlobUrl(`/api/v1${base}&redacted=false`),
      authenticatedBlobUrl(`/api/v1${base}&redacted=true`),
    ]);
    return { original: origRes, redacted: redRes };
  }, []);

  const openCompareModal = useCallback(
    async (row: FileListItem) => {
      revokeCompareBlobs();
      setCompareOpen(true);
      setCompareTarget(row);
      setCompareData(null);
      setCompareErr(null);
      setCompareLoading(true);
      setComparePreviewItems([]);
      setComparePage(1);
      const useBinaryPreview = isBinaryPreviewRow(row);
      setCompareTab(useBinaryPreview ? 'preview' : 'text');
      try {
        const [data, fileInfo] = await Promise.all([
          redactionApi.getComparison(row.file_id),
          fileApi.getInfo(row.file_id).catch(() => null),
        ]);
        setCompareData(data);
        setComparePreviewItems(
          normalizeHistoryPreviewItems(fileInfo as Record<string, unknown> | null),
        );
        const pageCount = Math.max(
          1,
          Number((fileInfo as Record<string, unknown> | null)?.page_count || 1),
        );
        setCompareTotalPages(pageCount);

        if (useBinaryPreview) {
          if (isPdfRow(row) || needsServerPngPreview(row)) {
            // PDF pages, or TIFF/BMP single images: server renders a browser-safe
            // PNG via /page-image (raw <img src> can't decode those formats).
            const urls = await fetchPageImages(row.file_id, 1);
            setCompareBlobUrls(urls);
          } else {
            // Browser-renderable single image: download full file as blob
            const mime = previewMimeForRow(row);
            const [original, redacted] = await Promise.all([
              blobUrlFromFileDownload(row.file_id, false, mime),
              blobUrlFromFileDownload(row.file_id, true, mime),
            ]);
            setCompareBlobUrls({ original, redacted });
          }
        }
      } catch (e) {
        setCompareErr(localizeErrorMessage(e, 'history.compareFailed'));
      } finally {
        setCompareLoading(false);
      }
    },
    [revokeCompareBlobs, isPdfRow, needsServerPngPreview, fetchPageImages],
  );

  // When user changes compare page (PDF pagination), re-fetch page images.
  useEffect(() => {
    if (!compareOpen || !compareTarget || !isPdfRow(compareTarget) || comparePage < 1) return;
    let cancelled = false;
    fetchPageImages(compareTarget.file_id, comparePage)
      .then((urls) => {
        if (cancelled) {
          revokeObjectUrl(urls.original);
          revokeObjectUrl(urls.redacted);
          return;
        }
        setCompareBlobUrls((prev) => {
          if (prev) {
            revokeObjectUrl(prev.original);
            revokeObjectUrl(prev.redacted);
          }
          return urls;
        });
      })
      .catch(() => {
        /* keep previous */
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only refetch when page changes
  }, [comparePage]);

  useEffect(() => {
    if (!compareOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeCompareModal();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [compareOpen, closeCompareModal]);

  useEffect(() => () => revokeCompareBlobs(), [revokeCompareBlobs]);

  return {
    compareOpen,
    compareTarget,
    compareLoading,
    compareErr,
    compareData,
    compareBlobUrls,
    compareTab,
    setCompareTab,
    comparePreviewItems,
    comparePage,
    setComparePage,
    compareTotalPages,
    openCompareModal,
    closeCompareModal,
  };
}
