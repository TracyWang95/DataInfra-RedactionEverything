import React, { useMemo } from 'react';
import { useRedactionStore } from '../../hooks/useRedaction';
import type { Entity } from '../../types';
import clsx from 'clsx';

interface EntityHighlighterProps {
  text: string;
  entities: Entity[];
  onEntityClick?: (entity: Entity) => void;
}

export const EntityHighlighter: React.FC<EntityHighlighterProps> = ({
  text,
  entities,
  onEntityClick,
}) => {
  const { toggleEntitySelection } = useRedactionStore();

  // 按位置排序实体
  const sortedEntities = useMemo(() => {
    return [...entities].sort((a, b) => a.start - b.start);
  }, [entities]);

  // 将文本分割成带高亮的片段
  const segments = useMemo(() => {
    const result: Array<{
      type: 'text' | 'entity';
      content: string;
      entity?: Entity;
    }> = [];

    let lastEnd = 0;

    for (const entity of sortedEntities) {
      // 添加实体前的普通文本
      if (entity.start > lastEnd) {
        result.push({
          type: 'text',
          content: text.slice(lastEnd, entity.start),
        });
      }

      // 添加实体
      result.push({
        type: 'entity',
        content: text.slice(entity.start, entity.end),
        entity,
      });

      lastEnd = entity.end;
    }

    // 添加最后一段普通文本
    if (lastEnd < text.length) {
      result.push({
        type: 'text',
        content: text.slice(lastEnd),
      });
    }

    return result;
  }, [text, sortedEntities]);

  const handleEntityClick = (entity: Entity) => {
    toggleEntitySelection(entity.id);
    onEntityClick?.(entity);
  };

  return (
    <div className="whitespace-pre-wrap font-serif text-ink leading-relaxed">
      {segments.map((segment, index) => {
        if (segment.type === 'text') {
          return <span key={index}>{segment.content}</span>;
        }

        const entity = segment.entity!;
        return (
          <EntityTag
            key={entity.id}
            entity={entity}
            onClick={() => handleEntityClick(entity)}
          />
        );
      })}
    </div>
  );
};

// 实体标签组件
interface EntityTagProps {
  entity: Entity;
  onClick: () => void;
}

const EntityTag: React.FC<EntityTagProps> = ({ entity, onClick }) => {
  const typeLabels: Record<string, string> = {
    PERSON: '人名',
    ID_CARD: '身份证',
    PHONE: '电话',
    ADDRESS: '地址',
    BANK_CARD: '银行卡',
    CASE_NUMBER: '案号',
    DATE: '日期',
    MONEY: '金额',
    CUSTOM: '自定义',
  };

  return (
    <span
      onClick={onClick}
      className={clsx(
        'entity-highlight',
        `entity-${entity.type}`,
        entity.selected && 'selected'
      )}
      title={`${typeLabels[entity.type] || entity.type}${entity.replacement ? ` → ${entity.replacement}` : ''}`}
    >
      {entity.text}
      {entity.selected && (
        <span className="ml-1 text-xs opacity-70">✓</span>
      )}
    </span>
  );
};

export default EntityHighlighter;
