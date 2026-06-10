// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState, type RefObject } from 'react';

const FALLBACK_TABLE_BODY_HEIGHT = 600;

/** Clamp a page size into the [minPageSize, maxPageSize] range. */
export function clampPageSize(pageSize: number, minPageSize: number, maxPageSize: number): number {
  return Math.min(Math.max(Math.round(pageSize), minPageSize), maxPageSize);
}

/**
 * Build a density interpolator for a table page size: returns a function that
 * maps (valueAtMinPageSize, valueAtMaxPageSize) onto the current page size
 * using a logarithmic ratio.
 */
export function interpolateDensity(
  pageSize: number,
  minPageSize: number,
  maxPageSize: number,
): (max: number, min: number) => number {
  const safePageSize = clampPageSize(pageSize, minPageSize, maxPageSize);
  const densityRatio =
    Math.log(safePageSize / minPageSize) / Math.log(maxPageSize / minPageSize);
  return (max: number, min: number): number => max - (max - min) * densityRatio;
}

interface ProportionalRowHeightOptions {
  pageSize: number;
  minPageSize: number;
  maxPageSize: number;
  bodyRef: RefObject<HTMLDivElement | null>;
  /** Optional sticky table head measured inside the body element. */
  headRef?: RefObject<HTMLDivElement | null>;
  /** Subtract 1px per row divider (safePageSize - 1) from the available height. */
  subtractRowDividers?: boolean;
}

/**
 * Observe a table body element and derive a per-row height so that exactly
 * `pageSize` rows fill the available vertical space.
 */
export function useProportionalRowHeight({
  pageSize,
  minPageSize,
  maxPageSize,
  bodyRef,
  headRef,
  subtractRowDividers = false,
}: ProportionalRowHeightOptions): number {
  const [bodyHeight, setBodyHeight] = useState(FALLBACK_TABLE_BODY_HEIGHT);
  const [headHeight, setHeadHeight] = useState(0);

  useEffect(() => {
    const element = bodyRef.current;
    if (!element) return;

    const update = () => {
      const nextHeight = element.clientHeight || FALLBACK_TABLE_BODY_HEIGHT;
      setBodyHeight((prev) => (Math.abs(prev - nextHeight) < 0.5 ? prev : nextHeight));
      const nextHeadHeight = headRef?.current?.getBoundingClientRect().height ?? 0;
      setHeadHeight((prev) => (Math.abs(prev - nextHeadHeight) < 0.5 ? prev : nextHeadHeight));
    };

    update();
    const ResizeObserverCtor = window.ResizeObserver;
    if (!ResizeObserverCtor) {
      window.addEventListener('resize', update);
      return () => window.removeEventListener('resize', update);
    }

    const observer = new ResizeObserverCtor(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [bodyRef, headRef]);

  const safePageSize = clampPageSize(pageSize, minPageSize, maxPageSize);
  const dividerAllowance = subtractRowDividers ? Math.max(0, safePageSize - 1) : 0;
  return Math.max(1, (bodyHeight - headHeight - dividerAllowance) / safePageSize);
}
