import React, { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { CloudArrowUpIcon, DocumentIcon, XMarkIcon } from '@heroicons/react/24/outline';
import clsx from 'clsx';
import { fileApi, nerApi, redactionApi } from '../../services/api';
import { useRedactionStore } from '../../hooks/useRedaction';

const ACCEPTED_FILES = {
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/pdf': ['.pdf'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/png': ['.png'],
};

export const FileUploader: React.FC = () => {
  const {
    setFileInfo,
    setContent,
    setEntities,
    setBoundingBoxes,
    setStage,
    setIsLoading,
    setLoadingMessage,
    setError,
  } = useRedactionStore();

  const [uploadedFile, setUploadedFile] = useState<File | null>(null);

  const processFile = useCallback(async (file: File) => {
    setError(null);
    setIsLoading(true);
    
    try {
      // 1. 上传文件
      setLoadingMessage('正在上传文件...');
      const fileInfo = await fileApi.upload(file);
      setFileInfo(fileInfo);

      // 2. 解析文件
      setLoadingMessage('正在解析文件内容...');
      const parseResult = await fileApi.parse(fileInfo.file_id);
      setContent(parseResult.content, parseResult.pages);

      // 更新文件信息
      setFileInfo({
        ...fileInfo,
        content: parseResult.content,
        pages: parseResult.pages,
        is_scanned: parseResult.is_scanned,
        page_count: parseResult.page_count,
      });

      // 3. 根据文件类型选择处理方式
      if (parseResult.is_scanned) {
        // 扫描件/图片：使用视觉识别
        setLoadingMessage('正在识别图片中的敏感信息...');
        const visionResult = await redactionApi.detectSensitiveRegions(fileInfo.file_id, 1);
        setBoundingBoxes(visionResult.bounding_boxes);
      } else {
        // 文本文件：使用 NER 识别
        setLoadingMessage('正在识别文本中的敏感信息...');
        const nerResult = await nerApi.extractEntities(fileInfo.file_id);
        setEntities(nerResult.entities);
      }

      // 4. 进入预览阶段
      setStage('preview');
    } catch (err) {
      setError(err instanceof Error ? err.message : '文件处理失败');
      console.error('File processing error:', err);
    } finally {
      setIsLoading(false);
      setLoadingMessage('');
    }
  }, [setFileInfo, setContent, setEntities, setBoundingBoxes, setStage, setIsLoading, setLoadingMessage, setError]);

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        const file = acceptedFiles[0];
        setUploadedFile(file);
        processFile(file);
      }
    },
    [processFile]
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: ACCEPTED_FILES,
    maxFiles: 1,
    maxSize: 50 * 1024 * 1024, // 50MB
  });

  const clearFile = () => {
    setUploadedFile(null);
    useRedactionStore.getState().reset();
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* 上传区域 */}
      <div
        {...getRootProps()}
        className={clsx(
          'dropzone cursor-pointer',
          isDragActive && 'active border-primary-500 bg-primary-50',
          isDragReject && 'border-red-500 bg-red-50'
        )}
      >
        <input {...getInputProps()} />
        
        <div className="flex flex-col items-center gap-4">
          <div className={clsx(
            'w-16 h-16 rounded-full flex items-center justify-center transition-colors',
            isDragActive ? 'bg-primary-100' : 'bg-surface-tertiary'
          )}>
            <CloudArrowUpIcon className={clsx(
              'w-8 h-8',
              isDragActive ? 'text-primary-600' : 'text-ink-subtle'
            )} />
          </div>
          
          <div>
            <p className="text-lg font-medium text-gray-700">
              {isDragActive ? '松开鼠标上传文件' : '拖拽文件到此处上传'}
            </p>
            <p className="text-sm text-ink-muted mt-1">
              或 <span className="text-primary-600 hover:underline">点击选择文件</span>
            </p>
          </div>
          
          <div className="flex flex-wrap justify-center gap-2 text-xs text-ink-subtle">
            <span className="px-2 py-1 bg-surface-tertiary rounded">.docx</span>
            <span className="px-2 py-1 bg-surface-tertiary rounded">.pdf</span>
            <span className="px-2 py-1 bg-surface-tertiary rounded">.jpg</span>
            <span className="px-2 py-1 bg-surface-tertiary rounded">.png</span>
          </div>
          
          <p className="text-xs text-ink-subtle">
            支持 Word 文档、PDF 文档、图片，最大 50MB
          </p>
        </div>
      </div>

      {/* 已选择的文件信息 */}
      {uploadedFile && (
        <div className="mt-4 p-4 bg-white rounded-lg border border-line flex items-center gap-3">
          <div className="w-10 h-10 bg-primary-100 rounded-lg flex items-center justify-center flex-shrink-0">
            <DocumentIcon className="w-5 h-5 text-primary-600" />
          </div>
          
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-ink truncate">
              {uploadedFile.name}
            </p>
            <p className="text-xs text-ink-muted">
              {(uploadedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
          
          <button
            onClick={(e) => {
              e.stopPropagation();
              clearFile();
            }}
            className="p-1 hover:bg-surface-tertiary rounded transition-colors"
          >
            <XMarkIcon className="w-5 h-5 text-ink-subtle" />
          </button>
        </div>
      )}

      {/* 使用说明 */}
      <div className="mt-8 grid grid-cols-3 gap-4 text-center">
        <div className="p-4">
          <div className="w-10 h-10 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-2">
            <span className="text-amber-600 font-bold">1</span>
          </div>
          <p className="text-sm text-ink-muted">上传文件</p>
        </div>
        <div className="p-4">
          <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-2">
            <span className="text-blue-600 font-bold">2</span>
          </div>
          <p className="text-sm text-ink-muted">预览&编辑</p>
        </div>
        <div className="p-4">
          <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-2">
            <span className="text-green-600 font-bold">3</span>
          </div>
          <p className="text-sm text-ink-muted">下载脱敏文件</p>
        </div>
      </div>
    </div>
  );
};

export default FileUploader;
