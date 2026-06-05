// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useT } from '@/i18n';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

interface SettingsOnboardingPanelProps {
  regexCount: number;
  semanticCount: number;
  ocrCount: number;
  imageCount: number;
  onOpenTextRules: () => void;
  onOpenVisionRules: () => void;
}

export function SettingsOnboardingPanel({
  regexCount,
  semanticCount,
  ocrCount,
  imageCount,
  onOpenTextRules,
  onOpenVisionRules,
}: SettingsOnboardingPanelProps) {
  const t = useT();
  const textCount = regexCount + semanticCount;
  const visionCount = ocrCount + imageCount;

  return (
    <section
      className="shrink-0 rounded-xl border border-border/70 bg-card px-3 py-2.5 shadow-[var(--shadow-control)]"
      data-testid="settings-onboarding-panel"
      aria-label={t('settings.overview.onboardingAria')}
    >
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="max-w-4xl space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="secondary" className="rounded-full">
              {t('settings.redaction.systemDefault')}
            </Badge>
            <span className="text-xs font-medium text-muted-foreground">
              {t('settings.redaction.defaultOption')}
            </span>
          </div>
          <div>
            <h2 className="text-lg font-semibold tracking-[-0.02em]">
              {t('settings.overview.onboardingTitle')}
            </h2>
            <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {t('settings.overview.onboardingDesc')
                .replace('{textPreset}', t('settings.redaction.defaultNameText'))
                .replace('{visionPreset}', t('settings.redaction.defaultNameVision'))}
            </p>
          </div>
        </div>

        <div className="grid min-w-[220px] grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <p className="font-medium">{t('settings.textRules')}</p>
            <p className="mt-1 text-muted-foreground">
              {t('settings.overview.countSummary')
                .replace('{count}', String(textCount))
                .replace('{left}', t('settings.regex'))
                .replace('{right}', t('settings.semantic'))}
            </p>
          </div>
          <div className="rounded-lg border border-border/70 bg-muted/20 px-2.5 py-1.5">
            <p className="font-medium">{t('settings.visionRules')}</p>
            <p className="mt-1 text-muted-foreground">
              {t('settings.overview.countSummary')
                .replace('{count}', String(visionCount))
                .replace('{left}', t('settings.pipelineDisplayName.ocr'))
                .replace('{right}', t('settings.pipelineDisplayName.image'))}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-3">
        <GuideItem
          title={t('settings.overview.defaultCoverageTitle')}
          description={t('settings.overview.defaultCoverageDesc').replace(
            '{createPreset}',
            t('settings.redaction.createPreset'),
          )}
        />
        <GuideItem
          title={t('settings.overview.reviewTitle')}
          description={t('settings.overview.reviewDesc').replace(
            '{paperHint}',
            t('settings.redaction.imageGroupHint'),
          )}
        />
        <div className="rounded-lg border border-border/70 bg-muted/15 px-2.5 py-2">
          <h3 className="text-sm font-semibold">{t('settings.overview.advancedAreaTitle')}</h3>
          <p className="mt-0.5 line-clamp-2 text-xs leading-4 text-muted-foreground">
            {t('settings.overview.advancedAreaDesc').replace(
              '{regex}',
              t('settings.regex'),
            )}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              onClick={onOpenTextRules}
            >
              {t('settings.textRules')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              onClick={onOpenVisionRules}
            >
              {t('settings.visionRules')}
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}

function GuideItem({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-lg border border-border/70 bg-muted/15 px-2.5 py-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-0.5 line-clamp-2 text-xs leading-4 text-muted-foreground">{description}</p>
    </div>
  );
}
