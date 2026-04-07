// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { FileType, type CompareData, type FileListItem, type FileListResponse } from '@/types';

const PREVIEW_ROW_COUNT = 60;

function buildHistoryPreviewRows(): FileListItem[] {
  const rows: FileListItem[] = [];
  const now = new Date('2026-04-05T18:10:00+08:00').getTime();
  const templates = [
    { prefix: '合同交付', type: FileType.DOCX, source: 'playground' as const },
    { prefix: '扫描卷宗', type: FileType.PDF, source: 'batch' as const },
    { prefix: '签章复核', type: FileType.PDF_SCANNED, source: 'batch' as const },
    { prefix: '现场影像', type: FileType.IMAGE, source: 'playground' as const },
    { prefix: '庭审材料', type: FileType.DOCX, source: 'batch' as const },
  ];

  for (let index = 0; index < PREVIEW_ROW_COUNT; index += 1) {
    const template = templates[index % templates.length];
    const statusCycle = index % 5;
    const hasOutput = statusCycle === 0 || statusCycle === 3 || statusCycle === 4;
    const itemStatus =
      statusCycle === 0 ? 'completed' :
      statusCycle === 1 ? 'awaiting_review' :
      statusCycle === 2 ? 'review_approved' :
      statusCycle === 3 ? 'completed' :
      'completed';

    rows.push({
      file_id: `preview-history-${index + 1}`,
      original_filename: `${template.prefix}-${String(index + 1).padStart(2, '0')}${
        template.type === FileType.DOCX ? '.docx' :
        template.type === FileType.PDF ? '.pdf' :
        template.type === FileType.PDF_SCANNED ? '.pdf' :
        '.png'
      }`,
      file_size: 180_000 + index * 36_400,
      file_type: template.type,
      created_at: new Date(now - index * 1000 * 60 * 32).toISOString(),
      has_output: hasOutput,
      entity_count: 3 + (index % 7),
      upload_source: template.source,
      job_id: template.source === 'batch' ? `preview-job-${Math.floor(index / 3) + 1}` : null,
      batch_group_id: template.source === 'batch' ? `preview-group-${Math.floor(index / 3) + 1}` : null,
      batch_group_count: template.source === 'batch' ? 3 : null,
      item_status: itemStatus,
      item_id: `preview-item-${index + 1}`,
      job_embed: template.source === 'batch'
        ? {
            status: statusCycle === 1 ? 'awaiting_review' : hasOutput ? 'completed' : 'running',
            job_type: template.type === FileType.DOCX ? 'text_batch' : 'image_batch',
            items: [],
            first_awaiting_review_item_id: statusCycle === 1 ? `preview-item-${index + 1}` : null,
            wizard_furthest_step: hasOutput ? 5 : 4,
            batch_step1_configured: true,
            progress: {
              total_items: 12,
              pending: 0,
              queued: 0,
              parsing: 0,
              ner: 0,
              vision: 0,
              awaiting_review: statusCycle === 1 ? 2 : 0,
              review_approved: statusCycle === 2 ? 1 : 0,
              redacting: 0,
              completed: hasOutput ? 9 : 6,
              failed: statusCycle === 4 ? 1 : 0,
              cancelled: 0,
            },
          }
        : null,
    });
  }

  return rows;
}

export function buildHistoryPreviewResponse(
  page: number,
  pageSize: number,
  source?: 'playground' | 'batch',
): FileListResponse {
  const allRows = buildHistoryPreviewRows().filter((row) => (source ? row.upload_source === source : true));
  const start = Math.max(0, (page - 1) * pageSize);
  const files = allRows.slice(start, start + pageSize);

  return {
    files,
    total: allRows.length,
    page,
    page_size: pageSize,
  };
}

export function isHistoryPreviewRow(row: FileListItem): boolean {
  return row.file_id.startsWith('preview-history-');
}

export function buildHistoryPreviewCompare(row: FileListItem): CompareData {
  const baseText = `文件 ${row.original_filename} 的示例对比结果已生成，用来检查列表、翻页和对比弹窗的排版。`;
  return {
    file_id: row.file_id,
    original_content: `${baseText}\n原文包含张宁、310101199201013422、静安区南京西路 88 号。`,
    redacted_content: `${baseText}\n原文包含[姓名]、[身份证号]、[地址]。`,
    changes: [
      { original: '张宁', replacement: '[姓名]', count: 1 },
      { original: '310101199201013422', replacement: '[身份证号]', count: 1 },
      { original: '静安区南京西路 88 号', replacement: '[地址]', count: 1 },
    ],
  };
}

export function buildHistoryPreviewDownloadBlob(row: FileListItem, redacted: boolean): Blob {
  const title = redacted ? '脱敏预览文件' : '原始预览文件';
  return new Blob(
    [`${title}\n\n${row.original_filename}\n\n这个文件用于检查下载入口、列表密度和分页布局。`],
    { type: 'text/plain;charset=utf-8' },
  );
}
