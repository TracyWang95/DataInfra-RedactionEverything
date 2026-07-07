// Copyright 2026 DataInfra-RedactionEverything Contributors

import { startTransition, useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { authFetch } from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import { ACCEPTED_UPLOAD_FILE_TYPES } from '@/utils/fileUploadAccept';
import { safeJson, runVisionDetectionPages } from '../utils';
import type {
  FileInfo,
  Entity,
  BoundingBox,
  Stage,
  UploadResponse,
  ParseResponse,
  NerResponse,
} from '../types';

const PLAYGROUND_MAX_FILE_SIZE = 50 * 1024 * 1024;

async function responseErrorMessage(res: Response, fallbackKey: string) {
  try {
    const data = await safeJson<{ detail?: unknown; message?: unknown; error?: unknown }>(res);
    const detail = data.detail ?? data.message ?? data.error;
    if (typeof detail === 'string' && detail.trim()) return detail;
  } catch {
    // Keep the localized fallback when the response body is not JSON.
  }
  return t(fallbackKey);
}

export interface PendingFile {
  fileId: string;
  fileType: string;
  isScanned: boolean;
  pageCount: number;
  content: string;
}

export interface UsePlaygroundFileOptions {
  /** Ref to latest selectedOcrHasTypes for use in async callbacks */
  latestOcrHasTypesRef: React.RefObject<string[]>;
  /** Ref to latest selectedVisualFeatureTypes for use in async callbacks */
  latestVisualFeatureTypesRef: React.RefObject<string[]>;
  /** Ref to latest selectedTypes for use in async callbacks */
  latestSelectedTypesRef: React.RefObject<string[]>;
  /** Reset entity history */
  resetEntityHistory: () => void;
  /** Reset image history */
  resetImageHistory: () => void;
  /** Set entities from recognition result */
  setEntities: React.Dispatch<React.SetStateAction<Entity[]>>;
  /** Set bounding boxes from recognition result */
  setBoundingBoxes: React.Dispatch<React.SetStateAction<BoundingBox[]>>;
  /** Return a user-facing reason when automatic recognition should not run yet */
  getRecognitionBlocker?: (file: PendingFile) => string | null;
}

export function usePlaygroundFile(options: UsePlaygroundFileOptions) {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [stage, setStage] = useState<Stage>('upload');
  const [fileInfo, setFileInfo] = useState<FileInfo | null>(null);
  const [content, setContent] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [uploadIssue, setUploadIssue] = useState<string | null>(null);
  const [recognitionIssue, setRecognitionIssue] = useState<string | null>(null);

  const [pendingFile, setPendingFile] = useState<PendingFile | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const isImageMode = !!fileInfo && (fileInfo.file_type === 'image' || !!fileInfo.is_scanned);

  // --- Cleanup abort on unmount ---
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const cancelProcessing = useCallback((notify = true) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setPendingFile(null);
    setIsLoading(false);
    setLoadingMessage('');
    setRecognitionIssue(null);
    if (notify) {
      showToast(t('playground.cancelled'), 'info');
    }
  }, []);

  const rejectionMessage = useCallback((rejection: FileRejection): string => {
    const firstError = rejection.errors[0];
    if (firstError?.code === 'file-too-large') {
      return t('playground.upload.rejectTooLarge')
        .replace('{filename}', rejection.file.name)
        .replace('{max}', '50 MB');
    }
    if (firstError?.code === 'file-invalid-type') {
      return t('playground.upload.rejectInvalidType').replace('{filename}', rejection.file.name);
    }
    if (firstError?.code === 'too-many-files') {
      return t('playground.upload.rejectTooMany');
    }
    return firstError?.message || t('playground.upload.rejectGeneric');
  }, []);

  const onDropRejected = useCallback(
    (rejections: FileRejection[]) => {
      const message = rejections[0]
        ? rejectionMessage(rejections[0])
        : t('playground.upload.rejectGeneric');
      setUploadIssue(message);
      showToast(message, 'error');
    },
    [rejectionMessage],
  );

  // --- File upload ---
  const handleFileDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    setIsLoading(true);
    setStage('upload');
    setUploadIssue(null);
    setRecognitionIssue(null);

    const opts = optionsRef.current;
    try {
      setLoadingMessage(t('playground.uploading'));
      const formData = new FormData();
      formData.append('file', file);
      formData.append('upload_source', 'playground');

      const uploadRes = await authFetch('/api/v1/files/upload', {
        method: 'POST',
        body: formData,
        signal,
      });
      if (signal.aborted) return;
      if (!uploadRes.ok) {
        throw new Error(await responseErrorMessage(uploadRes, 'playground.uploadFailed'));
      }
      const uploadData = await safeJson<UploadResponse>(uploadRes);
      if (signal.aborted) return;

      setLoadingMessage(t('playground.parsing'));
      const parseRes = await authFetch(`/api/v1/files/${uploadData.file_id}/parse`, { signal });
      if (signal.aborted) return;
      if (!parseRes.ok) {
        throw new Error(await responseErrorMessage(parseRes, 'playground.parseFailed'));
      }
      const parseData = await safeJson<ParseResponse>(parseRes);
      if (signal.aborted) return;

      const isScanned = parseData.is_scanned || false;
      const pageCount = Math.max(1, Number(parseData.page_count || 1));
      const parsedFileType = parseData.file_type || uploadData.file_type;
      const parsedContent = parseData.content || '';
      const parsedPages = Array.isArray(parseData.pages) ? parseData.pages : undefined;

      setFileInfo({
        file_id: uploadData.file_id,
        filename: uploadData.filename,
        file_size: uploadData.file_size,
        file_type: parsedFileType,
        is_scanned: isScanned,
        page_count: pageCount,
        pages: parsedPages,
      });
      setContent(parsedContent);
      opts.setBoundingBoxes([]);
      opts.resetImageHistory();
      opts.setEntities([]);

      setPendingFile({
        fileId: uploadData.file_id,
        fileType: parsedFileType,
        isScanned,
        pageCount,
        content: parsedContent,
      });
    } catch (err) {
      if (signal.aborted) return;
      showToast(localizeErrorMessage(err, 'playground.processFailed'), 'error');
      setIsLoading(false);
      setLoadingMessage('');
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    }
  }, []);

  // --- Auto-recognition after upload ---
  useEffect(() => {
    if (!pendingFile) return;
    const { fileId, fileType, isScanned, pageCount, content: parsedContent } = pendingFile;
    setPendingFile(null);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    const opts = optionsRef.current;

    const blocker = opts.getRecognitionBlocker?.(pendingFile) ?? null;
    if (blocker) {
      setRecognitionIssue(blocker);
      setStage('preview');
      setIsLoading(false);
      setLoadingMessage('');
      showToast(blocker, 'info');
      return;
    }

    const doRecognition = async () => {
      try {
        setRecognitionIssue(null);
        const isImage = fileType === 'image' || isScanned;
        if (isImage) {
          const ocrTypes = opts.latestOcrHasTypesRef.current;
          const visualFeatureTypes = opts.latestVisualFeatureTypesRef.current;
          if (ocrTypes.length === 0 && visualFeatureTypes.length === 0) {
            opts.setBoundingBoxes([]);
            opts.resetImageHistory();
            setStage('preview');
            return;
          }
          const vLabel =
            ocrTypes.length > 0 && visualFeatureTypes.length > 0
              ? t('playground.loading.visionHybrid')
              : ocrTypes.length > 0
                ? t('playground.loading.visionOcr')
                : visualFeatureTypes.length > 0
                  ? t('playground.loading.visionImage')
                  : t('playground.loading.vision');
          setLoadingMessage(vLabel);

          opts.setBoundingBoxes([]);
          opts.resetImageHistory();
          const totalPages = Math.max(1, pageCount);
          const { totalBoxes } = await runVisionDetectionPages({
            fileId,
            ocrHasTypes: ocrTypes,
            visualFeatureTypes,
            totalPages,
            signal,
            label: vLabel,
            setLoadingMessage,
            onPageComplete: ({ pageBoxes }) => {
              startTransition(() => {
                opts.setBoundingBoxes((prev) => [...prev, ...pageBoxes]);
              });
            },
          });
          if (signal.aborted) return;
          showToast(
            t('playground.toast.detectedRegions').replace('{count}', String(totalBoxes)),
            'success',
          );
        } else if (parsedContent) {
          setLoadingMessage(t('playground.loading.text'));
          const nerRes = await authFetch(`/api/v1/files/${fileId}/ner/hybrid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_type_ids: opts.latestSelectedTypesRef.current }),
            signal,
          });
          if (signal.aborted) return;

          if (!nerRes.ok) {
            throw new Error(t('playground.recognizeFailed'));
          }

          const nerData = await safeJson<NerResponse>(nerRes);
          const entitiesWithSource = (nerData.entities || []).map(
            (e: Record<string, unknown>, idx: number) =>
              ({
                ...e,
                id: e.id || `entity_${idx}`,
                selected: true,
                source: e.source || 'llm',
              }) as Entity,
          );
          opts.setEntities(entitiesWithSource);
          opts.resetEntityHistory();
          showToast(
            t('playground.toast.detectedEntities').replace(
              '{count}',
              String(entitiesWithSource.length),
            ),
            'success',
          );
      }
      if (signal.aborted) return;
      setStage('preview');
    } catch (err) {
      if (signal.aborted) return;
      const message = localizeErrorMessage(err, 'playground.recognizeFailed');
      setRecognitionIssue(message);
      setStage('preview');
      showToast(message, 'error');
    } finally {
      if (!signal.aborted) {
        setIsLoading(false);
        setLoadingMessage('');
        }
      }
    };

    doRecognition();
  }, [pendingFile]);

  // --- Dropzone ---
  const dropzone = useDropzone({
    onDrop: handleFileDrop,
    onDropRejected,
    accept: ACCEPTED_UPLOAD_FILE_TYPES,
    maxSize: PLAYGROUND_MAX_FILE_SIZE,
    maxFiles: 1,
    disabled: isLoading,
    noClick: true,
  });

  return {
    stage,
    setStage,
    fileInfo,
    setFileInfo,
    content,
    setContent,
    isLoading,
    setIsLoading,
    loadingMessage,
    setLoadingMessage,
    cancelProcessing,
    uploadIssue,
    recognitionIssue,
    setRecognitionIssue,
    isImageMode,
    dropzone,
  };
}
