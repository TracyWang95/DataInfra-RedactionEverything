// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { CSSProperties } from 'react';

export type SelectionTone = 'regex' | 'semantic' | 'visual';

export const selectionToneHex: Record<SelectionTone, string> = {
  regex: '#6f86a7',
  semantic: '#10a37f',
  visual: '#7c6f9c',
};

type ToneClasses = {
  headerSurface: string;
  dot: string;
  badgeText: string;
  cardSelected: string;
  cardSelectedCompact: string;
  cardNeutralSelected: string;
  tileSurface: string;
  titleText: string;
  metaText: string;
  descriptionText: string;
  hoverRing: string;
  checkbox: string;
};

const toneClasses: Record<SelectionTone, ToneClasses> = {
  regex: {
    headerSurface: 'border-[var(--selection-regex-border)] bg-[var(--selection-regex-soft)]',
    dot: 'bg-[var(--selection-regex-accent)]',
    badgeText: 'text-[var(--selection-regex-text)]',
    cardSelected: 'border-[var(--selection-regex-border)] bg-[var(--selection-regex-surface)] text-[var(--selection-regex-text)] shadow-sm',
    cardSelectedCompact: 'border-[var(--selection-regex-border)] bg-[var(--selection-regex-surface)] text-[var(--selection-regex-text)]',
    cardNeutralSelected: 'border-[var(--selection-regex-border)] bg-[var(--selection-regex-surface)] text-[var(--selection-regex-text)] shadow-sm',
    tileSurface: 'border-[var(--selection-regex-border)] bg-[var(--selection-regex-soft)]',
    titleText: 'text-[var(--selection-regex-text)]',
    metaText: 'text-[var(--selection-regex-muted)]',
    descriptionText: 'text-[var(--selection-regex-muted)]',
    hoverRing: 'hover:ring-[var(--selection-regex-ring)]',
    checkbox: 'accent-[var(--selection-regex-accent)] focus:ring-[var(--selection-regex-ring)]',
  },
  semantic: {
    headerSurface: 'border-[var(--selection-semantic-border)] bg-[var(--selection-semantic-soft)]',
    dot: 'bg-[var(--selection-semantic-accent)]',
    badgeText: 'text-[var(--selection-semantic-text)]',
    cardSelected: 'border-[var(--selection-semantic-border)] bg-[var(--selection-semantic-surface)] text-[var(--selection-semantic-text)] shadow-sm',
    cardSelectedCompact: 'border-[var(--selection-semantic-border)] bg-[var(--selection-semantic-surface)] text-[var(--selection-semantic-text)]',
    cardNeutralSelected: 'border-[var(--selection-semantic-border)] bg-[var(--selection-semantic-surface)] text-[var(--selection-semantic-text)] shadow-sm',
    tileSurface: 'border-[var(--selection-semantic-border)] bg-[var(--selection-semantic-soft)]',
    titleText: 'text-[var(--selection-semantic-text)]',
    metaText: 'text-[var(--selection-semantic-muted)]',
    descriptionText: 'text-[var(--selection-semantic-muted)]',
    hoverRing: 'hover:ring-[var(--selection-semantic-ring)]',
    checkbox: 'accent-[var(--selection-semantic-accent)] focus:ring-[var(--selection-semantic-ring)]',
  },
  visual: {
    headerSurface: 'border-[var(--selection-visual-border)] bg-[var(--selection-visual-soft)]',
    dot: 'bg-[var(--selection-visual-accent)]',
    badgeText: 'text-[var(--selection-visual-text)]',
    cardSelected: 'border-[var(--selection-visual-border)] bg-[var(--selection-visual-surface)] text-[var(--selection-visual-text)] shadow-sm',
    cardSelectedCompact: 'border-[var(--selection-visual-border)] bg-[var(--selection-visual-surface)] text-[var(--selection-visual-text)]',
    cardNeutralSelected: 'border-[var(--selection-visual-border)] bg-[var(--selection-visual-surface)] text-[var(--selection-visual-text)] shadow-sm',
    tileSurface: 'border-[var(--selection-visual-border)] bg-[var(--selection-visual-soft)]',
    titleText: 'text-[var(--selection-visual-text)]',
    metaText: 'text-[var(--selection-visual-muted)]',
    descriptionText: 'text-[var(--selection-visual-muted)]',
    hoverRing: 'hover:ring-[var(--selection-visual-ring)]',
    checkbox: 'accent-[var(--selection-visual-accent)] focus:ring-[var(--selection-visual-ring)]',
  },
};

export function getSelectionToneClasses(tone: SelectionTone): ToneClasses {
  return toneClasses[tone];
}

export function getSelectionMarkStyle(tone: SelectionTone): CSSProperties {
  return {
    backgroundColor: `var(--selection-${tone}-surface)`,
    color: `var(--selection-${tone}-text)`,
  };
}
