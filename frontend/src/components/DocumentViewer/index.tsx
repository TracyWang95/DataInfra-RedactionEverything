import React from 'react';
import { useFileStore, useEntityStore } from '../../hooks/useRedaction';
import { EntityHighlighter } from '../EntityHighlighter';
import { DocumentTextIcon, PhotoIcon } from '@heroicons/react/24/outline';
import clsx from 'clsx';

interface DocumentViewerProps {
  showHighlights?: boolean;
  className?: string;
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({
  showHighlights = true,
  className,
}) => {
  const { fileInfo, content, pages } = useFileStore();
  const { entities, boundingBoxes } = useEntityStore();

  // 根据文件类型渲染不同的视图
  const isScanned = fileInfo?.is_scanned;

  if (!fileInfo) {
    return (
      <div className={clsx('flex items-center justify-center h-full text-ink-subtle', className)}>
        <p>请先上传文件</p>
      </div>
    );
  }

  // 图片/扫描件视图
  if (isScanned) {
    return (
      <div className={clsx('h-full overflow-auto', className)}>
        <ImageViewer fileId={fileInfo.file_id} boundingBoxes={boundingBoxes} />
      </div>
    );
  }

  // 文本文档视图
  return (
    <div className={clsx('h-full overflow-auto', className)}>
      <div className="p-6 document-content">
        {pages && pages.length > 1 ? (
          // 多页文档
          pages.map((pageContent, index) => (
            <div key={index} className="mb-8">
              <div className="flex items-center gap-2 mb-4 text-sm text-ink-muted">
                <DocumentTextIcon className="w-4 h-4" />
                <span>第 {index + 1} 页</span>
              </div>
              <div className="bg-white rounded-lg shadow-sm border border-line p-6">
                {showHighlights ? (
                  <EntityHighlighter
                    text={pageContent}
                    entities={entities.filter((e) => e.page === index + 1)}
                  />
                ) : (
                  <pre className="whitespace-pre-wrap font-serif text-ink leading-relaxed">
                    {pageContent}
                  </pre>
                )}
              </div>
            </div>
          ))
        ) : (
          // 单页文档
          <div className="bg-white rounded-lg shadow-sm border border-line p-6">
            {showHighlights ? (
              <EntityHighlighter text={content} entities={entities} />
            ) : (
              <pre className="whitespace-pre-wrap font-serif text-ink leading-relaxed">
                {content}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// 图片查看器组件
interface ImageViewerProps {
  fileId: string;
  boundingBoxes: Array<{
    id: string;
    x: number;
    y: number;
    width: number;
    height: number;
    selected: boolean;
    type: string;
  }>;
}

const ImageViewer: React.FC<ImageViewerProps> = ({ fileId, boundingBoxes }) => {
  const { toggleBoxSelection } = useEntityStore();

  // 图片预览URL
  const imageUrl = `/api/v1/files/${fileId}/download`;

  return (
    <div className="p-6">
      <div className="flex items-center gap-2 mb-4 text-sm text-ink-muted">
        <PhotoIcon className="w-4 h-4" />
        <span>图片预览</span>
      </div>
      
      <div className="relative inline-block bg-white rounded-lg shadow-sm border border-line overflow-hidden">
        <img
          src={imageUrl}
          alt="文档预览"
          className="max-w-full h-auto"
          style={{ maxHeight: '70vh' }}
        />
        
        {/* 敏感区域标注层 */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none"
          style={{ mixBlendMode: 'multiply' }}
        >
          {boundingBoxes.map((box) => (
            <g key={box.id}>
              {/* 边界框 */}
              <rect
                x={`${box.x * 100}%`}
                y={`${box.y * 100}%`}
                width={`${box.width * 100}%`}
                height={`${box.height * 100}%`}
                fill={box.selected ? 'rgba(239, 68, 68, 0.3)' : 'transparent'}
                stroke={box.selected ? '#EF4444' : '#9CA3AF'}
                strokeWidth="2"
                strokeDasharray={box.selected ? 'none' : '4'}
                className="cursor-pointer pointer-events-auto"
                onClick={() => toggleBoxSelection(box.id)}
              />
              
              {/* 类型标签 */}
              {box.selected && (
                <text
                  x={`${(box.x + box.width / 2) * 100}%`}
                  y={`${box.y * 100 - 1}%`}
                  textAnchor="middle"
                  className="text-xs fill-red-600 font-medium"
                >
                  {box.type}
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>
      
      <p className="mt-4 text-sm text-ink-muted">
        点击红色区域可以取消选中，点击虚线框可以选中
      </p>
    </div>
  );
};

export default DocumentViewer;
