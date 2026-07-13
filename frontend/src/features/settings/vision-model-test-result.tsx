// Copyright 2026 DataInfra-RedactionEverything Contributors

import { cn } from '@/lib/utils';
import { tonePanelClass } from '@/utils/toneClasses';

export interface VisionModelTestResultProps {
  testResult: { success: boolean; message: string };
}

export function VisionModelTestResult({ testResult }: VisionModelTestResultProps) {
  return (
    <div
      className={cn(
        'mx-5 mb-4 rounded-lg border p-3 text-sm',
        testResult.success ? tonePanelClass.success : tonePanelClass.danger,
      )}
    >
      {testResult.success ? '\u2713 ' : '\u2717 '}
      {testResult.message}
    </div>
  );
}
