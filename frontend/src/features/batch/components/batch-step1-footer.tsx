// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { memo } from 'react';

import { Link } from 'react-router-dom';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export interface BatchStep1FooterProps {
  confirmStep1: boolean;
  setConfirmStep1: (v: boolean) => void;
  isStep1Complete: boolean;
  jobPriority: number;
  setJobPriority: (v: number) => void;
  advanceToUploadStep: () => void;
}

function BatchStep1FooterInner({
  confirmStep1,
  setConfirmStep1,
  isStep1Complete,
  jobPriority,
  setJobPriority,
  advanceToUploadStep,
}: BatchStep1FooterProps) {
  const t = useT();

  return (
    <div className="page-surface-footer">
      <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
        <div className="surface-subtle flex items-center justify-between gap-3 px-3 py-1.5">
          <span className="text-sm text-muted-foreground">
            {t('batchWizard.step1.priority')}
          </span>
          <Select
            value={String(jobPriority)}
            onValueChange={v => setJobPriority(Number(v))}
          >
            <SelectTrigger className="w-24 text-xs" data-testid="priority-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">{t('batchWizard.step1.priorityNormal')}</SelectItem>
              <SelectItem value="5">{t('batchWizard.step1.priorityHigh')}</SelectItem>
              <SelectItem value="10">{t('batchWizard.step1.priorityUrgent')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="surface-subtle flex flex-col gap-1.5 px-3 py-1.5">
          <label className="flex cursor-pointer items-start gap-2 text-sm">
            <Checkbox
              checked={confirmStep1}
              onCheckedChange={v => setConfirmStep1(v === true)}
              className="mt-0.5"
              data-testid="confirm-step1"
            />
            <span>{t('batchWizard.step1.confirm')}</span>
          </label>
          <Button
            className="w-full"
            disabled={!isStep1Complete}
            onClick={() => advanceToUploadStep()}
            data-testid="advance-upload"
          >
            {t('batchWizard.step1.nextUpload')}
          </Button>
        </div>
      </div>

      <p className="mt-1 text-xs text-muted-foreground">
        <Link to="/jobs" className="text-primary hover:underline font-medium">
          {t('batchHub.jobCenter')}
        </Link>
        <span className="mx-1">&middot;</span>
        <Link to="/history" className="text-primary hover:underline font-medium">
          {t('batchHub.history')}
        </Link>
      </p>
    </div>
  );
}

export const BatchStep1Footer = memo(BatchStep1FooterInner);
