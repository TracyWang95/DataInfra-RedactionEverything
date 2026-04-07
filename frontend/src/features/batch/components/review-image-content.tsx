// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { Checkbox } from '@/components/ui/checkbox';
import ImageBBoxEditor from '@/components/ImageBBoxEditor';
import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import type { PipelineCfg } from '../types';

export interface ReviewImageContentProps {
  reviewBoxes: EditorBox[];
  reviewOrigImageBlobUrl: string;
  reviewImagePreviewSrc: string;
  reviewImagePreviewLoading: boolean;
  selectedReviewBoxCount: number;
  pipelines: PipelineCfg[];
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  handleReviewBoxesCommit: (prev: EditorBox[], next: EditorBox[]) => void;
  toggleReviewBoxSelected: (id: string) => void;
}

export function ReviewImageContent({
  reviewBoxes,
  reviewOrigImageBlobUrl,
  reviewImagePreviewSrc,
  reviewImagePreviewLoading,
  selectedReviewBoxCount,
  pipelines,
  setReviewBoxes,
  handleReviewBoxesCommit,
  toggleReviewBoxSelected,
}: ReviewImageContentProps) {
  const t = useT();

  const getVisionTypeMeta = (id: string) => {
    for (const p of pipelines) {
      const tt = p.types.find(x => x.id === id);
      if (tt) return { name: tt.name, color: '#6366F1' };
    }
    return { name: id, color: '#6366F1' };
  };

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden">
      {/* Column 1: Original + bbox editor */}
      <div className="flex-[2] min-w-0 min-h-0 border-r flex flex-col">
        <div className="flex-1 min-h-0 relative">
          <div className="absolute inset-0">
            <ImageBBoxEditor
              imageSrc={reviewOrigImageBlobUrl}
              boxes={reviewBoxes}
              onBoxesChange={setReviewBoxes}
              onBoxesCommit={handleReviewBoxesCommit}
              getTypeConfig={getVisionTypeMeta}
              availableTypes={pipelines.flatMap(p => p.types.filter(tt => tt.enabled))}
              defaultType="CUSTOM"
            />
          </div>
        </div>
      </div>

      {/* Column 2: Redacted preview */}
      <div className="flex-[2] min-w-0 flex flex-col border-r overflow-hidden">
        <div className="shrink-0 flex items-center gap-1.5 px-2 py-1.5 border-b bg-muted/30">
          <span className="text-xs font-medium">{t('batchWizard.step4.previewImage')}</span>
          <span className="ml-auto text-xs text-muted-foreground">
            {reviewImagePreviewLoading
              ? t('batchWizard.step4.generating')
              : `${selectedReviewBoxCount}/${reviewBoxes.length} ${t('batchWizard.step4.selected')}`}
          </span>
        </div>
        <div className="flex-1 min-h-0 overflow-auto bg-muted/20 flex items-center justify-center">
          {reviewImagePreviewSrc ? (
            <img src={reviewImagePreviewSrc} alt={t('batchWizard.step4.previewImage')} className="max-w-full max-h-full object-contain" />
          ) : (
            <p className="text-sm text-muted-foreground">
              {reviewImagePreviewLoading ? t('batchWizard.step4.generating') : t('batchWizard.step4.noBoxes')}
            </p>
          )}
        </div>
      </div>

      {/* Column 3: Detection list */}
      <div className="flex-[1] min-w-[220px] max-w-[320px] min-h-0 flex flex-col bg-background">
        <div className="shrink-0 flex items-center px-2 py-1.5 border-b">
          <span className="text-xs font-medium">{t('batchWizard.step4.detectionRegions')}</span>
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {selectedReviewBoxCount}/{reviewBoxes.length}
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-1.5 overflow-y-auto p-2">
          {reviewBoxes.map(box => {
            const meta = getVisionTypeMeta(box.type);
            return (
              <button
                key={box.id}
                type="button"
                onClick={() => toggleReviewBoxSelected(box.id)}
                className="w-full text-left rounded-lg border px-2.5 py-1.5 transition hover:border-muted-foreground/40"
                style={{
                  borderColor: box.selected !== false ? meta.color : undefined,
                  backgroundColor: box.selected === false ? undefined : `${meta.color}0d`,
                }}
                data-testid={`bbox-toggle-${box.id}`}
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={box.selected !== false}
                    onCheckedChange={() => toggleReviewBoxSelected(box.id)}
                  />
                  <span className="text-xs font-medium truncate" style={{ color: meta.color }}>
                    {meta.name}
                  </span>
                  <span className="text-xs text-muted-foreground ml-auto shrink-0">
                    {Math.round(box.width * 100)}&times;{Math.round(box.height * 100)}%
                  </span>
                </div>
                {box.text && (
                  <p className="mt-0.5 text-xs text-muted-foreground truncate pl-6">{box.text}</p>
                )}
              </button>
            );
          })}
          {reviewBoxes.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-8">
              {t('batchWizard.step4.noBoxes')}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
