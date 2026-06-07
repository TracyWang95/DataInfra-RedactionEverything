// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { type FC, useEffect, useRef, useState } from 'react';
import ImageBBoxEditor, { type BoundingBox } from '@/components/ImageBBoxEditor';
import { PaginationRail } from '@/components/PaginationRail';
import { useT } from '@/i18n';

interface TypeOption {
  id: string;
  name: string;
  color: string;
}

const CHANNEL_NAME = 'playground-image-popout';

export const PlaygroundImagePopout: FC = () => {
  const t = useT();
  const [imageUrl, setImageUrl] = useState<string>('');
  const [boxes, setBoxes] = useState<BoundingBox[]>([]);
  const [types, setTypes] = useState<TypeOption[]>([]);
  const [defaultType, setDefaultType] = useState<string>('CUSTOM');
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [ready, setReady] = useState(false);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const suppressRef = useRef(false);

  useEffect(() => {
    const ch = new BroadcastChannel(CHANNEL_NAME);
    channelRef.current = ch;

    ch.onmessage = (e) => {
      const d = e.data;
      if (d?.type === 'init') {
        setImageUrl(d.rawImageUrl || d.imageUrl || '');
        setBoxes(d.boxes ?? []);
        setTypes(d.visionTypes ?? []);
        setDefaultType(d.defaultType ?? 'CUSTOM');
        setCurrentPage(Number(d.currentPage || 1));
        setTotalPages(Math.max(1, Number(d.totalPages || 1)));
        setReady(true);
      }
      if (d?.type === 'image-update') {
        setImageUrl(d.imageUrl || '');
      }
      if (d?.type === 'page-update') {
        setCurrentPage(Number(d.currentPage || 1));
        setTotalPages(Math.max(1, Number(d.totalPages || 1)));
      }
      if (d?.type === 'boxes-update') {
        if (suppressRef.current) return;
        setBoxes(d.boxes ?? []);
      }
    };

    ch.postMessage({ type: 'popout-ready' });
    return () => ch.close();
  }, []);

  const getTypeConfig = (typeId: string) => {
    const found = types.find((item) => item.id === typeId);
    return found ? { name: found.name, color: found.color } : { name: typeId, color: '#6366F1' };
  };

  const handleBoxesChange = (next: BoundingBox[]) => {
    setBoxes(next);
    suppressRef.current = true;
    channelRef.current?.postMessage({ type: 'boxes-sync', boxes: next });
    requestAnimationFrame(() => {
      suppressRef.current = false;
    });
  };

  const handleBoxesCommit = (prev: BoundingBox[], next: BoundingBox[]) => {
    setBoxes(next);
    suppressRef.current = true;
    channelRef.current?.postMessage({ type: 'boxes-commit', prevBoxes: prev, nextBoxes: next });
    requestAnimationFrame(() => {
      suppressRef.current = false;
    });
  };

  const handlePageChange = (page: number) => {
    const nextPage = Math.min(Math.max(1, page), totalPages);
    setCurrentPage(nextPage);
    channelRef.current?.postMessage({ type: 'page-change', page: nextPage });
  };

  if (!ready) {
    return (
      <div
        className="flex h-screen w-screen items-center justify-center bg-muted text-sm text-muted-foreground"
        data-testid="playground-popout-loading"
      >
        {t('playground.waitingConnection')}
      </div>
    );
  }

  return (
    <div
      className="flex h-screen w-screen flex-col overflow-hidden bg-muted"
      data-testid="playground-popout"
    >
      <ImageBBoxEditor
        imageSrc={imageUrl}
        boxes={boxes}
        onBoxesChange={handleBoxesChange}
        onBoxesCommit={handleBoxesCommit}
        getTypeConfig={getTypeConfig}
        availableTypes={types}
        defaultType={defaultType}
        viewportTopSlot={
          totalPages > 1 ? (
            <div className="w-full min-w-[320px]">
              <PaginationRail
                page={currentPage}
                pageSize={1}
                totalItems={totalPages}
                totalPages={totalPages}
                compact
                onPageChange={handlePageChange}
              />
            </div>
          ) : null
        }
      />
    </div>
  );
};

export { CHANNEL_NAME };
