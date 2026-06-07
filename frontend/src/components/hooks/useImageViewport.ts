// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { computeFitScale, type DisplaySize } from '../bbox-utils';

export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 3;
export const ZOOM_STEP = 0.1;

export interface UseImageViewportReturn {
  containerRef: React.RefObject<HTMLDivElement | null>;
  viewportRef: React.RefObject<HTMLDivElement | null>;
  imageRef: React.RefObject<HTMLImageElement | null>;
  naturalSize: DisplaySize;
  viewportSize: DisplaySize;
  displaySize: DisplaySize;
  displayW: number;
  displayH: number;
  zoom: number;
  setZoom: React.Dispatch<React.SetStateAction<number>>;
  handleImageLoad: () => void;
}

/**
 * Manages the image viewport: natural size detection, ResizeObserver on the
 * viewport element, fit-scale computation, zoom state, and the derived
 * display dimensions.
 */
export function useImageViewport(imageSrc: string, readOnly: boolean): UseImageViewportReturn {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);

  const [naturalSize, setNaturalSize] = useState<DisplaySize>({ width: 0, height: 0 });
  const [viewportSize, setViewportSize] = useState<DisplaySize>({ width: 0, height: 0 });
  // displaySize is now derived via useMemo below (no longer a separate state)
  const [zoom, setZoom] = useState(1);

  // Observe viewport resize
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (!cr) return;
      setViewportSize({ width: cr.width, height: cr.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitScale = useMemo(
    () => computeFitScale(naturalSize, viewportSize),
    [naturalSize, viewportSize],
  );

  const displayW = naturalSize.width * fitScale * zoom;
  const displayH = naturalSize.height * fitScale * zoom;

  const handleImageLoad = useCallback(() => {
    if (imageRef.current) {
      setNaturalSize({
        width: imageRef.current.naturalWidth,
        height: imageRef.current.naturalHeight,
      });
    }
  }, []);

  const displaySize = useMemo<DisplaySize>(
    () => ({ width: displayW, height: displayH }),
    [displayW, displayH],
  );

  // Reset zoom when image source changes. Intentionally keep the previous
  // naturalSize: zeroing it out collapses fitScale to 0 while the new image
  // is in-flight, so the browser briefly paints the new <img> at its
  // intrinsic resolution before onload fires — visible as a page-switch "pop".
  // Leaving the old naturalSize preserves a close-enough fit that stays
  // stable until the new image loads and handleImageLoad replaces it.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting zoom when image source prop changes
    setZoom(1);
  }, [imageSrc]);

  // Reset interaction-related state when entering readOnly
  useEffect(() => {
    if (readOnly) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting zoom when readOnly prop changes
      setZoom(1);
    }
  }, [readOnly]);

  return {
    containerRef,
    viewportRef,
    imageRef,
    naturalSize,
    viewportSize,
    displaySize,
    displayW,
    displayH,
    zoom,
    setZoom,
    handleImageLoad,
  };
}
