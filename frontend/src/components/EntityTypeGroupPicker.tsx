import React from 'react';
import { ENTITY_GROUPS, type EntityTypeConfig } from '../config/entityTypes';

export type EntityTypeOption = { id: string; name: string; description?: string };

type Props = {
  entityTypes: EntityTypeOption[];
  selectedTypeId: string;
  onSelectType: (id: string) => void;
  className?: string;
};

/** 与 Playground 划词弹层一致：ENTITY_GROUPS 分组 + 网格（仅展示当前启用类型） */
export const EntityTypeGroupPicker: React.FC<Props> = ({
  entityTypes,
  selectedTypeId,
  onSelectType,
  className = '',
}) => {
  const enabled = new Set(entityTypes.map(t => t.id));
  const resolveName = (cfg: EntityTypeConfig) =>
    entityTypes.find(et => et.id === cfg.id)?.name ?? cfg.name;

  return (
    <div className={`max-h-[240px] overflow-auto space-y-2 pr-1 ${className}`}>
      {ENTITY_GROUPS.filter(group => group.types.some(t => enabled.has(t.id))).map(group => {
        const availableTypes = group.types.filter(t => enabled.has(t.id));
        if (availableTypes.length === 0) return null;
        return (
          <div key={group.id} className="rounded-lg border border-gray-200 overflow-hidden bg-white">
            <div className="px-2.5 py-1.5 text-caption font-semibold text-[#262626] bg-gray-100 border-b border-gray-200">
              {group.label}
            </div>
            <div className="p-1.5 grid grid-cols-3 gap-1 bg-white">
              {availableTypes.map(type => {
                const isSelected = selectedTypeId === type.id;
                return (
                  <button
                    key={type.id}
                    type="button"
                    onClick={() => onSelectType(type.id)}
                    className={`text-xs px-2 py-1.5 rounded-md text-left transition-all truncate text-[#262626] ${
                      isSelected
                        ? 'font-semibold bg-gray-100 ring-2 ring-gray-400 ring-offset-0'
                        : 'hover:bg-gray-50'
                    }`}
                    title={type.description}
                  >
                    {resolveName(type)}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};