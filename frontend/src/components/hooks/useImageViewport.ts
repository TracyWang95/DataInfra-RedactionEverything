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
  const [displaySize, setDisplaySize] = useState<DisplaySize>({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);

  // Observe viewport resize
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
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

  // Sync displaySize state (consumed by coordinate helpers)
  useEffect(() => {
    setDisplaySize({ width: displayW, height: displayH });
  }, [displayW, displayH]);

  // Reset when image source changes
  useEffect(() => {
    setZoom(1);
    setNaturalSize({ width: 0, height: 0 });
  }, [imageSrc]);

  // Reset interaction-related state when entering readOnly
  useEffect(() => {
    if (readOnly) {
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
