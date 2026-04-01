/**
 * 虚拟化实体列表 — 用于 1000+ 实体的高性能渲染
 *
 * 使用 react-virtuoso 替代全量 DOM 渲染，
 * 避免 Playground/Batch 在大文档场景下卡顿。
 */
import React, { useCallback } from 'react';
import { Virtuoso } from 'react-virtuoso';

export interface VirtualEntityItem {
  id: string;
  text: string;
  type: string;
  selected: boolean;
  source?: string;
  confidence?: number;
}

interface VirtualEntityListProps {
  items: VirtualEntityItem[];
  height: number;
  onToggle: (id: string) => void;
  getTypeLabel: (type: string) => string;
  getTypeColor?: (type: string) => string;
}

const EntityRow: React.FC<{
  item: VirtualEntityItem;
  onToggle: (id: string) => void;
  getTypeLabel: (type: string) => string;
  getTypeColor?: (type: string) => string;
}> = React.memo(({ item, onToggle, getTypeLabel, getTypeColor }) => {
  const color = getTypeColor?.(item.type) || 'bg-gray-100';
  return (
    <div
      className={`flex items-center gap-2 px-3 py-1.5 text-sm border-b border-gray-100 hover:bg-gray-50 transition-colors ${
        item.selected ? 'opacity-100' : 'opacity-50'
      }`}
      role="option"
      aria-selected={item.selected}
    >
      <input
        type="checkbox"
        checked={item.selected}
        onChange={() => onToggle(item.id)}
        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        aria-label={`${item.selected ? '取消选择' : '选择'} ${getTypeLabel(item.type)}: ${item.text}`}
      />
      <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${color}`}>
        {getTypeLabel(item.type)}
      </span>
      <span className="truncate flex-1 text-gray-700" title={item.text}>
        {item.text}
      </span>
      {item.confidence != null && (
        <span className="text-xs text-gray-400 tabular-nums flex-shrink-0">
          {Math.round(item.confidence * 100)}%
        </span>
      )}
    </div>
  );
});
EntityRow.displayName = 'EntityRow';

export const VirtualEntityList: React.FC<VirtualEntityListProps> = ({
  items,
  height,
  onToggle,
  getTypeLabel,
  getTypeColor,
}) => {
  const renderItem = useCallback(
    (index: number) => (
      <EntityRow
        item={items[index]}
        onToggle={onToggle}
        getTypeLabel={getTypeLabel}
        getTypeColor={getTypeColor}
      />
    ),
    [items, onToggle, getTypeLabel, getTypeColor]
  );

  if (items.length === 0) {
    return (
      <div className="flex items-center justify-center h-20 text-sm text-gray-400">
        暂无识别结果
      </div>
    );
  }

  // 少于 100 条时不启用虚拟化，避免额外开销
  if (items.length < 100) {
    return (
      <div className="overflow-y-auto" style={{ maxHeight: height }} role="listbox" aria-label="实体列表">
        {items.map((item) => (
          <EntityRow
            key={item.id}
            item={item}
            onToggle={onToggle}
            getTypeLabel={getTypeLabel}
            getTypeColor={getTypeColor}
          />
        ))}
      </div>
    );
  }

  return (
    <div role="listbox" aria-label={`实体列表（共 ${items.length} 项）`}>
      <Virtuoso
        totalCount={items.length}
        itemContent={renderItem}
        style={{ height }}
        overscan={20}
      />
    </div>
  );
};
