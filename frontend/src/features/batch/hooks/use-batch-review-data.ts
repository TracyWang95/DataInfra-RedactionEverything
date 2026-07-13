// Copyright 2026 DataInfra-RedactionEverything Contributors

import type { BoundingBox as EditorBox } from '@/components/ImageBBoxEditor';
import type { BatchWizardPersistedConfig } from '@/services/batchPipeline';
import type {
  BatchRow,
  ReviewEntity,
  ReviewVisionPageQuality,
  Step,
  TextEntityType,
} from '../types';
import { useReviewDraft } from './use-batch-review-draft';
import { useReviewOrigImage } from './use-batch-review-orig-image';
import { useReviewImagePreview, useReviewTextPreviewMap } from './use-batch-review-preview';
import { useReviewRerun } from './use-batch-review-rerun';

export interface ReviewDataDeps {
  step: Step;
  reviewFile: BatchRow | null;
  activeJobId: string | null;
  itemIdByFileIdRef: React.MutableRefObject<Record<string, string>>;
  cfg: BatchWizardPersistedConfig;
  isPreviewMode: boolean;
  textTypes: TextEntityType[];
  reviewEntities: ReviewEntity[];
  reviewBoxes: EditorBox[];
  visibleReviewBoxes: EditorBox[];
  reviewCurrentPage: number;
  reviewTotalPages: number;
  reviewItemId: string | undefined;
  reviewLoading: boolean;
  reviewTextContent: string;
  previewEntityMap: Record<string, string>;
  reviewDraftInitializedRef: React.MutableRefObject<boolean>;
  reviewDraftDirtyRef: React.MutableRefObject<boolean>;
  reviewLastSavedJsonRef: React.MutableRefObject<string>;
  reviewAutosaveTimerRef: React.MutableRefObject<number | null>;
  setReviewLoading: React.Dispatch<React.SetStateAction<boolean>>;
  setPreviewEntityMap: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setReviewImagePreview: React.Dispatch<React.SetStateAction<string>>;
  setReviewDraftError: React.Dispatch<React.SetStateAction<string | null>>;
  setReviewLoadError: React.Dispatch<React.SetStateAction<string | null>>;
  setReviewEntities: React.Dispatch<React.SetStateAction<ReviewEntity[]>>;
  setReviewBoxes: React.Dispatch<React.SetStateAction<EditorBox[]>>;
  setReviewCurrentPage: React.Dispatch<React.SetStateAction<number>>;
  setReviewTotalPages: React.Dispatch<React.SetStateAction<number>>;
  setReviewPages: React.Dispatch<React.SetStateAction<string[]>>;
  setReviewVisionQualityByPage: React.Dispatch<
    React.SetStateAction<Record<number, ReviewVisionPageQuality>>
  >;
  setReviewTextContent: React.Dispatch<React.SetStateAction<string>>;
  setReviewOrigImageBlobUrl: React.Dispatch<React.SetStateAction<string>>;
  setReviewTextUndoStack: React.Dispatch<React.SetStateAction<ReviewEntity[][]>>;
  setReviewTextRedoStack: React.Dispatch<React.SetStateAction<ReviewEntity[][]>>;
  setReviewImageUndoStack: React.Dispatch<React.SetStateAction<EditorBox[][]>>;
  setReviewImageRedoStack: React.Dispatch<React.SetStateAction<EditorBox[][]>>;
  buildCurrentReviewDraftPayload: () => {
    entities: Array<Record<string, unknown>>;
    bounding_boxes: Array<Record<string, unknown>>;
  };
  flushCurrentReviewDraft: () => Promise<boolean>;
  setMsg: (msg: { text: string; tone: 'neutral' | 'ok' | 'warn' | 'err' } | null) => void;
}

export interface ReviewDataState {
  loadReviewData: (fileId: string, isImage: boolean) => Promise<void>;
  rerunCurrentItemRecognition: () => Promise<void>;
  rerunRecognitionLoading: boolean;
  reviewImagePreviewLoading: boolean;
}

export function useBatchReviewData(deps: ReviewDataDeps): ReviewDataState {
  useReviewOrigImage(deps);
  const { loadReviewData } = useReviewDraft(deps);
  const { rerunCurrentItemRecognition, rerunRecognitionLoading } = useReviewRerun(deps);
  useReviewTextPreviewMap(deps);
  const { reviewImagePreviewLoading } = useReviewImagePreview(deps);

  return {
    loadReviewData,
    rerunCurrentItemRecognition,
    rerunRecognitionLoading,
    reviewImagePreviewLoading,
  };
}
