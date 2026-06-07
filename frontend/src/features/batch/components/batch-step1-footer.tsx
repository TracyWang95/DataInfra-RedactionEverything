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
  configLocked?: boolean;
  advanceToUploadStep: () => void;
}

function BatchStep1FooterInner({
  confirmStep1,
  setConfirmStep1,
  isStep1Complete,
  jobPriority,
  setJobPriority,
  configLocked = false,
  advanceToUploadStep,
}: BatchStep1FooterProps) {
  const t = useT();

  return (
    <div className="page-surface-footer !px-3 !py-2">
      <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,34rem)]">
        <div className="surface-subtle flex items-center justify-between gap-3 px-3 py-1.5">
          <span className="truncate text-sm text-muted-foreground">
            {t('batchWizard.step1.priority')}
          </span>
          <Select
            value={String(jobPriority)}
            onValueChange={(v) => setJobPriority(Number(v))}
            disabled={configLocked}
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

        <div className="surface-subtle flex flex-col gap-1.5 px-3 py-1.5 xl:flex-row xl:items-center xl:justify-between">
          <label className="flex min-w-0 cursor-pointer items-start gap-2 text-sm xl:flex-1">
            <Checkbox
              checked={confirmStep1}
              onCheckedChange={(v) => setConfirmStep1(v === true)}
              disabled={configLocked}
              className="mt-0.5"
              data-testid="confirm-step1"
            />
            <span className="truncate">{t('batchWizard.step1.confirm')}</span>
          </label>
          <Button
            className="w-full whitespace-nowrap xl:w-auto xl:shrink-0"
            disabled={!isStep1Complete || configLocked}
            onClick={() => advanceToUploadStep()}
            data-testid="advance-upload"
          >
            {t('batchWizard.step1.nextUpload')}
          </Button>
          {configLocked ? (
            <p className="text-xs leading-snug text-muted-foreground xl:max-w-40">
              {t('batchWizard.step1.lockedHint')}
            </p>
          ) : null}
        </div>
      </div>

      <p className="mt-1 text-[11px] leading-tight text-muted-foreground">
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
