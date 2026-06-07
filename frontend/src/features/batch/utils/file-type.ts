// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { FileType } from '@/types';
import type { BatchWizardMode } from '@/services/batchPipeline';

export function resolveBatchFileType(raw: unknown, isScanned = false): FileType {
  const fileType = String(raw ?? '').toLowerCase();
  if (fileType === 'image' || fileType === 'jpg' || fileType === 'jpeg' || fileType === 'png') {
    return FileType.IMAGE;
  }
  if (fileType === 'pdf_scanned' || (fileType === 'pdf' && isScanned)) {
    return FileType.PDF_SCANNED;
  }
  if (fileType === 'pdf') return FileType.PDF;
  if (fileType === 'doc') return FileType.DOC;
  if (fileType === 'txt' || fileType === 'md' || fileType === 'rtf' || fileType === 'html') {
    return FileType.TXT;
  }
  return FileType.DOCX;
}

export function isBatchImageMode(fileType: FileType): boolean {
  return fileType === FileType.IMAGE || fileType === FileType.PDF_SCANNED;
}

export function isBatchFileAllowedForMode(mode: BatchWizardMode, fileType: FileType): boolean {
  if (mode === 'smart') return true;
  if (mode === 'text') return fileType !== FileType.IMAGE;
  return (
    fileType === FileType.IMAGE ||
    fileType === FileType.PDF ||
    fileType === FileType.PDF_SCANNED
  );
}

export function resolveBatchFileTypeFromName(filename: string): FileType {
  const name = filename.toLowerCase();
  if (/\.(png|jpe?g|bmp|gif|webp|tiff?)$/.test(name)) return FileType.IMAGE;
  if (name.endsWith('.pdf')) return FileType.PDF;
  if (name.endsWith('.doc')) return FileType.DOC;
  if (/\.(txt|md|rtf|html?)$/.test(name)) return FileType.TXT;
  return FileType.DOCX;
}
