import React, { useMemo } from 'react';
import { useEntityStore } from '../../hooks/useRedaction';
import type { Entity } from '../../types';
import { t } from '../../i18n';
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
  const { toggleEntitySelection } = useEntityStore();

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
  const label = t(`entityTag.${entity.type}`) !== `entityTag.${entity.type}`
    ? t(`entityTag.${entity.type}`)
    : entity.type;

  return (
    <span
      role="button"
      tabIndex={0}
      aria-pressed={entity.selected}
      aria-label={`${label}: ${entity.text}${entity.selected ? t('entityTag.selected') : ''}`}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }}
      className={clsx(
        'entity-highlight',
        `entity-${entity.type}`,
        entity.selected && 'selected'
      )}
      title={`${label}${entity.replacement ? ` → ${entity.replacement}` : ''}`}
    >
      {entity.text}
      {entity.selected && (
        <span className="ml-1 text-xs opacity-70" aria-hidden="true">✓</span>
      )}
    </span>
  );
};

export default EntityHighlighter;
