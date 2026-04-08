// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { cn } from '@/lib/utils';
import {
  ENTITY_GROUPS,
  getEntityGroupLabel,
  getEntityRiskConfig,
  getEntityTypeName,
  type EntityTypeConfig,
} from '@/config/entityTypes';

export type EntityTypeOption = { id: string; name: string; description?: string };

type Props = {
  entityTypes: EntityTypeOption[];
  selectedTypeId: string;
  onSelectType: (id: string) => void;
  className?: string;
};

export function EntityTypeGroupPicker({
  entityTypes,
  selectedTypeId,
  onSelectType,
  className = '',
}: Props) {
  const enabled = new Set(entityTypes.map((type) => type.id));
  const resolveName = (cfg: EntityTypeConfig) =>
    entityTypes.find((type) => type.id === cfg.id)?.name ?? getEntityTypeName(cfg.id);

  return (
    <div className={cn('flex max-h-[280px] flex-col gap-3 overflow-auto pr-1', className)}>
      {ENTITY_GROUPS.filter((group) => group.types.some((type) => enabled.has(type.id))).map((group) => {
        const availableTypes = group.types.filter((type) => enabled.has(type.id));
        if (availableTypes.length === 0) return null;

        return (
          <section
            key={group.id}
            className="overflow-hidden rounded-2xl border border-border/70 bg-[var(--surface-control)] shadow-[var(--shadow-sm)]"
          >
            <div
              className="flex items-center gap-2 border-b border-border/60 px-3 py-2.5"
              style={{
                background: `linear-gradient(135deg, ${group.bgColor} 0%, color-mix(in srgb, ${group.bgColor} 72%, transparent) 100%)`,
              }}
            >
              <span
                className="size-2.5 rounded-full"
                style={{ backgroundColor: group.color }}
                aria-hidden="true"
              />
              <span
                className="text-[11px] font-semibold uppercase tracking-[0.12em]"
                style={{ color: group.textColor }}
              >
                {getEntityGroupLabel(group.id)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 p-2 sm:grid-cols-3">
              {availableTypes.map((type) => {
                const isSelected = selectedTypeId === type.id;
                const risk = getEntityRiskConfig(type.id);

                return (
                  <button
                    key={type.id}
                    type="button"
                    onClick={() => onSelectType(type.id)}
                    className={cn(
                      'min-w-0 rounded-xl border px-3 py-2 text-left text-xs transition-all duration-200',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      isSelected
                        ? 'border-transparent shadow-[var(--shadow-control)]'
                        : 'border-border/70 bg-[var(--surface-control-muted)] hover:border-border hover:bg-accent',
                    )}
                    style={
                      isSelected
                        ? {
                            backgroundColor: risk.bgColor,
                            color: risk.textColor,
                            boxShadow: `inset 0 0 0 1px ${risk.color}33`,
                          }
                        : undefined
                    }
                    title={type.description ?? resolveName(type)}
                  >
                    <span className="block truncate font-medium">{resolveName(type)}</span>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
