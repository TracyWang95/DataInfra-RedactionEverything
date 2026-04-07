// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0


import { type FC, useEffect, useRef, useState } from 'react';
import ImageBBoxEditor, { type BoundingBox } from '@/components/ImageBBoxEditor';
import { useT } from '@/i18n';

interface TypeOption { id: string; name: string; color: string }

const CHANNEL_NAME = 'playground-image-popout';

export const PlaygroundImagePopout: FC = () => {
  const t = useT();
  const [imageUrl, setImageUrl] = useState<string>('');
  const [boxes, setBoxes] = useState<BoundingBox[]>([]);
  const [types, setTypes] = useState<TypeOption[]>([]);
  const [defaultType, setDefaultType] = useState<string>('CUSTOM');
  const [ready, setReady] = useState(false);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const suppressRef = useRef(false);

  useEffect(() => {
    const ch = new BroadcastChannel(CHANNEL_NAME);
    channelRef.current = ch;

    ch.onmessage = (e) => {
      const d = e.data;
      if (d?.type === 'init') {
        setImageUrl(d.imageUrl ?? '');
        setBoxes(d.boxes ?? []);
        setTypes(d.visionTypes ?? []);
        setDefaultType(d.defaultType ?? 'CUSTOM');
        setReady(true);
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
    requestAnimationFrame(() => { suppressRef.current = false; });
  };

  const handleBoxesCommit = (prev: BoundingBox[], next: BoundingBox[]) => {
    setBoxes(next);
    suppressRef.current = true;
    channelRef.current?.postMessage({ type: 'boxes-commit', prevBoxes: prev, nextBoxes: next });
    requestAnimationFrame(() => { suppressRef.current = false; });
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
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-muted" data-testid="playground-popout">
      <ImageBBoxEditor
        imageSrc={imageUrl}
        boxes={boxes}
        onBoxesChange={handleBoxesChange}
        onBoxesCommit={handleBoxesCommit}
        getTypeConfig={getTypeConfig}
        availableTypes={types}
        defaultType={defaultType}
      />
    </div>
  );
};

export { CHANNEL_NAME };
