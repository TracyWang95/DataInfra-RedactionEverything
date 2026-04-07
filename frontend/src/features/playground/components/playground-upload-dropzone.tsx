// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import type { FC } from 'react';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import type { usePlayground } from '../hooks/use-playground';

type PlaygroundCtx = ReturnType<typeof usePlayground>;

interface PlaygroundUploadDropzoneProps {
  dropzone: PlaygroundCtx['dropzone'];
}

export const PlaygroundUploadDropzone: FC<PlaygroundUploadDropzoneProps> = ({ dropzone }) => {
  const t = useT();
  const { getRootProps, getInputProps, isDragActive, open } = dropzone;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 items-stretch justify-center">
      <div className="flex h-full w-full max-w-[56rem] flex-col items-center pt-0.5 text-center lg:pt-1">
        <div className="mb-5 flex w-full max-w-3xl flex-col items-center">
          <p className="mb-3 text-xs font-medium uppercase tracking-[0.2em] text-primary/70">
            {t('playground.upload.kicker')}
          </p>
          <h2 className="bg-gradient-to-b from-foreground to-foreground/70 bg-clip-text text-center text-[2rem] font-bold leading-[1.15] tracking-[-0.04em] text-transparent lg:text-[2.25rem]">
            {t('playground.upload.title')}
          </h2>
          <p className="mt-3 max-w-xl text-center text-[15px] leading-relaxed text-muted-foreground">
            {t('playground.upload.desc')}
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 text-[10px] tracking-wide text-muted-foreground/45">
            {t('playground.upload.standards').split(' · ').map((s, i, a) => (
              <span key={s}>{s}{i < a.length - 1 && <span className="ml-1.5 text-border">·</span>}</span>
            ))}
          </div>
        </div>

        <div
          {...getRootProps({ onClick: (e) => { e.stopPropagation(); open(); } })}
          aria-label={t('playground.dropHere')}
          className={cn(
            'saas-hero group relative min-h-[18rem] flex-1 w-full cursor-pointer border-2 border-dashed p-10 text-center transition-all duration-300 ease-out lg:px-12',
            isDragActive
              ? 'border-primary bg-primary/[0.04] ring-4 ring-primary/10'
              : 'border-border hover:border-foreground/15 hover:shadow-lg',
          )}
          data-testid="playground-dropzone"
        >
          <input {...getInputProps()} />
          <div className="flex h-full flex-col items-center justify-center">
            <div
              className={cn(
                'mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[20px] bg-foreground text-background transition-transform duration-300 group-hover:scale-110',
                isDragActive && 'scale-110 animate-pulse',
              )}
            >
              <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            <p className="mb-1.5 text-lg font-semibold tracking-[-0.02em]">
              {t('playground.dropHere')}
            </p>
            <p className="mb-5 text-sm text-muted-foreground">
              {t('playground.supportedFormats')}
            </p>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); open(); }}
              className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-card px-4 py-2 text-xs font-medium text-foreground hover:bg-accent/40 transition-colors"
            >
              <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              {t('playground.clickToUpload')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
