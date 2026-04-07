// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { getSelectionToneClasses } from './selectionPalette';

export type SelectionVariant = 'regex' | 'semantic' | 'visual';

export function textGroupKeyToVariant(key: 'regex' | 'llm' | 'other'): SelectionVariant {
  return key === 'regex' ? 'regex' : 'semantic';
}

const cardBase =
  'rounded-xl border transition-[background-color,border-color,box-shadow,color] duration-200 ease-out';

export function selectableCardClass(selected: boolean, variant: SelectionVariant): string {
  if (!selected) {
    return `${cardBase} border-border/70 bg-card text-foreground/80 shadow-[0_1px_2px_rgba(0,0,0,0.04)] hover:border-border hover:bg-accent/40 hover:text-foreground hover:shadow-[0_1px_3px_rgba(0,0,0,0.06)]`;
  }

  return `${cardBase} ${getSelectionToneClasses(variant).cardSelected}`;
}

export function selectableCardClassCompact(selected: boolean, variant: SelectionVariant): string {
  if (!selected) {
    return `${cardBase} border-border/70 bg-card text-foreground/80 hover:border-border hover:bg-accent/40 hover:text-foreground`;
  }

  return `${cardBase} ${getSelectionToneClasses(variant).cardSelectedCompact}`;
}

export function selectableCheckboxClass(variant: SelectionVariant, size: 'sm' | 'md' = 'sm'): string {
  const dim = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5';
  return `${dim} shrink-0 rounded border-gray-300/70 focus:ring-2 focus:ring-offset-0 focus:outline-none ${getSelectionToneClasses(variant).checkbox}`;
}

export function selectableCardClassNeutral(selected: boolean): string {
  if (!selected) {
    return `${cardBase} border-border/70 bg-card text-foreground/80 hover:border-border hover:bg-accent/40 hover:text-foreground`;
  }

  return `${cardBase} ${getSelectionToneClasses('semantic').cardNeutralSelected}`;
}

export function selectableCheckboxNeutral(size: 'sm' | 'md' = 'sm'): string {
  const dim = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5';
  return `${dim} shrink-0 rounded border-gray-300/70 focus:ring-2 focus:ring-offset-0 focus:outline-none ${getSelectionToneClasses('semantic').checkbox}`;
}

export function formCheckboxClass(size: 'sm' | 'md' = 'sm'): string {
  const dim = size === 'md' ? 'h-4 w-4' : 'h-3.5 w-3.5';
  return `${dim} shrink-0 rounded border-gray-300/80 accent-foreground focus:ring-2 focus:ring-ring/30 focus:ring-offset-0 focus:outline-none`;
}
