
import { useState, useCallback, useEffect, useRef } from 'react';
import { useDropzone } from 'react-dropzone';
import { authFetch } from '@/services/api-client';
import { showToast } from '@/components/Toast';
import { t } from '@/i18n';
import { localizeErrorMessage } from '@/utils/localizeError';
import { safeJson, runVisionDetection } from '../utils';
import type { FileInfo, Entity, BoundingBox, Stage } from '../types';

export interface PendingFile {
  fileId: string;
  fileType: string;
  isScanned: boolean;
  content: string;
}

export interface UsePlaygroundFileOptions {
  /** Ref to latest selectedOcrHasTypes for use in async callbacks */
  latestOcrHasTypesRef: React.RefObject<string[]>;
  /** Ref to latest selectedHasImageTypes for use in async callbacks */
  latestHasImageTypesRef: React.RefObject<string[]>;
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
}

export function usePlaygroundFile(options: UsePlaygroundFileOptions) {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [stage, setStage] = useState<Stage>('upload');
  const [fileInfo, setFileInfo] = useState<FileInfo | null>(null);
  const [content, setContent] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');

  const [pendingFile, setPendingFile] = useState<PendingFile | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const isImageMode = !!fileInfo && (fileInfo.file_type === 'image' || !!fileInfo.is_scanned);

  // --- Loading elapsed timer ---
  const [loadingElapsedSec, setLoadingElapsedSec] = useState(0);
  useEffect(() => {
    if (!isLoading) { setLoadingElapsedSec(0); return; }
    setLoadingElapsedSec(0);
    const id = window.setInterval(() => setLoadingElapsedSec(s => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [isLoading]);

  // --- Cleanup abort on unmount ---
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // --- File upload ---
  const handleFileDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const file = acceptedFiles[0];
    setIsLoading(true);

    const opts = optionsRef.current;
    try {
      setLoadingMessage(t('playground.uploading') || '正在上传文件...');
      const formData = new FormData();
      formData.append('file', file);
      formData.append('upload_source', 'playground');

      const uploadRes = await authFetch('/api/v1/files/upload', { method: 'POST', body: formData });
      if (!uploadRes.ok) throw new Error(t('playground.uploadFailed') || '文件上传失败');
      const uploadData = await safeJson(uploadRes);

      setLoadingMessage(t('playground.parsing') || '正在解析文件...');
      const parseRes = await authFetch(`/api/v1/files/${uploadData.file_id}/parse`);
      if (!parseRes.ok) throw new Error(t('playground.parseFailed') || '文件解析失败');
      const parseData = await safeJson(parseRes);

      const isScanned = parseData.is_scanned || false;
      const parsedContent = parseData.content || '';

      setFileInfo({
        file_id: uploadData.file_id,
        filename: uploadData.filename,
        file_size: uploadData.file_size,
        file_type: uploadData.file_type,
        is_scanned: isScanned,
      });
      setContent(parsedContent);
      opts.setBoundingBoxes([]);
      opts.resetImageHistory();
      opts.setEntities([]);

      setPendingFile({
        fileId: uploadData.file_id,
        fileType: uploadData.file_type,
        isScanned,
        content: parsedContent,
      });
    } catch (err) {
      showToast(localizeErrorMessage(err, 'playground.processFailed'), 'error');
      setIsLoading(false);
      setLoadingMessage('');
    }
  }, []);

  // --- Auto-recognition after upload ---
  useEffect(() => {
    if (!pendingFile) return;
    const { fileId, fileType, isScanned, content: parsedContent } = pendingFile;
    setPendingFile(null);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    const opts = optionsRef.current;

    const doRecognition = async () => {
      try {
        const isImage = fileType === 'image' || isScanned;
        if (isImage) {
          const ocrTypes = opts.latestOcrHasTypesRef.current;
          const hiTypes = opts.latestHasImageTypesRef.current;
          const vLabel = ocrTypes.length > 0 && hiTypes.length > 0
            ? '正在进行图像识别（OCR+HaS 与 HaS Image 并行）...'
            : ocrTypes.length > 0
              ? '正在进行图像识别（OCR+HaS）...'
              : hiTypes.length > 0
                ? '正在进行图像识别（HaS Image）...'
                : '正在进行图像识别...';
          setLoadingMessage(vLabel);

          const result = await runVisionDetection(fileId, ocrTypes, hiTypes);
          if (signal.aborted) return;

          opts.setBoundingBoxes(result.boxes);
          opts.resetImageHistory();
          showToast(`识别到 ${result.boxes.length} 个敏感区域`, 'success');
        } else if (parsedContent) {
          setLoadingMessage('AI正在识别敏感信息...');
          const nerRes = await authFetch(`/api/v1/files/${fileId}/ner/hybrid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ entity_type_ids: opts.latestSelectedTypesRef.current }),
            signal,
          });
          if (signal.aborted) return;

          if (nerRes.ok) {
            const nerData = await safeJson(nerRes);
            const entitiesWithSource = (nerData.entities || []).map(
              (e: Record<string, unknown>, idx: number) => ({
                ...e,
                id: e.id || `entity_${idx}`,
                selected: true,
                source: e.source || 'llm',
              }),
            );
            opts.setEntities(entitiesWithSource);
            opts.resetEntityHistory();
            showToast(`识别到 ${entitiesWithSource.length} 处敏感信息`, 'success');
          }
        }
        if (signal.aborted) return;
        setStage('preview');
      } catch (err) {
        if (signal.aborted) return;
        showToast(localizeErrorMessage(err, 'playground.recognizeFailed'), 'error');
      } finally {
        if (!signal.aborted) {
          setIsLoading(false);
          setLoadingMessage('');
        }
      }
    };

    doRecognition();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFile]);

  // --- Dropzone ---
  const dropzone = useDropzone({
    onDrop: handleFileDrop,
    accept: {
      'application/msword': ['.doc'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'application/pdf': ['.pdf'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
    },
    maxFiles: 1,
    disabled: isLoading,
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
    loadingElapsedSec,
    isImageMode,
    dropzone,
  };
}
