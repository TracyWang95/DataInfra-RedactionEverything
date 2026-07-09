// Copyright 2026 DataInfra-RedactionEverything Contributors

import { getSelectionToneClasses } from './selectionPalette';

export type SelectionVariant = 'regex' | 'semantic' | 'visual';

const cardBase =
  'rounded-xl border transition-[background-color,border-color,box-shadow,color] duration-200 ease-out';

export function selectableCardClass(selected: boolean, variant: SelectionVariant): string {
  if (!selected) {
    return `${cardBase} border-border/70 bg-card text-foreground/80 shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:border-border hover:bg-accent/40 hover:text-foreground hover:shadow-[0_1px_3px_rgba(0,0,0,0.06)]`;
  }

  return `${cardBase} ${getSelectionToneClasses(variant).cardSelected}`;
}

export function selectableCheckboxClass(
  variant: SelectionVariant,
  size: 'sm' | 'md' = 'sm',
): string {
  const dim = size === 'md' ? 'size-4' : 'size-3.5';
  return `${dim} shrink-0 rounded border-gray-300/70 focus:ring-2 focus:ring-offset-0 focus:outline-none ${getSelectionToneClasses(variant).checkbox}`;
}
