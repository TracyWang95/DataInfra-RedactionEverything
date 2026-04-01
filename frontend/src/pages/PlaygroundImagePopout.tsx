/**
 * 独立新窗口的图像标注编辑器。
 * 通过 BroadcastChannel 与主 Playground 窗口双向同步 boxes 数据。
 *
 * 协议：
 *   主窗口 → 本窗口:  { type: 'init', imageUrl, boxes, visionTypes, defaultType }
 *   主窗口 → 本窗口:  { type: 'boxes-update', boxes }          // 主窗口改了 boxes
 *   本窗口 → 主窗口:  { type: 'boxes-sync', boxes }            // 本窗口改了 boxes
 *   本窗口 → 主窗口:  { type: 'boxes-commit', prevBoxes, nextBoxes }
 */
import React, { useEffect, useRef, useState } from 'react';
import ImageBBoxEditor, { type BoundingBox } from '../components/ImageBBoxEditor';

interface TypeOption { id: string; name: string; color: string }

const CHANNEL_NAME = 'playground-image-popout';

const PlaygroundImagePopout: React.FC = () => {
  const [imageUrl, setImageUrl] = useState<string>('');
  const [boxes, setBoxes] = useState<BoundingBox[]>([]);
  const [types, setTypes] = useState<TypeOption[]>([]);
  const [defaultType, setDefaultType] = useState<string>('CUSTOM');
  const [ready, setReady] = useState(false);
  const channelRef = useRef<BroadcastChannel | null>(null);
  /** 防止自身发出的 sync 又被自己接收后覆盖 */
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

    // 告诉主窗口"我准备好了，发 init 吧"
    ch.postMessage({ type: 'popout-ready' });

    return () => ch.close();
  }, []);

  const getTypeConfig = (typeId: string) => {
    const t = types.find(x => x.id === typeId);
    return t ? { name: t.name, color: t.color } : { name: typeId, color: '#6366F1' };
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
      <div className="h-screen w-screen flex items-center justify-center bg-[#fafafa] text-sm text-gray-500">
        等待主窗口连接…
      </div>
    );
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-[#fafafa] overflow-hidden">
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

export default PlaygroundImagePopout;
export { CHANNEL_NAME };
