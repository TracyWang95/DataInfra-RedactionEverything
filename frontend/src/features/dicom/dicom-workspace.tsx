// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronRight,
  Download,
  FileScan,
  FolderOpen,
  Images,
  LoaderCircle,
  Play,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Tags,
  Upload,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { showToast } from '@/components/Toast';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { useT } from '@/i18n';
import { cn } from '@/lib/utils';
import {
  anonymizeDicomBatch,
  anonymizeDicomStudy,
  downloadDicomBatchExport,
  downloadDicomExport,
  getDicomCapabilities,
  getDicomJob,
  getDicomMetadata,
  getDicomPreviewUrl,
  getDicomRisks,
  getDicomStudy,
  ingestDicom,
  listDicomStudies,
  preflightDicomStudy,
  releaseDicomPreviewUrl,
  reviewDicomStudy,
  type DicomInstance,
  type DicomJob,
  type DicomMetadataEntry,
  type DicomPreflightResponse,
  type DicomProfile,
  type DicomReport,
  type DicomRisk,
  type DicomRiskSeverity,
  type DicomSeries,
  type DicomStudy,
  getDicomReport,
} from '@/services/dicomApi';

const PROFILE_OPTIONS: Array<{ value: DicomProfile; labelKey: string; descriptionKey: string }> = [
  {
    value: 'basic',
    labelKey: 'dicom.profile.basic',
    descriptionKey: 'dicom.profile.basicDesc',
  },
  {
    value: 'research_strict',
    labelKey: 'dicom.profile.strict',
    descriptionKey: 'dicom.profile.strictDesc',
  },
  {
    value: 'longitudinal',
    labelKey: 'dicom.profile.longitudinal',
    descriptionKey: 'dicom.profile.longitudinalDesc',
  },
  {
    value: 'longitudinal_research',
    labelKey: 'dicom.profile.longitudinalResearch',
    descriptionKey: 'dicom.profile.longitudinalResearchDesc',
  },
  {
    value: 'internal_pseudonymized',
    labelKey: 'dicom.profile.internal',
    descriptionKey: 'dicom.profile.internalDesc',
  },
  {
    value: 'ai_training',
    labelKey: 'dicom.profile.aiTraining',
    descriptionKey: 'dicom.profile.aiTrainingDesc',
  },
];

type AsyncAction =
  | 'ingest'
  | 'refresh'
  | 'preflight'
  | 'batch-preflight'
  | 'anonymize'
  | 'batch-anonymize'
  | null;

export function DicomWorkspace() {
  const t = useT();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [profile, setProfile] = useState<DicomProfile>('research_strict');
  const [supportedProfiles, setSupportedProfiles] = useState<DicomProfile[]>(
    PROFILE_OPTIONS.map((option) => option.value),
  );
  const [pixelRedactionEnabled, setPixelRedactionEnabled] = useState(false);
  const [studies, setStudies] = useState<DicomStudy[]>([]);
  const [selectedStudyIds, setSelectedStudyIds] = useState<Set<string>>(new Set());
  const [activeStudyId, setActiveStudyId] = useState<string | null>(null);
  const [study, setStudy] = useState<DicomStudy | null>(null);
  const [metadata, setMetadata] = useState<DicomMetadataEntry[]>([]);
  const [risks, setRisks] = useState<DicomRisk[]>([]);
  const [preflights, setPreflights] = useState<Record<string, DicomPreflightResponse>>({});
  const [jobs, setJobs] = useState<Record<string, DicomJob>>({});
  const [reports, setReports] = useState<Record<string, DicomReport>>({});
  const [latestBatchId, setLatestBatchId] = useState<string | null>(null);
  const [activeSeriesId, setActiveSeriesId] = useState<string | null>(null);
  const [activeInstanceId, setActiveInstanceId] = useState<string | null>(null);
  const [frame, setFrame] = useState(0);
  const [windowCenter, setWindowCenter] = useState('');
  const [windowWidth, setWindowWidth] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [action, setAction] = useState<AsyncAction>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  const refreshStudies = useCallback(async (silent = false) => {
    if (!silent) setAction('refresh');
    try {
      const response = await listDicomStudies({ limit: 200 });
      setStudies(response.studies);
      const restoredJobs = Object.fromEntries(
        response.studies
          .filter((item) => item.latest_job)
          .map((item) => [item.study_id, item.latest_job as DicomJob]),
      );
      setJobs(restoredJobs);
      setLatestBatchId(
        response.studies.find((item) => item.latest_job?.batch_id)?.latest_job?.batch_id ?? null,
      );
      setReports({});
      const completedJobs = Object.values(restoredJobs).filter(
        (job) => job.status === 'completed',
      );
      void Promise.allSettled(completedJobs.map((job) => getDicomReport(job.job_id))).then(
        (results) => {
          const restoredReports: Record<string, DicomReport> = {};
          results.forEach((result, index) => {
            if (result.status === 'fulfilled') {
              restoredReports[completedJobs[index].study_id] = result.value;
            }
          });
          setReports(restoredReports);
        },
      );
      setPageError(null);
      setActiveStudyId((current) => current ?? response.studies[0]?.study_id ?? null);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!silent) setAction(null);
    }
  }, []);

  useEffect(() => {
    void refreshStudies(true);
  }, [refreshStudies]);

  useEffect(() => {
    let cancelled = false;
    void getDicomCapabilities()
      .then((capabilities) => {
        if (cancelled) return;
        setPixelRedactionEnabled(
          capabilities.pixel_redaction.enabled && capabilities.pixel_redaction.automatic,
        );
        if (capabilities.profiles.length === 0) return;
        setSupportedProfiles(capabilities.profiles);
        setProfile((current) =>
          capabilities.profiles.includes(current) ? current : capabilities.profiles[0],
        );
      })
      .catch(() => {
        // Older compatible backends may not expose capabilities; retain safe local defaults.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeStudyId) {
      setStudy(null);
      setMetadata([]);
      setRisks([]);
      setActiveSeriesId(null);
      setActiveInstanceId(null);
      return;
    }
    setStudy(null);
    setMetadata([]);
    setRisks([]);
    setActiveSeriesId(null);
    setActiveInstanceId(null);
    let cancelled = false;
    Promise.all([
      getDicomStudy(activeStudyId),
      getDicomMetadata(activeStudyId),
      getDicomRisks(activeStudyId),
    ])
      .then(([detail, metadataResponse, riskResponse]) => {
        if (cancelled) return;
        setStudy(detail);
        setMetadata(metadataResponse.entries);
        setRisks(riskResponse.risks);
        const firstSeries = detail.series?.[0] ?? null;
        setActiveSeriesId((current) =>
          detail.series?.some((series) => series.series_id === current)
            ? current
            : (firstSeries?.series_id ?? null),
        );
        setPageError(null);
      })
      .catch((error) => {
        if (!cancelled) setPageError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      cancelled = true;
    };
  }, [activeStudyId]);

  const activeSeries = useMemo(
    () => study?.series?.find((series) => series.series_id === activeSeriesId) ?? null,
    [activeSeriesId, study],
  );

  useEffect(() => {
    const firstInstance = activeSeries?.instances?.[0] ?? null;
    setActiveInstanceId((current) =>
      activeSeries?.instances?.some((instance) => instance.instance_id === current)
        ? current
        : (firstInstance?.instance_id ?? null),
    );
    setFrame(0);
  }, [activeSeries]);

  const activeInstance = useMemo(
    () =>
      activeSeries?.instances?.find((instance) => instance.instance_id === activeInstanceId) ??
      null,
    [activeInstanceId, activeSeries],
  );

  useEffect(() => {
    let cancelled = false;
    const previous = previewUrl;
    if (
      !activeStudyId ||
      study?.study_id !== activeStudyId ||
      !activeInstance ||
      activeInstance.instance_id !== activeInstanceId
    ) {
      setPreviewUrl(null);
      setPreviewError(null);
      releaseDicomPreviewUrl(previous);
      return;
    }
    setLoadingPreview(true);
    setPreviewError(null);
    getDicomPreviewUrl({
      studyId: activeStudyId,
      instanceId: activeInstance.instance_id,
      frame,
      windowCenter: parseOptionalNumber(windowCenter),
      windowWidth: parseOptionalNumber(windowWidth),
    })
      .then((url) => {
        if (cancelled) {
          releaseDicomPreviewUrl(url);
          return;
        }
        setPreviewUrl(url);
        releaseDicomPreviewUrl(previous);
      })
      .catch((error) => {
        if (cancelled) return;
        setPreviewUrl(null);
        releaseDicomPreviewUrl(previous);
        setPreviewError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setLoadingPreview(false);
      });
    return () => {
      cancelled = true;
    };
    // Window values are applied explicitly with the refresh button to avoid decoding on each keypress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeInstance, activeInstanceId, activeStudyId, frame, study?.study_id]);

  useEffect(
    () => () => {
      releaseDicomPreviewUrl(previewUrl);
    },
    [previewUrl],
  );

  useEffect(() => {
    const activeJobs = Object.values(jobs).filter((job) =>
      ['queued', 'running'].includes(job.status),
    );
    if (activeJobs.length === 0) return;
    const timer = window.setInterval(() => {
      void Promise.all(activeJobs.map((job) => getDicomJob(job.job_id)))
        .then((updates) => {
          setJobs((current) => {
            const next = { ...current };
            updates.forEach((job) => {
              next[job.study_id] = job;
            });
            return next;
          });
          updates
            .filter((job) => job.status === 'completed')
            .forEach((job) => {
              void getDicomReport(job.job_id)
                .then((report) =>
                  setReports((current) => ({ ...current, [job.study_id]: report })),
                )
                .catch((error) =>
                  setPageError(error instanceof Error ? error.message : String(error)),
                );
            });
        })
        .catch((error) => setPageError(error instanceof Error ? error.message : String(error)));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const metrics = useMemo(() => {
    const instanceCount = studies.reduce((sum, item) => sum + item.instance_count, 0);
    const unresolvedHighRisk = studies.reduce((sum, item) => sum + item.risk_summary.blocking, 0);
    const completed = Object.values(jobs).filter((job) => job.status === 'completed').length;
    return { instanceCount, unresolvedHighRisk, completed };
  }, [jobs, studies]);

  const latestBatchJobs = useMemo(
    () =>
      latestBatchId
        ? Object.values(jobs).filter((job) => job.batch_id === latestBatchId)
        : [],
    [jobs, latestBatchId],
  );

  const selectedCount = selectedStudyIds.size;
  const restorePreflight = useCallback(
    (studyId: string): DicomPreflightResponse | undefined => {
      const candidate =
        study?.study_id === studyId ? study : studies.find((item) => item.study_id === studyId);
      if (!candidate?.preflight_version || !candidate.profile || candidate.profile !== profile) {
        return undefined;
      }
      return {
        study_id: studyId,
        profile,
        preflight_version: candidate.preflight_version,
        export_allowed: candidate.risk_summary.blocking === 0,
        risk_summary: candidate.risk_summary,
        risks: candidate.study_id === activeStudyId ? risks : [],
      };
    },
    [activeStudyId, profile, risks, studies, study],
  );
  const currentPreflight = activeStudyId
    ? (preflights[activeStudyId] ?? restorePreflight(activeStudyId))
    : undefined;
  const currentJob = activeStudyId ? jobs[activeStudyId] : undefined;
  const currentReport = activeStudyId ? reports[activeStudyId] : undefined;

  const handleFiles = (incoming: File[]) => {
    const accepted = incoming.filter(isDicomCandidate);
    const rejected = incoming.length - accepted.length;
    if (rejected > 0) showToast(t('dicom.upload.rejected'), 'error');
    setFiles(accepted);
  };

  const handleIngest = async () => {
    if (files.length === 0) return;
    const archives = files.filter((file) => file.name.toLowerCase().endsWith('.zip'));
    if (archives.length > 0 && files.length !== 1) {
      showToast(t('dicom.upload.archiveExclusive'), 'error');
      return;
    }
    setAction('ingest');
    try {
      const response = await ingestDicom({
        profile,
        archive: archives[0],
        files: archives.length === 0 ? files : undefined,
        idempotencyKey: crypto.randomUUID(),
      });
      setStudies((current) => mergeStudies(current, response.studies));
      setSelectedStudyIds(new Set(response.studies.map((item) => item.study_id)));
      setActiveStudyId(response.studies[0]?.study_id ?? null);
      setFiles([]);
      showToast(
        t('dicom.upload.success')
          .replace('{studies}', String(response.study_count))
          .replace('{instances}', String(response.instance_count)),
        'success',
      );
    } catch (error) {
      showToast(error, 'error');
    } finally {
      setAction(null);
    }
  };

  const runPreflight = async (studyId: string) => {
    const response = await preflightDicomStudy(studyId, { profile });
    setPreflights((current) => ({ ...current, [studyId]: response }));
    const applyPreflight = (item: DicomStudy): DicomStudy =>
      item.study_id === studyId
        ? {
            ...item,
            profile: response.profile,
            preflight_version: response.preflight_version,
            risk_summary: response.risk_summary,
          }
        : item;
    setStudies((current) => current.map(applyPreflight));
    setStudy((current) => (current ? applyPreflight(current) : current));
    return response;
  };

  const handlePreflight = async () => {
    if (!activeStudyId) return;
    setAction('preflight');
    try {
      await runPreflight(activeStudyId);
      await refreshStudyRisks(activeStudyId, setRisks);
      showToast(t('dicom.preflight.complete'), 'success');
    } catch (error) {
      showToast(error, 'error');
    } finally {
      setAction(null);
    }
  };

  const handleBatchPreflight = async () => {
    if (selectedCount === 0) return;
    setAction('batch-preflight');
    try {
      const results = await Promise.allSettled([...selectedStudyIds].map(runPreflight));
      const failed = results.filter((result) => result.status === 'rejected').length;
      showToast(
        t('dicom.preflight.batchComplete')
          .replace('{success}', String(results.length - failed))
          .replace('{failed}', String(failed)),
        failed ? 'info' : 'success',
      );
      if (activeStudyId && selectedStudyIds.has(activeStudyId)) {
        await refreshStudyRisks(activeStudyId, setRisks);
      }
    } catch (error) {
      showToast(error, 'error');
    } finally {
      setAction(null);
    }
  };

  const startAnonymization = async (studyId: string) => {
    const preflight =
      preflights[studyId] ?? restorePreflight(studyId) ?? (await runPreflight(studyId));
    if (!preflight.export_allowed) {
      throw new Error(t('dicom.anonymize.reviewRequired'));
    }
    const job = await anonymizeDicomStudy(
      studyId,
      {
        profile,
        expected_preflight_version: preflight.preflight_version,
      },
      crypto.randomUUID(),
    );
    setJobs((current) => ({ ...current, [studyId]: job }));
    return job;
  };

  const handleAnonymize = async () => {
    if (!activeStudyId) return;
    setAction('anonymize');
    try {
      await startAnonymization(activeStudyId);
      showToast(t('dicom.anonymize.started'), 'success');
    } catch (error) {
      showToast(error, 'error');
    } finally {
      setAction(null);
    }
  };

  const handleBatchAnonymize = async () => {
    if (selectedCount === 0) return;
    setAction('batch-anonymize');
    try {
      const studyIds = [...selectedStudyIds];
      const preflightResults = await Promise.all(
        studyIds.map(
          async (studyId) =>
            preflights[studyId] ?? restorePreflight(studyId) ?? runPreflight(studyId),
        ),
      );
      if (preflightResults.some((item) => !item.export_allowed)) {
        throw new Error(t('dicom.anonymize.reviewRequired'));
      }
      const batch = await anonymizeDicomBatch(
        {
          study_ids: studyIds,
          profile,
          expected_preflight_versions: Object.fromEntries(
            preflightResults.map((item) => [item.study_id, item.preflight_version]),
          ),
        },
        crypto.randomUUID(),
      );
      setLatestBatchId(batch.batch_id);
      setJobs((current) => ({
        ...current,
        ...Object.fromEntries(batch.jobs.map((job) => [job.study_id, job])),
      }));
      showToast(
        t('dicom.anonymize.batchStarted')
          .replace('{success}', String(batch.jobs.length))
          .replace('{failed}', '0'),
        'success',
      );
    } catch (error) {
      showToast(error, 'error');
    } finally {
      setAction(null);
    }
  };

  const handleExport = async () => {
    if (!currentJob) return;
    try {
      await downloadDicomExport(currentJob.job_id);
    } catch (error) {
      showToast(error, 'error');
    }
  };

  const handleBatchExport = async () => {
    if (!latestBatchId) return;
    try {
      await downloadDicomBatchExport(latestBatchId);
    } catch (error) {
      showToast(error, 'error');
    }
  };

  const handleReview = async (
    risk: DicomRisk,
    resolution: 'resolved' | 'accepted',
    note = '',
  ): Promise<boolean> => {
    if (!activeStudyId) return false;
    try {
      const review = await reviewDicomStudy(activeStudyId, [
        { risk_id: risk.risk_id, resolution, note },
      ]);
      const [riskResponse, detail] = await Promise.all([
        getDicomRisks(activeStudyId),
        getDicomStudy(activeStudyId),
      ]);
      setRisks(riskResponse.risks);
      setStudy(detail);
      setStudies((current) => mergeStudies(current, [detail]));
      setPreflights((current) => {
        const existing = current[activeStudyId];
        if (!existing) return current;
        return {
          ...current,
          [activeStudyId]: {
            ...existing,
            risks: riskResponse.risks,
            risk_summary: review.risk_summary,
            export_allowed: review.export_allowed,
          },
        };
      });
      showToast(t('dicom.review.saved'), 'success');
      return true;
    } catch (error) {
      showToast(error, 'error');
      return false;
    }
  };

  const handlePreviewRefresh = async () => {
    if (!activeStudyId || !activeInstanceId) return;
    setLoadingPreview(true);
    setPreviewError(null);
    try {
      const nextUrl = await getDicomPreviewUrl({
        studyId: activeStudyId,
        instanceId: activeInstanceId,
        frame,
        windowCenter: parseOptionalNumber(windowCenter),
        windowWidth: parseOptionalNumber(windowWidth),
      });
      setPreviewUrl((current) => {
        releaseDicomPreviewUrl(current);
        return nextUrl;
      });
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingPreview(false);
    }
  };

  const toggleStudy = (studyId: string, checked: boolean) => {
    setSelectedStudyIds((current) => {
      const next = new Set(current);
      if (checked) next.add(studyId);
      else next.delete(studyId);
      return next;
    });
  };

  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,2200px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
          <header className="flex flex-none flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="saas-kicker">DICOM PS3.15</span>
                {pixelRedactionEnabled ? (
                  <Badge variant="outline" className="gap-1 border-emerald-500/40 text-emerald-700">
                    <ScanLine className="size-3" />
                    {t('dicom.pixelRedaction.enabled')}
                  </Badge>
                ) : null}
              </div>
              <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">
                {t('dicom.title')}
              </h1>
              <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
                {t('dicom.description')}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button
                variant="outline"
                onClick={() => void refreshStudies()}
                disabled={action != null}
              >
                <RefreshCw
                  data-icon="inline-start"
                  className={cn(action === 'refresh' && 'animate-spin')}
                />
                {t('common.refresh')}
              </Button>
              <Button onClick={() => fileInputRef.current?.click()}>
                <Upload data-icon="inline-start" />
                {t('dicom.upload.choose')}
              </Button>
            </div>
          </header>

          {pageError ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertTitle>{t('dicom.error.title')}</AlertTitle>
              <AlertDescription>{pageError}</AlertDescription>
            </Alert>
          ) : null}

          <section className="grid flex-none gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard icon={Images} label={t('dicom.metric.studies')} value={studies.length} />
            <MetricCard
              icon={FileScan}
              label={t('dicom.metric.instances')}
              value={metrics.instanceCount}
            />
            <MetricCard
              icon={AlertTriangle}
              label={t('dicom.metric.highRisk')}
              value={metrics.unresolvedHighRisk}
              destructive={metrics.unresolvedHighRisk > 0}
            />
            <MetricCard
              icon={ShieldCheck}
              label={t('dicom.metric.completed')}
              value={metrics.completed}
            />
          </section>

          <main className="min-h-0 flex-1 overflow-auto pr-1">
            <Tabs defaultValue="workbench" className="flex min-h-full flex-col gap-2">
              <TabsList className="w-fit flex-none">
                <TabsTrigger value="workbench">{t('dicom.tab.workbench')}</TabsTrigger>
                <TabsTrigger value="metadata">{t('dicom.tab.metadata')}</TabsTrigger>
                <TabsTrigger value="workflow">{t('dicom.tab.workflow')}</TabsTrigger>
              </TabsList>

              <TabsContent value="workbench" className="min-h-0 flex-1">
                <div className="grid min-h-[620px] gap-3 xl:grid-cols-[21rem_minmax(32rem,1fr)_25rem]">
                  <StudyQueueCard
                    studies={studies}
                    activeStudyId={activeStudyId}
                    selectedStudyIds={selectedStudyIds}
                    onActivate={setActiveStudyId}
                    onToggle={toggleStudy}
                  />
                  <ViewerCard
                    study={study}
                    series={study?.series ?? []}
                    activeSeries={activeSeries}
                    activeSeriesId={activeSeriesId}
                    activeInstance={activeInstance}
                    activeInstanceId={activeInstanceId}
                    previewUrl={previewUrl}
                    previewError={previewError}
                    loading={loadingPreview}
                    frame={frame}
                    windowCenter={windowCenter}
                    windowWidth={windowWidth}
                    onSeriesChange={setActiveSeriesId}
                    onInstanceChange={setActiveInstanceId}
                    onFrameChange={setFrame}
                    onWindowCenterChange={setWindowCenter}
                    onWindowWidthChange={setWindowWidth}
                    onRefresh={() => void handlePreviewRefresh()}
                  />
                  <RiskReviewCard
                    risks={study?.study_id === activeStudyId ? risks : []}
                    onReview={handleReview}
                  />
                </div>
              </TabsContent>

              <TabsContent value="metadata" className="min-h-0 flex-1">
                <MetadataCard
                  study={study?.study_id === activeStudyId ? study : null}
                  entries={study?.study_id === activeStudyId ? metadata : []}
                />
              </TabsContent>

              <TabsContent value="workflow" className="min-h-0 flex-1">
                <div className="grid gap-3 xl:grid-cols-[minmax(24rem,0.8fr)_minmax(32rem,1.2fr)]">
                  <ImportCard
                    files={files}
                    profile={profile}
                    supportedProfiles={supportedProfiles}
                    busy={action === 'ingest'}
                    fileInputRef={fileInputRef}
                    folderInputRef={folderInputRef}
                    onFiles={handleFiles}
                    onProfile={setProfile}
                    onIngest={() => void handleIngest()}
                    onClear={() => setFiles([])}
                  />
                  <ProcessingCard
                    study={study}
                    profile={profile}
                    selectedCount={selectedCount}
                    preflight={currentPreflight}
                    job={currentJob}
                    report={currentReport}
                    action={action}
                    onPreflight={() => void handlePreflight()}
                    onBatchPreflight={() => void handleBatchPreflight()}
                    onAnonymize={() => void handleAnonymize()}
                    onBatchAnonymize={() => void handleBatchAnonymize()}
                    onExport={() => void handleExport()}
                    batchExportReady={
                      latestBatchJobs.length > 0 &&
                      latestBatchJobs.every((job) => job.status === 'completed')
                    }
                    batchAnonymizeReady={
                      selectedCount > 0 &&
                      [...selectedStudyIds].every(
                        (studyId) =>
                          (preflights[studyId] ?? restorePreflight(studyId))?.export_allowed ===
                          true,
                      )
                    }
                    onBatchExport={() => void handleBatchExport()}
                  />
                </div>
              </TabsContent>
            </Tabs>
          </main>
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  destructive = false,
}: {
  icon: typeof Images;
  label: string;
  value: number;
  destructive?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 p-4 pb-2">
        <CardDescription>{label}</CardDescription>
        <Icon className="size-4 text-muted-foreground" />
      </CardHeader>
      <CardContent className="p-4 pt-0">
        <p className={cn('text-2xl font-semibold tabular-nums', destructive && 'text-destructive')}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

function StudyQueueCard({
  studies,
  activeStudyId,
  selectedStudyIds,
  onActivate,
  onToggle,
}: {
  studies: DicomStudy[];
  activeStudyId: string | null;
  selectedStudyIds: Set<string>;
  onActivate: (studyId: string) => void;
  onToggle: (studyId: string, checked: boolean) => void;
}) {
  const t = useT();
  return (
    <Card className="flex min-h-0 flex-col">
      <CardHeader className="p-4">
        <CardTitle>{t('dicom.queue.title')}</CardTitle>
        <CardDescription>{t('dicom.queue.description')}</CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 p-2 pt-0">
        {studies.length === 0 ? (
          <Empty className="h-full border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Images />
              </EmptyMedia>
              <EmptyTitle>{t('dicom.empty.title')}</EmptyTitle>
              <EmptyDescription>{t('dicom.empty.description')}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ScrollArea className="h-full min-h-[460px]">
            <div className="flex flex-col gap-1 pr-3">
              {studies.map((item) => {
                const highRisk = item.risk_summary.blocking;
                return (
                  <div
                    key={item.study_id}
                    className={cn(
                      'grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2 rounded-xl border border-transparent p-2',
                      activeStudyId === item.study_id && 'border-border bg-accent',
                    )}
                  >
                    <Checkbox
                      checked={selectedStudyIds.has(item.study_id)}
                      onCheckedChange={(checked) => onToggle(item.study_id, checked === true)}
                      aria-label={t('dicom.queue.select')}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-auto min-w-0 justify-start p-0 text-left hover:bg-transparent"
                      onClick={() => onActivate(item.study_id)}
                    >
                      <span className="flex min-w-0 flex-col gap-1">
                        <span className="truncate text-sm font-medium">
                          {item.description || item.patient_pseudonym || item.study_id}
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          {item.modalities.join(' / ') || 'DICOM'} · {item.series_count} Series ·{' '}
                          {item.instance_count} Instances
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          {item.study_date || t('dicom.value.unknownDate')}
                        </span>
                      </span>
                    </Button>
                    <div className="flex flex-col items-end gap-1">
                      <Badge variant={highRisk > 0 ? 'destructive' : 'secondary'}>{highRisk}</Badge>
                      <ChevronRight className="size-4 text-muted-foreground" />
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}

function ViewerCard({
  study,
  series,
  activeSeries,
  activeSeriesId,
  activeInstance,
  activeInstanceId,
  previewUrl,
  previewError,
  loading,
  frame,
  windowCenter,
  windowWidth,
  onSeriesChange,
  onInstanceChange,
  onFrameChange,
  onWindowCenterChange,
  onWindowWidthChange,
  onRefresh,
}: {
  study: DicomStudy | null;
  series: DicomSeries[];
  activeSeries: DicomSeries | null;
  activeSeriesId: string | null;
  activeInstance: DicomInstance | null;
  activeInstanceId: string | null;
  previewUrl: string | null;
  previewError: string | null;
  loading: boolean;
  frame: number;
  windowCenter: string;
  windowWidth: string;
  onSeriesChange: (id: string) => void;
  onInstanceChange: (id: string) => void;
  onFrameChange: (frame: number) => void;
  onWindowCenterChange: (value: string) => void;
  onWindowWidthChange: (value: string) => void;
  onRefresh: () => void;
}) {
  const t = useT();
  return (
    <Card className="flex min-h-0 flex-col">
      <CardHeader className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <CardTitle>{study?.description || t('dicom.viewer.title')}</CardTitle>
            <CardDescription>
              {study
                ? `${study.patient_pseudonym || t('dicom.value.pseudonymPending')} · ${study.modalities.join(' / ') || 'DICOM'}`
                : t('dicom.viewer.description')}
            </CardDescription>
          </div>
          {study ? <Badge variant="outline">{study.status}</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 p-4 pt-0">
        {study ? (
          <>
            <FieldGroup className="grid gap-2 lg:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="dicom-series">{t('dicom.viewer.series')}</FieldLabel>
                <Select value={activeSeriesId ?? ''} onValueChange={onSeriesChange}>
                  <SelectTrigger id="dicom-series">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {series.map((item) => (
                        <SelectItem key={item.series_id} value={item.series_id}>
                          {`${item.series_number ?? '-'} · ${item.description || item.modality || 'Series'} (${item.instance_count})`}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="dicom-instance">{t('dicom.viewer.instance')}</FieldLabel>
                <Select value={activeInstanceId ?? ''} onValueChange={onInstanceChange}>
                  <SelectTrigger id="dicom-instance">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      {(activeSeries?.instances ?? []).map((item) => (
                        <SelectItem key={item.instance_id} value={item.instance_id}>
                          {`${t('dicom.viewer.instance')} ${item.instance_number ?? '-'} · ${item.frame_count ?? 1} frame`}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>
            </FieldGroup>

            <div className="relative flex min-h-[360px] flex-1 items-center justify-center overflow-hidden rounded-xl border bg-foreground">
              {loading ? (
                <LoaderCircle className="size-8 animate-spin text-background" />
              ) : previewUrl ? (
                <img
                  src={previewUrl}
                  alt={t('dicom.viewer.previewAlt')}
                  className="max-h-full max-w-full object-contain"
                />
              ) : (
                <Empty className="text-background">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ScanLine />
                    </EmptyMedia>
                    <EmptyTitle>{t('dicom.viewer.noPreview')}</EmptyTitle>
                    <EmptyDescription className="text-background/70">
                      {previewError || t('dicom.viewer.noPreviewDesc')}
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              )}
            </div>

            {previewError ? (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertDescription>{previewError}</AlertDescription>
              </Alert>
            ) : null}

            <FieldGroup className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
              <Field>
                <FieldLabel htmlFor="dicom-frame">{t('dicom.viewer.frame')}</FieldLabel>
                <Input
                  id="dicom-frame"
                  type="number"
                  min={0}
                  max={Math.max(0, (activeInstance?.frame_count ?? 1) - 1)}
                  value={frame}
                  onChange={(event) => onFrameChange(Number(event.target.value) || 0)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="dicom-window-center">
                  {t('dicom.viewer.windowCenter')}
                </FieldLabel>
                <Input
                  id="dicom-window-center"
                  inputMode="decimal"
                  value={windowCenter}
                  onChange={(event) => onWindowCenterChange(event.target.value)}
                  placeholder="Auto"
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="dicom-window-width">
                  {t('dicom.viewer.windowWidth')}
                </FieldLabel>
                <Input
                  id="dicom-window-width"
                  inputMode="decimal"
                  value={windowWidth}
                  onChange={(event) => onWindowWidthChange(event.target.value)}
                  placeholder="Auto"
                />
              </Field>
              <Field className="justify-end">
                <FieldLabel className="sr-only">{t('dicom.viewer.apply')}</FieldLabel>
                <Button variant="outline" onClick={onRefresh} disabled={!activeInstance || loading}>
                  <RefreshCw data-icon="inline-start" className={cn(loading && 'animate-spin')} />
                  {t('dicom.viewer.apply')}
                </Button>
              </Field>
            </FieldGroup>
          </>
        ) : (
          <Empty className="h-full border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Images />
              </EmptyMedia>
              <EmptyTitle>{t('dicom.viewer.selectStudy')}</EmptyTitle>
              <EmptyDescription>{t('dicom.viewer.selectStudyDesc')}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
      </CardContent>
    </Card>
  );
}

function RiskReviewCard({
  risks,
  onReview,
}: {
  risks: DicomRisk[];
  onReview: (
    risk: DicomRisk,
    resolution: 'resolved' | 'accepted',
    note?: string,
  ) => Promise<boolean>;
}) {
  const t = useT();
  const [acceptanceTarget, setAcceptanceTarget] = useState<DicomRisk | null>(null);
  const [acceptanceNote, setAcceptanceNote] = useState('');
  const [savingAcceptance, setSavingAcceptance] = useState(false);
  const unresolved = risks.filter((risk) => !['resolved', 'false_positive'].includes(risk.status));

  const submitAcceptance = async () => {
    if (!acceptanceTarget || acceptanceNote.trim().length < 10) return;
    setSavingAcceptance(true);
    const saved = await onReview(acceptanceTarget, 'accepted', acceptanceNote.trim());
    setSavingAcceptance(false);
    if (saved) {
      setAcceptanceTarget(null);
      setAcceptanceNote('');
    }
  };

  return (
    <>
      <Card className="flex min-h-0 flex-col">
        <CardHeader className="p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <CardTitle>{t('dicom.risk.title')}</CardTitle>
              <CardDescription>{t('dicom.risk.description')}</CardDescription>
            </div>
            <Badge variant={unresolved.length ? 'destructive' : 'secondary'}>
              {unresolved.length}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="min-h-0 flex-1 p-2 pt-0">
          {risks.length === 0 ? (
            <Empty className="h-full border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ShieldCheck />
                </EmptyMedia>
                <EmptyTitle>{t('dicom.risk.empty')}</EmptyTitle>
                <EmptyDescription>{t('dicom.risk.emptyDesc')}</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <ScrollArea className="h-full min-h-[460px]">
              <div className="flex flex-col gap-2 pr-3">
                {risks.map((risk) => (
                  <Card key={risk.risk_id} className="shadow-none">
                    <CardHeader className="p-3 pb-2">
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="leading-5">{risk.message}</CardTitle>
                        <Badge variant={severityVariant(risk.severity)}>{risk.severity}</Badge>
                      </div>
                      <CardDescription>
                        {[risk.category, risk.tag, risk.keyword, risk.location]
                          .filter(Boolean)
                          .join(' · ')}
                      </CardDescription>
                    </CardHeader>
                    {risk.value_preview ? (
                      <CardContent className="p-3 pt-0">
                        <p className="break-all rounded-lg bg-muted p-2 font-mono text-xs text-muted-foreground">
                          {risk.value_preview}
                        </p>
                      </CardContent>
                    ) : null}
                    <CardFooter className="justify-end gap-2 p-3 pt-0">
                      {['open', 'confirmed'].includes(risk.status) ? (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setAcceptanceTarget(risk);
                              setAcceptanceNote('');
                            }}
                          >
                            {t('dicom.risk.accept')}
                          </Button>
                          <Button size="sm" onClick={() => void onReview(risk, 'resolved')}>
                            <CheckCircle2 data-icon="inline-start" />
                            {t('dicom.risk.resolve')}
                          </Button>
                        </>
                      ) : risk.status === 'accepted' ? (
                        <>
                          <Badge variant="secondary">{risk.status}</Badge>
                          <Button size="sm" onClick={() => void onReview(risk, 'resolved')}>
                            <CheckCircle2 data-icon="inline-start" />
                            {t('dicom.risk.resolve')}
                          </Button>
                        </>
                      ) : (
                        <Badge variant="secondary">{risk.status}</Badge>
                      )}
                    </CardFooter>
                  </Card>
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
      <Dialog
        open={acceptanceTarget !== null}
        onOpenChange={(open) => {
          if (!open && !savingAcceptance) {
            setAcceptanceTarget(null);
            setAcceptanceNote('');
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('dicom.risk.acceptTitle')}</DialogTitle>
            <DialogDescription>{t('dicom.risk.acceptDescription')}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="dicom-risk-acceptance-note">
              {t('dicom.risk.acceptNote')}
            </FieldLabel>
            <Textarea
              id="dicom-risk-acceptance-note"
              value={acceptanceNote}
              onChange={(event) => setAcceptanceNote(event.target.value)}
              placeholder={t('dicom.risk.acceptNotePlaceholder')}
              maxLength={2000}
              rows={5}
            />
            <FieldDescription>{t('dicom.risk.acceptNoteHint')}</FieldDescription>
          </Field>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={savingAcceptance}
              onClick={() => setAcceptanceTarget(null)}
            >
              {t('common.cancel')}
            </Button>
            <Button
              variant="destructive"
              disabled={savingAcceptance || acceptanceNote.trim().length < 10}
              onClick={() => void submitAcceptance()}
            >
              {savingAcceptance ? <LoaderCircle className="animate-spin" /> : null}
              {t('dicom.risk.acceptConfirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function MetadataCard({
  study,
  entries,
}: {
  study: DicomStudy | null;
  entries: DicomMetadataEntry[];
}) {
  const t = useT();
  return (
    <Card className="min-h-[600px]">
      <CardHeader>
        <CardTitle>{t('dicom.metadata.title')}</CardTitle>
        <CardDescription>{study?.description || t('dicom.metadata.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <Empty className="min-h-[420px] border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Tags />
              </EmptyMedia>
              <EmptyTitle>{t('dicom.metadata.empty')}</EmptyTitle>
              <EmptyDescription>{t('dicom.metadata.emptyDesc')}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="rounded-xl border">
            <Table className="min-w-[900px]">
              <TableHeader className="bg-muted">
                <TableRow>
                  <TableHead>{t('dicom.metadata.tag')}</TableHead>
                  <TableHead>{t('dicom.metadata.keyword')}</TableHead>
                  <TableHead>VR</TableHead>
                  <TableHead>{t('dicom.metadata.original')}</TableHead>
                  <TableHead>{t('dicom.metadata.output')}</TableHead>
                  <TableHead>{t('dicom.metadata.action')}</TableHead>
                  <TableHead>{t('dicom.metadata.source')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry, index) => (
                  <TableRow key={`${entry.tag}-${entry.source}-${index}`}>
                    <TableCell className="whitespace-nowrap font-mono text-xs">
                      {entry.tag}
                    </TableCell>
                    <TableCell>{entry.keyword || '-'}</TableCell>
                    <TableCell className="font-mono text-xs">{entry.vr || '-'}</TableCell>
                    <TableCell className="max-w-[16rem] break-all text-muted-foreground">
                      {entry.original_value || '-'}
                    </TableCell>
                    <TableCell className="max-w-[16rem] break-all">
                      {entry.output_value || '-'}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{entry.action}</Badge>
                    </TableCell>
                    <TableCell>{entry.source || 'dataset'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ImportCard({
  files,
  profile,
  supportedProfiles,
  busy,
  fileInputRef,
  folderInputRef,
  onFiles,
  onProfile,
  onIngest,
  onClear,
}: {
  files: File[];
  profile: DicomProfile;
  supportedProfiles: DicomProfile[];
  busy: boolean;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  folderInputRef: React.RefObject<HTMLInputElement | null>;
  onFiles: (files: File[]) => void;
  onProfile: (profile: DicomProfile) => void;
  onIngest: () => void;
  onClear: () => void;
}) {
  const t = useT();
  const directoryProps = {
    webkitdirectory: '',
    directory: '',
  } as React.InputHTMLAttributes<HTMLInputElement>;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('dicom.import.title')}</CardTitle>
        <CardDescription>{t('dicom.import.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <FieldSet>
          <FieldLegend variant="label">{t('dicom.import.profile')}</FieldLegend>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="dicom-profile">{t('dicom.import.profileLabel')}</FieldLabel>
              <Select value={profile} onValueChange={(value) => onProfile(value as DicomProfile)}>
                <SelectTrigger id="dicom-profile">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {PROFILE_OPTIONS.filter((option) =>
                      supportedProfiles.includes(option.value),
                    ).map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {t(option.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              <FieldDescription>
                {t(
                  PROFILE_OPTIONS.find((option) => option.value === profile)?.descriptionKey ?? '',
                )}
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="dicom-files">{t('dicom.import.files')}</FieldLabel>
              <Input
                ref={fileInputRef}
                id="dicom-files"
                type="file"
                multiple
                accept=".dcm,.dicom,.zip,DICOMDIR,application/dicom,application/zip"
                onChange={(event) => onFiles(Array.from(event.target.files ?? []))}
              />
              <FieldDescription>{t('dicom.import.filesDesc')}</FieldDescription>
            </Field>

            <Input
              {...directoryProps}
              ref={folderInputRef}
              type="file"
              multiple
              className="sr-only"
              aria-label={t('dicom.import.folder')}
              onChange={(event) => onFiles(Array.from(event.target.files ?? []))}
            />

            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => fileInputRef.current?.click()}>
                <Archive data-icon="inline-start" />
                {t('dicom.import.chooseFiles')}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => folderInputRef.current?.click()}
              >
                <FolderOpen data-icon="inline-start" />
                {t('dicom.import.folder')}
              </Button>
            </div>
          </FieldGroup>
        </FieldSet>

        <Separator className="my-4" />

        {files.length === 0 ? (
          <Empty className="min-h-44 border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Upload />
              </EmptyMedia>
              <EmptyTitle>{t('dicom.import.noFiles')}</EmptyTitle>
              <EmptyDescription>{t('dicom.import.noFilesDesc')}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ScrollArea className="h-44 rounded-xl border p-2">
            <div className="flex flex-col gap-1 pr-3">
              {files.slice(0, 200).map((file) => (
                <div
                  key={`${file.name}-${file.size}-${file.lastModified}`}
                  className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm"
                >
                  <span className="truncate">{file.webkitRelativePath || file.name}</span>
                  <Badge variant="outline">{formatBytes(file.size)}</Badge>
                </div>
              ))}
              {files.length > 200 ? (
                <p className="px-2 text-xs text-muted-foreground">+{files.length - 200}</p>
              ) : null}
            </div>
          </ScrollArea>
        )}
      </CardContent>
      <CardFooter className="justify-between gap-2">
        <Button variant="ghost" onClick={onClear} disabled={files.length === 0 || busy}>
          {t('common.clear')}
        </Button>
        <Button onClick={onIngest} disabled={files.length === 0 || busy}>
          {busy ? (
            <LoaderCircle data-icon="inline-start" className="animate-spin" />
          ) : (
            <Upload data-icon="inline-start" />
          )}
          {busy ? t('dicom.import.ingesting') : t('dicom.import.ingest')}
        </Button>
      </CardFooter>
    </Card>
  );
}

function ProcessingCard({
  study,
  profile,
  selectedCount,
  preflight,
  job,
  report,
  action,
  onPreflight,
  onBatchPreflight,
  onAnonymize,
  onBatchAnonymize,
  onExport,
  batchExportReady,
  batchAnonymizeReady,
  onBatchExport,
}: {
  study: DicomStudy | null;
  profile: DicomProfile;
  selectedCount: number;
  preflight?: DicomPreflightResponse;
  job?: DicomJob;
  report?: DicomReport;
  action: AsyncAction;
  onPreflight: () => void;
  onBatchPreflight: () => void;
  onAnonymize: () => void;
  onBatchAnonymize: () => void;
  onExport: () => void;
  batchExportReady: boolean;
  batchAnonymizeReady: boolean;
  onBatchExport: () => void;
}) {
  const t = useT();
  const profileLabel = t(
    PROFILE_OPTIONS.find((option) => option.value === profile)?.labelKey ?? '',
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('dicom.processing.title')}</CardTitle>
        <CardDescription>{t('dicom.processing.description')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <WorkflowStep
            number="1"
            title={t('dicom.processing.preflight')}
            description={
              preflight
                ? t('dicom.processing.preflightDone')
                : t('dicom.processing.preflightPending')
            }
            complete={Boolean(preflight)}
          />
          <WorkflowStep
            number="2"
            title={t('dicom.processing.deidentify')}
            description={job?.status || t('dicom.processing.deidentifyPending')}
            complete={job?.status === 'completed'}
          />
          <WorkflowStep
            number="3"
            title={t('dicom.processing.validate')}
            description={report?.validation_status || t('dicom.processing.validatePending')}
            complete={report?.validation_status === 'passed'}
          />
        </div>

        <Alert>
          <ShieldCheck />
          <AlertTitle>{profileLabel}</AlertTitle>
          <AlertDescription>
            {t('dicom.processing.sourceGuard')} ·{' '}
            {t('dicom.processing.selected').replace('{count}', String(selectedCount))}
          </AlertDescription>
        </Alert>

        {preflight ? (
          <div className="grid gap-3 sm:grid-cols-4">
            <RiskCount
              label="Critical"
              value={preflight.risk_summary.critical}
              severity="critical"
            />
            <RiskCount label="High" value={preflight.risk_summary.high} severity="high" />
            <RiskCount label="Medium" value={preflight.risk_summary.medium} severity="medium" />
            <RiskCount
              label={t('dicom.processing.unresolved')}
              value={preflight.risk_summary.unresolved}
              severity="low"
            />
          </div>
        ) : null}

        {job ? (
          <div className="flex flex-col gap-2 rounded-xl border p-3">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">{job.message || job.status}</span>
              <Badge variant={job.status === 'failed' ? 'destructive' : 'secondary'}>
                {job.status}
              </Badge>
            </div>
            <Progress value={job.progress ?? (job.status === 'completed' ? 100 : 0)} />
            {job.error ? <p className="text-sm text-destructive">{job.error}</p> : null}
          </div>
        ) : null}

        {report ? (
          <Alert>
            <CheckCircle2 />
            <AlertTitle>{t('dicom.processing.reportReady')}</AlertTitle>
            <AlertDescription>
              {t('dicom.processing.reportSummary')
                .replace('{source}', String(report.source_instance_count))
                .replace('{output}', String(report.output_instance_count))}
            </AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
      <CardFooter className="flex-wrap justify-end gap-2">
        <Button variant="outline" disabled={!study || action != null} onClick={onPreflight}>
          <ScanLine data-icon="inline-start" />
          {action === 'preflight' ? t('dicom.processing.running') : t('dicom.processing.preflight')}
        </Button>
        <Button
          variant="outline"
          disabled={selectedCount === 0 || action != null}
          onClick={onBatchPreflight}
        >
          <Images data-icon="inline-start" />
          {action === 'batch-preflight'
            ? t('dicom.processing.running')
            : t('dicom.processing.batchPreflight')}
        </Button>
        <Button
          disabled={!study || !preflight?.export_allowed || action != null}
          onClick={onAnonymize}
        >
          <Play data-icon="inline-start" />
          {action === 'anonymize'
            ? t('dicom.processing.running')
            : t('dicom.processing.deidentify')}
        </Button>
        <Button disabled={!batchAnonymizeReady || action != null} onClick={onBatchAnonymize}>
          <ShieldCheck data-icon="inline-start" />
          {action === 'batch-anonymize'
            ? t('dicom.processing.running')
            : t('dicom.processing.batchDeidentify')}
        </Button>
        <Button
          variant="outline"
          disabled={job?.status !== 'completed' || !report}
          onClick={onExport}
        >
          <Download data-icon="inline-start" />
          {t('dicom.processing.export')}
        </Button>
        <Button variant="outline" disabled={!batchExportReady} onClick={onBatchExport}>
          <Archive data-icon="inline-start" />
          {t('dicom.processing.batchExport')}
        </Button>
      </CardFooter>
    </Card>
  );
}

function WorkflowStep({
  number,
  title,
  description,
  complete,
}: {
  number: string;
  title: string;
  description: string;
  complete: boolean;
}) {
  return (
    <Card className="shadow-none">
      <CardHeader className="p-3">
        <div className="flex items-center gap-2">
          <Badge variant={complete ? 'default' : 'outline'}>{complete ? '✓' : number}</Badge>
          <CardTitle>{title}</CardTitle>
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
    </Card>
  );
}

function RiskCount({
  label,
  value,
  severity,
}: {
  label: string;
  value: number;
  severity: DicomRiskSeverity;
}) {
  return (
    <Card className="shadow-none">
      <CardHeader className="flex-row items-center justify-between gap-2 p-3">
        <CardDescription>{label}</CardDescription>
        <Badge variant={severityVariant(severity)}>{value}</Badge>
      </CardHeader>
    </Card>
  );
}

function severityVariant(
  severity: DicomRiskSeverity,
): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (severity === 'critical' || severity === 'high') return 'destructive';
  if (severity === 'medium') return 'default';
  if (severity === 'low') return 'secondary';
  return 'outline';
}

function isDicomCandidate(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    name === 'dicomdir' ||
    name.endsWith('.dcm') ||
    name.endsWith('.dicom') ||
    name.endsWith('.zip') ||
    file.type === 'application/dicom' ||
    file.type === 'application/zip' ||
    file.type === ''
  );
}

function mergeStudies(current: DicomStudy[], incoming: DicomStudy[]): DicomStudy[] {
  const merged = new Map(current.map((study) => [study.study_id, study]));
  incoming.forEach((study) => merged.set(study.study_id, study));
  return [...merged.values()];
}

function parseOptionalNumber(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function refreshStudyRisks(
  studyId: string,
  setter: React.Dispatch<React.SetStateAction<DicomRisk[]>>,
): Promise<void> {
  const response = await getDicomRisks(studyId);
  setter(response.risks);
}
