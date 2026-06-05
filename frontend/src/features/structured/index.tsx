// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Database,
  Download,
  Eye,
  FileSpreadsheet,
  Layers,
  PackageCheck,
  Play,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  TableProperties,
  Trash2,
  Upload,
} from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { getJob } from '@/services/jobsApi';
import {
  createStructuredConnection,
  deleteStructuredConnection,
  createStructuredJob,
  discoverStructuredConnectionDatasets,
  downloadStructuredJob,
  getStructuredPolicy,
  getStructuredProfile,
  listStructuredConnections,
  listStructuredDatasets,
  previewStructuredDataset,
  profileStructuredDataset,
  registerStructuredConnectionDatasets,
  saveStructuredPolicy,
  testStructuredConnection,
  uploadStructuredFile,
  type StructuredColumnPolicy,
  type StructuredColumnProfile,
  type StructuredConnection,
  type StructuredConnectionPayload,
  type StructuredDataset,
  type StructuredExportFormat,
  type StructuredPolicyAction,
  type StructuredPreview,
  type StructuredProfile,
} from '@/services/structuredApi';

const actionOptions: Array<{ value: StructuredPolicyAction; label: string }> = [
  { value: 'keep', label: '保留' },
  { value: 'mask', label: '掩码' },
  { value: 'hash', label: '哈希' },
  { value: 'tokenize', label: '令牌化' },
  { value: 'generalize', label: '泛化' },
  { value: 'bucket', label: '分桶' },
  { value: 'suppress', label: '置空' },
  { value: 'custom', label: '自定义' },
];

const exportOptions: Array<{ value: StructuredExportFormat; label: string }> = [
  { value: 'csv', label: 'CSV' },
  { value: 'xlsx', label: 'XLSX' },
  { value: 'sqlite', label: 'SQLite' },
  { value: 'sql', label: 'SQL' },
];

const FIELD_POLICY_PAGE_SIZE = 5;
const DATABASE_DISCOVERY_PAGE_SIZE = 5;
const EMPTY_STRUCTURED_COLUMNS: StructuredColumnProfile[] = [];

interface FieldReviewProgress {
  reviewedPages: number;
  totalPages: number;
  currentPage: number;
  currentPageReviewed: boolean;
  allReviewed: boolean;
}

const emptyConnection: StructuredConnectionPayload = {
  engine: 'sqlite',
  display_name: '',
  host: '127.0.0.1',
  port: 3306,
  database: '',
  username: '',
  password: '',
  sqlite_path: '',
};

export function Structured() {
  return <StructuredOverview />;
}

export function StructuredOverview() {
  const datasetsState = useDatasets();
  const connectionsState = useConnections();
  const fileCount = datasetsState.datasets.filter(isFileDataset).length;
  const dbCount = datasetsState.datasets.filter((dataset) => Boolean(dataset.connection_id)).length;
  const latestDataset = datasetsState.datasets[0] ?? null;
  const pendingReviewDatasets = [...datasetsState.datasets]
    .filter((dataset) => !isDatasetDeliveryReady(dataset))
    .sort(compareStructuredDatasetsForReview);
  const deliverableDatasets = [...datasetsState.datasets]
    .filter(isDatasetDeliveryReady)
    .sort(compareStructuredDatasetsForReview);
  const nextActionDataset = pendingReviewDatasets[0] ?? latestDataset;
  const nextDeliveryDataset = deliverableDatasets[0] ?? nextActionDataset;
  const pendingReviewCount = pendingReviewDatasets.length;

  return (
    <StructuredFrame
      eyebrow="库表处理"
      title="库表处理体系"
      description="结构化数据不走 OCR/VisualFeature 主链路，而是按数据源、数据集、字段策略和交付任务拆开处理。"
    >
      <div className="grid gap-3 lg:grid-cols-4">
        <MetricCard icon={Layers} label="已登记数据集" value={String(datasetsState.datasets.length)} helper="统一进入字段策略治理" />
        <MetricCard icon={FileSpreadsheet} label="文件表数据集" value={String(fileCount)} helper="CSV / Excel / JSONL / SQLite" />
        <MetricCard icon={Database} label="数据库数据集" value={String(dbCount)} helper="MySQL / PostgreSQL / SQLite" />
        <MetricCard icon={Server} label="数据库连接" value={String(connectionsState.connections.length)} helper="只读连接与发现" />
      </div>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.75fr)_minmax(18rem,0.75fr)]">
        <StructuredPathCard
          datasetCount={datasetsState.datasets.length}
          connectionCount={connectionsState.connections.length}
          deliverableCount={deliverableDatasets.length}
          pendingReviewCount={pendingReviewCount}
        />
        <StructuredNextActionCard
          dataset={nextActionDataset}
          deliveryDataset={nextDeliveryDataset}
          datasetCount={datasetsState.datasets.length}
          deliverableCount={deliverableDatasets.length}
          pendingReviewCount={pendingReviewCount}
        />
        <StructuredSourceMixCard fileCount={fileCount} dbCount={dbCount} connectionCount={connectionsState.connections.length} />
      </section>
    </StructuredFrame>
  );
}

export function StructuredFiles() {
  const navigate = useNavigate();
  const datasetsState = useDatasets();
  const notice = useNotice();
  const fileDatasets = datasetsState.datasets.filter(isFileDataset);
  const latestFileDataset = fileDatasets[0] ?? null;
  const deliverableFileCount = fileDatasets.filter(isDatasetDeliveryReady).length;

  async function handleUpload(files: FileList | null) {
    const fileList = Array.from(files ?? []);
    if (!fileList.length) return;
    await notice.run('upload', async () => {
      const uploaded: StructuredDataset[] = [];
      for (const file of fileList) {
        const response = await uploadStructuredFile(file);
        uploaded.push(...response.datasets);
      }
      await datasetsState.refresh();
      notice.setMessage(`已导入 ${uploaded.length} 个数据集`);
      if (uploaded[0]) {
        navigate(
          `/structured/datasets?datasetId=${encodeURIComponent(uploaded[0].id)}&source=file&registered=${uploaded.length}`,
        );
      }
    });
  }

  return (
    <StructuredFrame
      eyebrow="文件表"
      title="文件表导入"
      description="把离线表格、结构化日志和 SQLite 文件登记成数据集，再进入策略页做字段级去标识化。"
      notices={notice}
      actions={
        <Button variant="outline" size="sm" onClick={() => void datasetsState.refresh()}>
          <RefreshCw className="size-4" />
          刷新
        </Button>
      }
    >
      <section className="grid gap-3 xl:grid-cols-[minmax(20rem,0.75fr)_minmax(0,1fr)_minmax(18rem,0.7fr)]">
        <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm">导入文件</CardTitle>
            <CardDescription>上传后自动登记数据集，并进入字段策略。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 px-4 pb-4 pt-0">
            <Label
              htmlFor="structured-upload"
              className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-border bg-muted/30 px-4 py-5 text-center transition hover:bg-muted/50"
            >
              <Upload className="size-7 text-muted-foreground" />
              <span className="mt-3 text-sm font-medium">选择结构化文件</span>
              <span className="mt-1 text-xs text-muted-foreground">CSV / Excel / JSONL / SQLite</span>
            </Label>
            <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
              {['CSV', 'XLSX', 'JSONL', 'SQLite'].map((kind) => (
                <span key={kind} className="rounded-lg border border-border bg-muted/20 px-2 py-1.5 text-center">
                  {kind}
                </span>
              ))}
            </div>
            <Input
              id="structured-upload"
              className="hidden"
              type="file"
              multiple
              accept=".csv,.xlsx,.jsonl,.db,.sqlite"
              onChange={(event) => {
                void handleUpload(event.currentTarget.files);
                event.currentTarget.value = '';
              }}
            />
          </CardContent>
        </Card>

        <DatasetRegistryCard
          title="文件数据集"
          description="文件导入后会出现在这里；进入策略页后可复核、预览和保存策略。"
          datasets={fileDatasets}
          emptyText="暂无文件表数据集"
          busy={notice.busy}
          primaryAction={(dataset) => {
            const reviewed = isDatasetDeliveryReady(dataset);
            return (
              <>
                <Badge
                  variant="outline"
                  className={cn(
                    'shrink-0 text-[10px]',
                    reviewed
                      ? 'border-[var(--success-border)] text-[var(--success-foreground)]'
                      : 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                  )}
                >
                  {reviewed ? '已复核' : '待复核'}
                </Badge>
                <Button asChild size="sm" variant="outline">
                  <Link to={`/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}`}>
                    {reviewed ? '查看策略' : '去策略'}
                  </Link>
                </Button>
              </>
            );
          }}
        />
        <FileTableNextStepCard
          dataset={latestFileDataset}
          count={fileDatasets.length}
          deliverableCount={deliverableFileCount}
        />
      </section>
    </StructuredFrame>
  );
}

export function StructuredDatabase() {
  const navigate = useNavigate();
  const connectionsState = useConnections();
  const datasetsState = useDatasets();
  const notice = useNotice();
  const [payload, setPayload] = React.useState<StructuredConnectionPayload>(emptyConnection);
  const [activeConnectionId, setActiveConnectionId] = React.useState('');
  const [liveDiscovered, setLiveDiscovered] = React.useState<StructuredDataset[]>([]);
  const [discoveryMode, setDiscoveryMode] = React.useState<'registered' | 'live'>('registered');
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const activeConnection =
    connectionsState.connections.find((connection) => connection.id === activeConnectionId) ?? null;
  const registeredConnectionDatasets = React.useMemo(
    () =>
      datasetsState.datasets
        .filter((dataset) => dataset.connection_id === activeConnectionId)
        .sort(compareStructuredDatasetsForReview),
    [activeConnectionId, datasetsState.datasets],
  );
  const discoveryDatasets = discoveryMode === 'live' ? liveDiscovered : registeredConnectionDatasets;

  React.useEffect(() => {
    setActiveConnectionId((current) => current || connectionsState.connections[0]?.id || '');
  }, [connectionsState.connections]);

  function resetDiscovery(message?: string) {
    setLiveDiscovered([]);
    setDiscoveryMode('registered');
    setSelected(new Set());
    if (message) notice.setMessage(message);
  }

  function selectConnection(connectionId: string) {
    if (connectionId === activeConnectionId) return;
    setActiveConnectionId(connectionId);
    resetDiscovery('已切换连接，右侧显示已登记对象；需要刷新结构时点击发现表/视图。');
  }

  async function handleTestConnection() {
    await notice.run('testConnection', async () => {
      const result = await testStructuredConnection(payload);
      if (!result.ok) throw new Error(result.message);
      notice.setMessage(`连接成功，发现 ${result.dataset_count} 个表/视图`);
    });
  }

  async function handleSaveConnection() {
    await notice.run('saveConnection', async () => {
      const connection = await createStructuredConnection(payload);
      await connectionsState.refresh();
      setActiveConnectionId(connection.id);
      resetDiscovery();
      notice.setMessage('数据库连接已保存');
    });
  }

  async function handleDeleteConnection(connectionId: string) {
    if (!connectionId) return;
    const confirmed = window.confirm(
      '移除这条数据库连接？相关登记表、字段策略和预览会从库表处理中移除；已生成的交付包不受影响。',
    );
    if (!confirmed) return;
    await notice.run('deleteConnection', async () => {
      await deleteStructuredConnection(connectionId);
      const nextConnections = await connectionsState.refresh();
      await datasetsState.refresh();
      setLiveDiscovered([]);
      setDiscoveryMode('registered');
      setSelected(new Set());
      setActiveConnectionId(nextConnections[0]?.id ?? '');
      notice.setMessage('数据库连接已移除，相关登记表和策略已清理。');
    });
  }

  async function handleDiscover() {
    if (!activeConnectionId) return;
    await notice.run('discover', async () => {
      const response = await discoverStructuredConnectionDatasets(activeConnectionId);
      setLiveDiscovered(response.datasets);
      setDiscoveryMode('live');
      setSelected(new Set());
      notice.setMessage(`发现 ${response.datasets.length} 个表/视图`);
    });
  }

  async function handleRegister() {
    if (!activeConnectionId || selected.size === 0) return;
    await notice.run('register', async () => {
      const selections = liveDiscovered
        .filter((dataset) => selected.has(datasetKey(dataset)))
        .map((dataset) => ({
          schema_name: dataset.schema_name,
          table_name: dataset.table_name,
          name: dataset.name,
        }));
      const response = await registerStructuredConnectionDatasets(activeConnectionId, selections);
      notice.setMessage(`已登记 ${response.datasets.length} 个数据集`);
      if (response.datasets[0]) {
        navigate(
          `/structured/datasets?datasetId=${encodeURIComponent(response.datasets[0].id)}&source=database&registered=${response.datasets.length}`,
        );
      }
    });
  }

  return (
    <StructuredFrame
      eyebrow="数据库"
      title="数据库连接与发现"
      description="数据库路径独立处理：先保存只读连接，再发现表/视图，最后登记成可治理数据集。"
      notices={notice}
      actions={
        <Button variant="outline" size="sm" onClick={() => void connectionsState.refresh()}>
          <RefreshCw className="size-4" />
          刷新连接
        </Button>
      }
    >
      <section className="grid gap-2 xl:grid-cols-[minmax(23rem,0.78fr)_minmax(0,1.22fr)]">
        <DatabaseConnectionCard
          payload={payload}
          connections={connectionsState.connections}
          activeConnection={activeConnection}
          activeConnectionId={activeConnectionId}
          busy={notice.busy}
          onPayloadChange={setPayload}
          onSelectConnection={selectConnection}
          onTest={() => void handleTestConnection()}
          onSave={() => void handleSaveConnection()}
          onDeleteConnection={(connectionId) => void handleDeleteConnection(connectionId)}
          onDiscover={() => void handleDiscover()}
        />
        <DiscoveredTablesCard
          datasets={discoveryDatasets}
          selected={selected}
          mode={discoveryMode}
          activeConnectionId={activeConnectionId}
          hasActiveConnection={Boolean(activeConnectionId)}
          busy={notice.busy}
          onToggle={(key) => setSelected(toggleSet(selected, key))}
          onSelectAll={() => setSelected(new Set(discoveryDatasets.map(datasetKey)))}
          onSelectKeys={(keys) => setSelected(new Set([...selected, ...keys]))}
          onClear={() => setSelected(new Set())}
          onRegister={() => void handleRegister()}
        />
      </section>
    </StructuredFrame>
  );
}

export function StructuredDatasets() {
  const [searchParams, setSearchParams] = useSearchParams();
  const datasetsState = useDatasets();
  const connectionsState = useConnections();
  const notice = useNotice();
  const [selectedDatasetId, setSelectedDatasetId] = React.useState('');
  const [profile, setProfile] = React.useState<StructuredProfile | null>(null);
  const [policy, setPolicy] = React.useState<StructuredColumnPolicy[]>([]);
  const [preview, setPreview] = React.useState<StructuredPreview | null>(null);
  const [policyConfirmed, setPolicyConfirmed] = React.useState(false);
  const [policySaved, setPolicySaved] = React.useState(false);
  const [policyDirty, setPolicyDirty] = React.useState(false);
  const [fieldPage, setFieldPage] = React.useState(0);
  const [reviewedFieldPages, setReviewedFieldPages] = React.useState<Set<number>>(new Set());
  const [completedDatasetIds, setCompletedDatasetIds] = React.useState<Set<string>>(new Set());
  const handoffNoticeRef = React.useRef('');
  const restoredDatasetIdRef = React.useRef('');
  const autoPreviewKeyRef = React.useRef('');
  const runNotice = notice.run;
  const selectedDataset =
    datasetsState.datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null;
  const returnToDelivery = searchParams.get('returnTo') === 'delivery';
  const returnDeliveryUrl = returnToDelivery && selectedDataset ? deliveryUrlForDataset(selectedDataset) : '';
  const reviewedDatasetIds = React.useMemo(() => {
    const ids = new Set(completedDatasetIds);
    datasetsState.datasets.forEach((dataset) => {
      if (dataset.policy_reviewed_at) ids.add(dataset.id);
    });
    if (policyDirty && selectedDatasetId) ids.delete(selectedDatasetId);
    return ids;
  }, [completedDatasetIds, datasetsState.datasets, policyDirty, selectedDatasetId]);
  const reviewScopeDatasets = React.useMemo(
    () =>
      selectedDataset
        ? datasetsState.datasets.filter((dataset) => isSameDatasetReviewScope(dataset, selectedDataset))
        : datasetsState.datasets,
    [datasetsState.datasets, selectedDataset],
  );
  const remainingDatasetReviewCount = reviewScopeDatasets.filter(
    (dataset) => !reviewedDatasetIds.has(dataset.id),
  ).length;
  const nextDatasetToReview =
    reviewScopeDatasets
      .filter((dataset) => dataset.id !== selectedDatasetId && !reviewedDatasetIds.has(dataset.id))
      .sort(compareStructuredDatasetsForReview)[0] ?? null;
  const fieldCount = profile?.columns.length ?? 0;
  const fieldPageCount = Math.max(1, Math.ceil(fieldCount / FIELD_POLICY_PAGE_SIZE));
  const safeFieldPage = Math.min(fieldPage, fieldPageCount - 1);
  const fieldReviewTotalPages = profile && fieldCount > 0 ? fieldPageCount : 0;
  const fieldReviewReviewedPages = profile
    ? Math.min(
        [...reviewedFieldPages].filter((pageIndex) => pageIndex >= 0 && pageIndex < fieldPageCount).length,
        fieldPageCount,
      )
    : 0;
  const fieldReviewComplete = Boolean(profile) && (fieldReviewTotalPages === 0 || fieldReviewReviewedPages >= fieldReviewTotalPages);
  const currentFieldPageReviewed = Boolean(profile && reviewedFieldPages.has(safeFieldPage));
  const fieldReviewProgress: FieldReviewProgress = {
    reviewedPages: fieldReviewReviewedPages,
    totalPages: fieldReviewTotalPages,
    currentPage: profile ? safeFieldPage + 1 : 0,
    currentPageReviewed: currentFieldPageReviewed,
    allReviewed: fieldReviewComplete,
  };

  React.useEffect(() => {
    const requested = searchParams.get('datasetId');
    if (requested && datasetsState.datasets.some((dataset) => dataset.id === requested)) {
      setSelectedDatasetId(requested);
      return;
    }
    setSelectedDatasetId((current) => current || datasetsState.datasets[0]?.id || '');
  }, [datasetsState.datasets, searchParams]);

  React.useEffect(() => {
    const registered = Number(searchParams.get('registered') ?? 0);
    const source = searchParams.get('source');
    const datasetId = searchParams.get('datasetId') ?? '';
    const key = `${source}:${registered}:${datasetId}`;
    if (!['database', 'file'].includes(source ?? '') || registered <= 0 || handoffNoticeRef.current === key) return;
    handoffNoticeRef.current = key;
    const sourceLabel = source === 'database' ? '数据库登记' : '文件导入';
    notice.setMessage(
      registered === 1
        ? `已从${sourceLabel} 1 个数据集，请复核字段策略。`
        : `已从${sourceLabel} ${registered} 个数据集，当前先复核第 1 个；其余数据集可在左侧列表继续处理。`,
    );
  }, [notice, searchParams]);

  function resetDatasetReviewState() {
    setProfile(null);
    setPolicy([]);
    setPreview(null);
    setPolicyConfirmed(false);
    setPolicySaved(false);
    setPolicyDirty(false);
    setFieldPage(0);
    setReviewedFieldPages(new Set());
  }

  React.useEffect(() => {
    if (!selectedDataset) return;
    const restoreKey = [
      selectedDataset.id,
      selectedDataset.profile_updated_at ?? '',
      selectedDataset.policy_updated_at ?? '',
      selectedDataset.policy_reviewed_at ?? '',
    ].join(':');
    if (restoredDatasetIdRef.current === restoreKey && profile?.dataset_id === selectedDataset.id) return;

    const hasLocalReviewState =
      profile?.dataset_id === selectedDataset.id ||
      preview?.dataset_id === selectedDataset.id;
    if (!hasLocalReviewState) {
      resetDatasetReviewState();
    }

    const hasStoredReviewState = Boolean(
      selectedDataset.profile_updated_at || selectedDataset.policy_updated_at || selectedDataset.policy_reviewed_at,
    );
    if (!hasStoredReviewState) {
      restoredDatasetIdRef.current = restoreKey;
      return;
    }

    let cancelled = false;
    void runNotice('restorePolicy', async () => {
      const [storedProfile, storedPolicy] = await Promise.all([
        getStructuredProfile(selectedDataset.id),
        getStructuredPolicy(selectedDataset.id),
      ]);
      if (cancelled) return;
      const restoredPolicy = storedPolicy.columns.length
        ? storedPolicy.columns
        : storedProfile.columns.map(profileToPolicy);
      const restoredPageCount = Math.max(1, Math.ceil(storedProfile.columns.length / FIELD_POLICY_PAGE_SIZE));
      const wasReviewed = Boolean(selectedDataset.policy_reviewed_at);
      const restoredPreview = wasReviewed ? await previewStructuredDataset(selectedDataset.id) : null;
      if (cancelled) return;
      setProfile(storedProfile);
      setPolicy(restoredPreview?.policy ?? restoredPolicy);
      setPreview(restoredPreview);
      setPolicyConfirmed(wasReviewed);
      setPolicySaved(wasReviewed);
      setPolicyDirty(false);
      setFieldPage(0);
      setReviewedFieldPages(
        wasReviewed
          ? new Set(Array.from({ length: restoredPageCount }, (_, index) => index))
          : new Set(),
      );
      restoredDatasetIdRef.current = restoreKey;
    });
    return () => {
      cancelled = true;
    };
  }, [preview?.dataset_id, profile?.dataset_id, runNotice, selectedDataset]);

  React.useEffect(() => {
    if (!selectedDataset || !selectedDatasetId || !policySaved || preview || notice.busy) return;
    const previewKey = `${selectedDataset.id}:${selectedDataset.policy_updated_at ?? selectedDataset.policy_reviewed_at ?? 'saved'}`;
    if (autoPreviewKeyRef.current === previewKey) return;

    let cancelled = false;
    autoPreviewKeyRef.current = previewKey;
    void runNotice('autoPreview', async () => {
      const response = await previewStructuredDataset(selectedDatasetId);
      if (cancelled) return;
      setPreview(response);
      setPolicy(response.policy);
    });
    return () => {
      cancelled = true;
    };
  }, [notice.busy, policySaved, preview, runNotice, selectedDataset, selectedDatasetId]);

  function selectDataset(datasetId: string) {
    if (datasetId === selectedDatasetId) {
      setSearchParams(datasetId ? preservePolicyReturnParams(searchParams, datasetId) : {});
      return;
    }
    if (
      policyDirty &&
      !window.confirm('当前字段策略有未保存改动，切换数据集会放弃这些改动。确定继续？')
    ) {
      return;
    }
    setSelectedDatasetId(datasetId);
    setSearchParams(datasetId ? preservePolicyReturnParams(searchParams, datasetId) : {});
    resetDatasetReviewState();
  }

  async function handleProfile(datasetId = selectedDatasetId) {
    if (!datasetId) return;
    await notice.run('profile', async () => {
      const nextProfile = await profileStructuredDataset(datasetId);
      setProfile(nextProfile);
      setPolicy(nextProfile.columns.map(profileToPolicy));
      setPolicyConfirmed(false);
      setPolicySaved(false);
      setPolicyDirty(false);
      setPreview(null);
      setFieldPage(0);
      setReviewedFieldPages(new Set());
    });
  }

  async function handleSaveAndPreview() {
    if (!selectedDatasetId) return;
    if (!policyConfirmed) {
      notice.setError('请先确认字段策略，再生成预览。');
      return;
    }
    await notice.run('policyPreview', async () => {
      const saved = await saveStructuredPolicy(selectedDatasetId, policy);
      setPolicy(saved.columns);
      setPolicySaved(true);
      setPolicyDirty(false);
      const response = await previewStructuredDataset(selectedDatasetId);
      setPreview(response);
      setPolicy(response.policy);
      setCompletedDatasetIds((current) => new Set([...current, selectedDatasetId]));
      await datasetsState.refresh();
    });
  }

  async function handlePreview() {
    if (!selectedDatasetId) return;
    if (!policySaved) {
      notice.setError('请先保存字段策略，再生成脱敏预览。');
      return;
    }
    await notice.run('preview', async () => {
      const response = await previewStructuredDataset(selectedDatasetId);
      setPreview(response);
      setPolicy(response.policy);
    });
  }

  function handlePolicyChange(nextPolicy: StructuredColumnPolicy[]) {
    setPolicy(nextPolicy);
    setPolicyConfirmed(false);
    setPolicySaved(false);
    setPolicyDirty(true);
    setPreview(null);
    setReviewedFieldPages((current) => {
      if (!current.has(safeFieldPage)) return current;
      const next = new Set(current);
      next.delete(safeFieldPage);
      return next;
    });
  }

  function handleConfirmChange(checked: boolean) {
    if (checked && !fieldReviewComplete) {
      notice.setError(`请先确认所有字段页：已确认 ${fieldReviewReviewedPages}/${fieldReviewTotalPages} 页。`);
      return;
    }
    setPolicyConfirmed(checked);
  }

  function advanceFieldReview() {
    if (!profile) return;
    const nextReviewedPages = new Set(reviewedFieldPages);
    nextReviewedPages.add(safeFieldPage);
    setReviewedFieldPages(nextReviewedPages);
    const nextUnreviewed = Array.from({ length: fieldPageCount }, (_, index) => index).find(
      (pageIndex) => !nextReviewedPages.has(pageIndex),
    );
    if (nextUnreviewed == null) {
      setPolicyConfirmed(true);
    }
    setFieldPage(nextUnreviewed ?? safeFieldPage);
  }

  return (
    <StructuredFrame
      eyebrow="数据集策略"
      title="数据集策略与字段复核"
      description="这里不做导入和连接，只处理已登记数据集的字段识别、策略复核和脱敏预览。"
      notices={notice}
      fit
      actions={
        <Button variant="outline" size="sm" onClick={() => void datasetsState.refresh()}>
          <RefreshCw className="size-4" />
          刷新数据集
        </Button>
      }
    >
      <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2">
        <PolicyCanvas
          dataset={selectedDataset}
          profile={profile}
          fieldReview={fieldReviewProgress}
          policyConfirmed={policyConfirmed}
          policySaved={policySaved}
          preview={preview}
          nextDatasetToReview={nextDatasetToReview}
          remainingDatasetReviewCount={remainingDatasetReviewCount}
          busy={notice.busy}
          onConfirmChange={handleConfirmChange}
          onAdvanceFieldReview={advanceFieldReview}
          onProfile={() => void handleProfile()}
          onSave={() => void handleSaveAndPreview()}
          onPreview={() => void handlePreview()}
          onNextDataset={() => {
            if (nextDatasetToReview) selectDataset(nextDatasetToReview.id);
          }}
          returnDeliveryUrl={returnDeliveryUrl}
        />
        <div className="grid min-h-0 gap-2 xl:grid-cols-[17rem_minmax(0,1fr)_22rem]">
          <DatasetPickerCard
            datasets={datasetsState.datasets}
            connections={connectionsState.connections}
            selectedDatasetId={selectedDatasetId}
            reviewedDatasetIds={reviewedDatasetIds}
            dirtyDatasetId={policyDirty ? selectedDatasetId : ''}
            onSelect={selectDataset}
            compact
          />
          <ProfilePolicyCard
            dataset={selectedDataset}
            profile={profile}
            policy={policy}
            fieldPage={safeFieldPage}
            currentPageReviewed={fieldReviewProgress.currentPageReviewed}
            reviewedPageCount={fieldReviewReviewedPages}
            pageCount={fieldReviewTotalPages || 1}
            onFieldPageChange={setFieldPage}
            onPolicyChange={handlePolicyChange}
          />
          <PreviewCard
            preview={preview}
            profile={profile}
            loading={notice.busy === 'autoPreview' || notice.busy === 'preview' || notice.busy === 'policyPreview'}
          />
        </div>
      </section>
    </StructuredFrame>
  );
}

export function StructuredDelivery() {
  const [searchParams, setSearchParams] = useSearchParams();
  const datasetsState = useDatasets();
  const connectionsState = useConnections();
  const notice = useNotice();
  const requestedDatasetId = searchParams.get('datasetId') ?? '';
  const requestedScope = searchParams.get('scope') ?? '';
  const requestedConnectionId = searchParams.get('connectionId') ?? '';
  const requestedSourceId = searchParams.get('sourceId') ?? '';
  const requestedJobId = searchParams.get('jobId') ?? '';
  const requestedSelectionSignature = searchParams.get('selected') ?? '';
  const requestedSelectionIds = React.useMemo(
    () => Array.from(new Set(requestedSelectionSignature.split(',').map((item) => item.trim()).filter(Boolean))),
    [requestedSelectionSignature],
  );
  const appliedDatasetParamRef = React.useRef('');
  const appliedDefaultSelectionRef = React.useRef('');
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [exportFormat, setExportFormat] = React.useState<StructuredExportFormat>('csv');
  const [latestJobId, setLatestJobId] = React.useState(requestedJobId);
  const [latestJobStatus, setLatestJobStatus] = React.useState('');
  const handoffDataset = datasetsState.datasets.find((dataset) => dataset.id === requestedDatasetId) ?? null;
  const handoffScopeDatasets = React.useMemo(() => {
    if (requestedScope === 'file') {
      return datasetsState.datasets.filter(isFileDataset).sort(compareStructuredDatasetsForReview);
    }
    if (requestedScope === 'connection' && requestedConnectionId) {
      return datasetsState.datasets
        .filter((dataset) => dataset.connection_id === requestedConnectionId)
        .sort(compareStructuredDatasetsForReview);
    }
    if (requestedScope === 'source' && requestedSourceId) {
      return datasetsState.datasets
        .filter((dataset) => dataset.source_id === requestedSourceId)
        .sort(compareStructuredDatasetsForReview);
    }
    return handoffDataset ? [handoffDataset] : [];
  }, [datasetsState.datasets, handoffDataset, requestedConnectionId, requestedScope, requestedSourceId]);
  const handoffSelectionIds = handoffScopeDatasets.map((dataset) => dataset.id);
  const handoffSelectionSignature = handoffSelectionIds.join('|');
  const hasExplicitHandoffScope =
    handoffScopeDatasets.length > 0 &&
    (requestedScope === 'file' ||
      (requestedScope === 'connection' && Boolean(requestedConnectionId)) ||
      (requestedScope === 'source' && Boolean(requestedSourceId)));
  const deliveryDatasetOptions = React.useMemo(
    () => (hasExplicitHandoffScope ? handoffScopeDatasets : datasetsState.datasets),
    [datasetsState.datasets, handoffScopeDatasets, hasExplicitHandoffScope],
  );
  const deliverableDatasetOptions = React.useMemo(
    () => deliveryDatasetOptions.filter(isDatasetDeliveryReady),
    [deliveryDatasetOptions],
  );
  const deliverableDatasetIds = React.useMemo(
    () => deliverableDatasetOptions.map((dataset) => dataset.id),
    [deliverableDatasetOptions],
  );
  const deliverableDatasetIdSet = React.useMemo(() => new Set(deliverableDatasetIds), [deliverableDatasetIds]);
  const defaultSelectionSignature = deliverableDatasetIds.join('|');
  const unreviewedDeliveryDatasets = deliveryDatasetOptions.filter((dataset) => !isDatasetDeliveryReady(dataset));
  const selectedDatasets = React.useMemo(
    () => deliverableDatasetOptions.filter((dataset) => selectedIds.has(dataset.id)),
    [deliverableDatasetOptions, selectedIds],
  );
  const firstUnreviewedDataset = unreviewedDeliveryDatasets[0] ?? null;
  const firstUnreviewedLabel = firstUnreviewedDataset
    ? firstUnreviewedDataset.table_name || firstUnreviewedDataset.name
    : '';
  const handoffConnection =
    requestedScope === 'connection'
      ? connectionsState.connections.find((connection) => connection.id === requestedConnectionId) ?? null
      : null;
  const handoffLabel =
    requestedScope === 'file' && handoffScopeDatasets.length > 1
      ? `文件表 · ${handoffScopeDatasets.length} 个数据集`
    : requestedScope === 'connection' && handoffScopeDatasets.length > 1
      ? `${handoffConnection?.display_name || '当前数据库连接'} · ${handoffScopeDatasets.length} 个数据集`
      : requestedScope === 'source' && handoffScopeDatasets.length > 1
        ? `当前文件来源 · ${handoffScopeDatasets.length} 个数据集`
        : handoffDataset?.name;
  const handoffVisible = handoffSelectionIds.some((datasetId) => selectedIds.has(datasetId));
  const jobCompleted = latestJobStatus === 'completed';
  const deliveryMode = selectedDatasets.length === 0 ? 'none' : selectedDatasets.length > 1 ? 'batch' : 'single';
  const deliveryModeLabel =
    selectedDatasets.length === 0
      ? '待选择'
      : selectedDatasets.length > 1
        ? `批量交付（${selectedDatasets.length}）`
        : '单次交付';
  const canCreateJob = selectedDatasets.length > 0 && !notice.busy;
  const createButtonLabel = jobCompleted
    ? '重新执行交付'
    : selectedDatasets.length === 0
      ? '选择数据集后交付'
      : selectedDatasets.length > 1
        ? `执行批量交付（${selectedDatasets.length}）`
        : '执行单次交付';
  const downloadButtonLabel = jobCompleted ? '下载 ZIP 包' : '下载结果';

  React.useEffect(() => {
    if (requestedSelectionIds.length === 0) return;
    const validSelectionIds = requestedSelectionIds.filter((datasetId) => deliverableDatasetIdSet.has(datasetId));
    setSelectedIds((current) => (sameSetValues(current, validSelectionIds) ? current : new Set(validSelectionIds)));
  }, [deliverableDatasetIdSet, requestedSelectionIds]);

  React.useEffect(() => {
    if (requestedSelectionIds.length > 0) return;
    const handoffKey = `${requestedDatasetId}:${requestedScope}:${requestedConnectionId}:${requestedSourceId}:${handoffSelectionSignature}`;
    if ((!requestedDatasetId && !hasExplicitHandoffScope) || appliedDatasetParamRef.current === handoffKey) return;
    if (handoffSelectionIds.length === 0) return;
    const reviewedHandoffIds = handoffScopeDatasets.filter(isDatasetDeliveryReady).map((dataset) => dataset.id);
    setSelectedIds(new Set(reviewedHandoffIds));
    appliedDatasetParamRef.current = handoffKey;
  }, [
    handoffSelectionIds,
    handoffSelectionSignature,
    handoffScopeDatasets,
    requestedSelectionIds.length,
    requestedConnectionId,
    requestedDatasetId,
    requestedScope,
    requestedSourceId,
    hasExplicitHandoffScope,
  ]);

  React.useEffect(() => {
    if (requestedSelectionIds.length > 0) return;
    if (requestedDatasetId || hasExplicitHandoffScope) return;
    if (!defaultSelectionSignature || appliedDefaultSelectionRef.current === defaultSelectionSignature) return;
    if (selectedIds.size > 0) {
      appliedDefaultSelectionRef.current = defaultSelectionSignature;
      return;
    }
    setSelectedIds(new Set(deliverableDatasetIds));
    appliedDefaultSelectionRef.current = defaultSelectionSignature;
  }, [
    defaultSelectionSignature,
    deliverableDatasetIds,
    hasExplicitHandoffScope,
    requestedDatasetId,
    requestedSelectionIds.length,
    selectedIds.size,
  ]);

  React.useEffect(() => {
    setLatestJobId(requestedJobId);
    if (!requestedJobId) {
      setLatestJobStatus('');
      return undefined;
    }
    let cancelled = false;
    void getJob(requestedJobId)
      .then((detail) => {
        if (!cancelled) setLatestJobStatus(detail.status);
      })
      .catch(() => {
        if (!cancelled) setLatestJobStatus('');
      });
    return () => {
      cancelled = true;
    };
  }, [requestedJobId]);

  async function waitForStructuredJob(jobId: string): Promise<string> {
    for (let attempt = 0; attempt < 45; attempt += 1) {
      const detail = await getJob(jobId);
      setLatestJobStatus(detail.status);
      if (['completed', 'failed', 'cancelled'].includes(detail.status)) return detail.status;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    return 'processing';
  }

  async function handleCreateJob() {
    const ids = selectedDatasets.map((dataset) => dataset.id);
    if (!ids.length) {
      notice.setError('请至少选择一个数据集');
      return;
    }
    await notice.run('job', async () => {
      const response = await createStructuredJob({
        title: ids.length === 1 ? '库表单次去标识化' : `库表批量去标识化（${ids.length}）`,
        dataset_ids: ids,
        export_format: exportFormat,
        skip_review: true,
        auto_submit: true,
      });
      setLatestJobId(response.job.id);
      setLatestJobStatus(response.job.status || 'queued');
      setSearchParams({ ...handoffSearchParams(new Set(ids)), jobId: response.job.id });
      const finalStatus = await waitForStructuredJob(response.job.id);
      if (finalStatus === 'completed') {
        notice.setMessage(`交付包已生成，包含脱敏数据和 quality-report.json：${response.job.id}`);
      } else if (finalStatus === 'failed' || finalStatus === 'cancelled') {
        throw new Error(`任务未完成：${finalStatus}`);
      } else {
        notice.setMessage(`任务仍在处理，可稍后刷新或到任务中心查看：${response.job.id}`);
      }
    });
  }

  function clearStaleJob(nextSelectedIds = selectedIds, reason = '当前选择已变化，请重新执行交付。') {
    const hadJob = Boolean(latestJobId || latestJobStatus);
    setLatestJobId('');
    setLatestJobStatus('');
    notice.setMessage(hadJob ? reason : '');
    setSearchParams(handoffSearchParams(nextSelectedIds));
  }

  function handoffSearchParams(nextSelectedIds: Set<string>): Record<string, string> {
    const params: Record<string, string> = {};
    if (requestedDatasetId && nextSelectedIds.has(requestedDatasetId)) params.datasetId = requestedDatasetId;
    if (requestedScope === 'file') {
      params.scope = 'file';
    }
    if (requestedScope === 'connection' && requestedConnectionId) {
      params.scope = 'connection';
      params.connectionId = requestedConnectionId;
    }
    if (requestedScope === 'source' && requestedSourceId) {
      params.scope = 'source';
      params.sourceId = requestedSourceId;
    }
    const selectedInScope = Array.from(nextSelectedIds).filter((datasetId) => deliverableDatasetIds.includes(datasetId));
    const defaultIdSet = new Set(deliverableDatasetIds);
    const differsFromDefault =
      selectedInScope.length > 0 &&
      (selectedInScope.length !== defaultIdSet.size || selectedInScope.some((datasetId) => !defaultIdSet.has(datasetId)));
    if (differsFromDefault) params.selected = selectedInScope.join(',');
    return params;
  }

  function handleToggleDataset(datasetId: string) {
    const dataset = deliveryDatasetOptions.find((item) => item.id === datasetId);
    if (dataset && !isDatasetDeliveryReady(dataset)) {
      notice.setError('这个数据集还没有保存字段策略，先进入数据集策略页复核。');
      return;
    }
    const next = toggleSet(selectedIds, datasetId);
    setSelectedIds(next);
    clearStaleJob(next);
  }

  function handleSelectAll(datasetIds?: string[]) {
    const next = new Set(datasetIds ?? deliverableDatasetOptions.map((dataset) => dataset.id));
    if (next.size === 0 && deliveryDatasetOptions.length > 0) {
      notice.setError('当前没有已复核的数据集，先去数据集策略页保存字段策略。');
      return;
    }
    setSelectedIds(next);
    clearStaleJob(next);
  }

  function handleClearSelection() {
    const next = new Set<string>();
    setSelectedIds(next);
    clearStaleJob(next);
  }

  function handleExportFormatChange(value: StructuredExportFormat) {
    setExportFormat(value);
    clearStaleJob(selectedIds, '导出格式已变化，请重新执行交付。');
  }

  async function handleDownload() {
    if (!latestJobId) return;
    if (latestJobStatus !== 'completed') {
      notice.setError('任务完成后才能下载结果');
      return;
    }
    await notice.run('download', async () => {
      await downloadStructuredJob(latestJobId);
      notice.setMessage(`交付包已开始下载：${latestJobId}`);
    });
  }

  return (
    <StructuredFrame
      eyebrow="交付导出"
      title="库表交付"
      description="单个数据集走单次交付，多个数据集走批量交付；选择变化后需要重新执行任务。"
      notices={notice}
      actions={
        <Button variant="outline" size="sm" asChild>
          <Link to="/jobs">任务中心</Link>
        </Button>
      }
    >
      <section className="grid items-start gap-2 xl:grid-cols-[minmax(0,1.2fr)_minmax(22rem,0.8fr)]">
        <DeliveryDatasetCard
          datasets={deliveryDatasetOptions}
          connections={connectionsState.connections}
          selectedIds={selectedIds}
          onToggle={handleToggleDataset}
          onSelectAll={handleSelectAll}
          onClear={handleClearSelection}
        />
        <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
          <CardHeader className="px-3 py-2">
            <CardTitle className="text-sm">交付设置</CardTitle>
            <CardDescription>结构化任务会直接生成脱敏导出，不调用 OCR/VisualFeature。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 px-3 pb-3 pt-0">
            <Field label="包内文件格式">
              <Select
                value={exportFormat}
                onValueChange={(value) => handleExportFormatChange(value as StructuredExportFormat)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {exportOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs leading-4 text-muted-foreground">
                下载始终是 ZIP 交付包，包内包含所选格式文件和 quality-report.json。
              </p>
            </Field>
            <div className="rounded-xl border border-border bg-muted/30 p-2.5 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">已选择</span>
                <span className="font-semibold">{selectedDatasets.length} 个数据集</span>
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span className="text-muted-foreground">交付模式</span>
                <Badge variant={deliveryMode === 'single' ? 'secondary' : 'outline'}>{deliveryModeLabel}</Badge>
              </div>
              {handoffVisible && handoffLabel ? (
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">承接自策略</span>
                  <span className="truncate font-medium" title={handoffLabel}>
                    {handoffLabel}
                  </span>
                </div>
              ) : null}
              <div className="mt-1.5 flex items-center justify-between gap-3">
                <span className="text-muted-foreground">下载形式</span>
                <span className="font-medium">ZIP 交付包</span>
              </div>
              {latestJobId ? (
                <div className="mt-1.5 flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">最近任务</span>
                  <Badge variant={jobCompleted ? 'default' : 'outline'}>
                    {structuredJobStatusLabel(latestJobStatus || 'queued')}
                  </Badge>
                </div>
              ) : null}
              {jobCompleted ? (
                <div className="mt-1.5 rounded-lg border border-[var(--success-border)] bg-[var(--success-surface)] px-2.5 py-1.5 text-xs text-[var(--success-foreground)]">
                  ZIP 包已就绪，包含脱敏数据和 quality-report.json。
                </div>
              ) : null}
            </div>
            {unreviewedDeliveryDatasets.length > 0 ? (
              <div className="grid gap-2 rounded-xl border border-[var(--warning-border)] bg-[var(--warning-surface)] px-3 py-2 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    <span className="block font-semibold text-[var(--warning-foreground)]">待复核数据集不会纳入交付</span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {firstUnreviewedLabel ? `下一项：${firstUnreviewedLabel} · ` : ''}
                      {unreviewedDeliveryDatasets.length} 个数据集还没有保存字段策略；复核后会自动变成可交付。
                    </span>
                  </span>
                  {firstUnreviewedDataset ? (
                    <Button asChild variant="outline" size="sm" className="h-8 shrink-0 bg-background">
                      <Link to={policyReviewUrlForDataset(firstUnreviewedDataset, { returnToDelivery: true })}>
                        去复核
                        <ArrowRight className="size-4" />
                      </Link>
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : null}
            <DeliveryChecklist
              selectedCount={selectedDatasets.length}
              unreviewedCount={unreviewedDeliveryDatasets.length}
              exportFormat={exportFormat}
              deliveryModeLabel={selectedDatasets.length ? deliveryModeLabel : '待选择'}
              latestJobStatus={latestJobStatus}
            />
            <div className="grid gap-2 sm:grid-cols-2">
              <Button
                variant={jobCompleted ? 'outline' : 'default'}
                onClick={() => void handleCreateJob()}
                disabled={!canCreateJob}
                data-testid="delivery-create-job"
              >
                <Play className="size-4" />
                {createButtonLabel}
              </Button>
              <Button
                variant={jobCompleted ? 'default' : 'outline'}
                onClick={() => void handleDownload()}
                disabled={!latestJobId || !jobCompleted || Boolean(notice.busy)}
                data-testid="delivery-download-job"
              >
                <Download className="size-4" />
                {downloadButtonLabel}
              </Button>
            </div>
          </CardContent>
        </Card>
      </section>
    </StructuredFrame>
  );
}

function StructuredFrame({
  eyebrow,
  title,
  description,
  actions,
  notices,
  fit,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  notices?: NoticeState;
  fit?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="saas-page flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      <div className="page-shell !max-w-[min(100%,2048px)] !px-3 !py-3 sm:!px-4 2xl:!px-5">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden">
          <header className="flex flex-none flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <span className="saas-kicker">{eyebrow}</span>
              <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
              <p className="max-w-4xl text-sm leading-6 text-muted-foreground">{description}</p>
            </div>
            {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
          </header>
          <NoticeStack notices={notices} />
          <main className={cn('min-h-0 flex-1 pr-1', fit ? 'overflow-hidden' : 'overflow-auto')}>
            <div className={cn('grid gap-3', fit ? 'h-full min-h-0' : 'pb-3')}>{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
}

type NoticeState = {
  busy: string;
  message: string;
  error: string;
  setMessage: (message: string) => void;
  setError: (error: string) => void;
  run: (name: string, fn: () => Promise<void>) => Promise<void>;
};

function useNotice(): NoticeState {
  const [busy, setBusy] = React.useState('');
  const [message, setMessage] = React.useState('');
  const [error, setError] = React.useState('');

  const run = React.useCallback(async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setMessage('');
    setError('');
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  }, []);

  return { busy, message, error, setMessage, setError, run };
}

function NoticeStack({ notices }: { notices?: NoticeState }) {
  if (!notices) return null;
  return (
    <>
      {notices.error ? (
        <Alert variant="destructive" className="flex-none">
          <AlertDescription>{notices.error}</AlertDescription>
        </Alert>
      ) : null}
      {notices.message ? (
        <Alert className="flex-none">
          <AlertDescription>{notices.message}</AlertDescription>
        </Alert>
      ) : null}
    </>
  );
}

function useDatasets() {
  const [datasets, setDatasets] = React.useState<StructuredDataset[]>([]);
  const [loading, setLoading] = React.useState(true);
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const response = await listStructuredDatasets();
      setDatasets(response.datasets);
      return response.datasets;
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { datasets, loading, refresh };
}

function useConnections() {
  const [connections, setConnections] = React.useState<StructuredConnection[]>([]);
  const [loading, setLoading] = React.useState(true);
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const nextConnections = await listStructuredConnections();
      setConnections(nextConnections);
      return nextConnections;
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { connections, loading, refresh };
}

function StructuredPathCard({
  datasetCount,
  connectionCount,
  deliverableCount,
  pendingReviewCount,
}: {
  datasetCount: number;
  connectionCount: number;
  deliverableCount: number;
  pendingReviewCount: number;
}) {
  const steps = [
    {
      title: '登记数据源',
      desc: datasetCount > 0 ? '文件表或数据库对象已登记' : '文件表或数据库任选其一',
      Icon: Layers,
      done: datasetCount > 0,
      active: datasetCount === 0,
      status: datasetCount > 0 ? `${datasetCount} 个` : '待登记',
    },
    {
      title: '复核字段策略',
      desc:
        datasetCount === 0
          ? '登记后进入字段策略复核'
          : pendingReviewCount > 0
            ? `${pendingReviewCount} 个数据集待复核`
            : '字段策略已复核',
      Icon: ShieldCheck,
      done: datasetCount > 0 && pendingReviewCount === 0,
      active: datasetCount > 0 && pendingReviewCount > 0,
      status: datasetCount > 0 ? `${deliverableCount}/${datasetCount}` : '待数据',
    },
    {
      title: '交付导出',
      desc: deliverableCount > 0 ? '生成 ZIP 交付包和质量报告' : '保存策略后可交付',
      Icon: PackageCheck,
      done: deliverableCount > 0,
      active: deliverableCount > 0,
      status: deliverableCount > 0 ? '可交付' : '待复核',
    },
  ];
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-2.5">
        <CardTitle className="text-sm">治理路径</CardTitle>
        <CardDescription>数据源入口二选一，后续按字段策略闭环。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        {steps.map(({ title, desc, Icon, done, active, status }) => {
          return (
            <div
              key={title}
              data-testid="structured-path-step"
              data-path-title={title}
              className={cn(
                'grid min-h-11 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-1.5',
                active && 'bg-muted/35',
              )}
            >
              <span
                className={cn(
                  'grid size-8 place-items-center rounded-lg border',
                  done ? 'border-[var(--success-border)] bg-[var(--success-surface)]' : 'border-border bg-muted/25',
                )}
              >
                {done ? <CheckCircle2 className="size-4 text-[var(--success-foreground)]" /> : <Icon className="size-4" />}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">{title}</span>
                <span className="block truncate text-xs text-muted-foreground">{desc}</span>
              </span>
              <Badge variant="outline" className="rounded-full text-[10px]">
                {status}
              </Badge>
            </div>
          );
        })}
        <div className="rounded-xl border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          数据库连接是数据库来源的可选入口；当前已保存 {connectionCount} 条只读连接。
        </div>
      </CardContent>
    </Card>
  );
}

function StructuredNextActionCard({
  dataset,
  deliveryDataset,
  datasetCount,
  deliverableCount,
  pendingReviewCount,
}: {
  dataset: StructuredDataset | null;
  deliveryDataset: StructuredDataset | null;
  datasetCount: number;
  deliverableCount: number;
  pendingReviewCount: number;
}) {
  const hasDataset = Boolean(dataset);
  const hasPendingReview = pendingReviewCount > 0;
  const primaryTarget = dataset
    ? `/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}`
    : '/structured/files';
  const primaryLabel = !hasDataset ? '导入第一个数据集' : hasPendingReview ? '继续复核待处理表' : '查看字段策略';
  const secondaryTarget =
    deliverableCount > 0
      ? '/structured/delivery'
      : deliveryDataset
        ? deliveryUrlForDataset(deliveryDataset)
        : '/structured/database';
  const secondaryLabel =
    deliverableCount > 0 ? '交付已复核数据' : deliveryDataset ? '查看交付准备' : '连接数据库';
  const description =
    datasetCount === 0
      ? '先登记一个文件表或数据库表。'
      : hasPendingReview
        ? `还有 ${pendingReviewCount} 个数据集待复核。`
        : '字段策略已复核，可以进入交付。';

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-2.5">
        <CardTitle className="text-sm">下一步</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 pt-0">
        <div className="grid min-h-20 content-center rounded-xl border border-border bg-muted/25 px-3 py-2">
          <span className="text-xs font-semibold text-muted-foreground">
            {hasPendingReview ? '待复核对象' : '当前对象'}
          </span>
          <span className="mt-1 truncate text-sm font-semibold" title={dataset?.name}>
            {dataset?.name ?? '暂无数据集'}
          </span>
          <span className="mt-1 truncate text-xs text-muted-foreground">
            {dataset
              ? `${dataset.source_kind.toUpperCase()} · ${dataset.column_count} 列 ${dataset.row_count_estimate ?? 0} 行`
              : '导入后会自动进入字段策略'}
          </span>
        </div>
        <Button asChild className="h-9 justify-between rounded-xl" size="sm">
          <Link to={primaryTarget}>
            {primaryLabel}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
        <Button asChild variant="outline" className="h-9 justify-between rounded-xl" size="sm">
          <Link to={secondaryTarget}>
            {secondaryLabel}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function StructuredSourceMixCard({
  fileCount,
  dbCount,
  connectionCount,
}: {
  fileCount: number;
  dbCount: number;
  connectionCount: number;
}) {
  const total = fileCount + dbCount;
  const filePct = total > 0 ? Math.round((fileCount / total) * 100) : 0;
  const dbPct = total > 0 ? 100 - filePct : 0;
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-2.5">
        <CardTitle className="text-sm">数据源分布</CardTitle>
        <CardDescription>区分离线文件表与数据库登记对象。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 pt-0">
        <div className="grid gap-2 rounded-xl border border-border bg-muted/25 p-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">登记对象</span>
            <span className="font-semibold">{total}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="flex h-full">
              <span className="bg-foreground" style={{ width: `${filePct}%` }} />
              <span className="bg-[var(--success-foreground)]" style={{ width: `${dbPct}%` }} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <SourceMixItem label="文件表" value={fileCount} percent={filePct} tone="file" />
            <SourceMixItem label="数据库对象" value={dbCount} percent={dbPct} tone="db" />
          </div>
        </div>
        <div className="grid min-h-11 content-center rounded-xl border border-border px-3 py-1.5 text-sm">
          <span className="text-xs text-muted-foreground">只读连接</span>
          <span className="mt-0.5 font-semibold">{connectionCount} 个连接可发现表/视图</span>
        </div>
      </CardContent>
    </Card>
  );
}

function FileTableNextStepCard({
  dataset,
  count,
  deliverableCount,
}: {
  dataset: StructuredDataset | null;
  count: number;
  deliverableCount: number;
}) {
  const reviewed = Boolean(dataset && isDatasetDeliveryReady(dataset));
  const policyTarget = dataset ? `/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}` : '/structured/files';
  const hasDeliverableFiles = deliverableCount > 0;
  const deliveryTarget = hasDeliverableFiles
    ? '/structured/delivery?scope=file'
    : dataset
      ? policyReviewUrlForDataset(dataset, { returnToDelivery: true })
      : '/structured/delivery';
  const deliveryStatus =
    deliverableCount > 0
      ? deliverableCount === count
        ? '全部可交付'
        : `${deliverableCount}/${count} 可交付`
      : dataset
        ? '待复核'
        : '待数据集';
  const deliveryLabel = deliverableCount > 1 ? '交付全部文件表' : hasDeliverableFiles ? '交付文件表' : '进入交付';
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">文件表状态</CardTitle>
        <CardDescription>导入后先复核字段策略，再批量交付。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 px-4 pb-4 pt-0">
        <div className="grid gap-2 rounded-xl border border-border bg-muted/25 p-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted-foreground">文件表数据集</span>
            <span className="font-semibold">{count}</span>
          </div>
          <div className="grid min-h-14 content-center rounded-lg bg-background px-3 py-2">
            <span className="text-xs text-muted-foreground">最近对象</span>
            <span className="truncate font-semibold" title={dataset?.name}>
              {dataset?.name ?? '暂无文件表'}
            </span>
            {dataset ? (
              <span className="truncate text-xs text-muted-foreground">
                {dataset.source_kind.toUpperCase()} · {dataset.column_count} 列 {dataset.row_count_estimate ?? 0} 行
              </span>
            ) : null}
          </div>
        </div>
        <div className="grid gap-2">
          <FileFlowCheck label="导入文件" status={count > 0 ? '已登记' : '待导入'} done={count > 0} />
          <FileFlowCheck
            label="字段策略"
            status={deliverableCount > 0 ? `${deliverableCount}/${count} 已复核` : dataset ? '待复核' : '待登记'}
            done={deliverableCount > 0}
          />
          <FileFlowCheck label="交付导出" status={deliveryStatus} done={hasDeliverableFiles} />
        </div>
        {dataset ? (
          <Button asChild className="h-9 justify-between rounded-xl" size="sm">
            <Link to={policyTarget}>
              {reviewed ? '查看策略' : '继续策略'}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : (
          <Button className="h-9 justify-between rounded-xl" size="sm" disabled>
            继续策略
            <ArrowRight className="size-4" />
          </Button>
        )}
        {dataset ? (
          <Button asChild variant="outline" className="h-9 justify-between rounded-xl" size="sm">
            <Link to={deliveryTarget}>
              {deliveryLabel}
              <ArrowRight className="size-4" />
            </Link>
          </Button>
        ) : (
          <Button variant="outline" className="h-9 justify-between rounded-xl" size="sm" disabled>
            进入交付
            <ArrowRight className="size-4" />
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function FileFlowCheck({ label, status, done }: { label: string; status: string; done: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border px-3 py-1.5 text-sm">
      <span className="flex items-center gap-2">
        <CheckCircle2
          className={cn('size-4', done ? 'text-[var(--success-foreground)]' : 'text-muted-foreground')}
        />
        {label}
      </span>
      <span className="text-xs text-muted-foreground">{status}</span>
    </div>
  );
}

function SourceMixItem({
  label,
  value,
  percent,
  tone,
}: {
  label: string;
  value: number;
  percent: number;
  tone: 'file' | 'db';
}) {
  return (
    <span className="grid gap-0.5 rounded-lg bg-background px-2 py-1.5">
      <span className="flex items-center gap-1 text-muted-foreground">
        <span
          className={cn(
            'size-2 rounded-full',
            tone === 'file' ? 'bg-foreground' : 'bg-[var(--success-foreground)]',
          )}
        />
        {label}
      </span>
      <span className="font-semibold">
        {value} · {percent}%
      </span>
    </span>
  );
}

function MetricCard({
  label,
  value,
  helper,
  icon: Icon,
}: {
  label: string;
  value: string;
  helper?: string;
  icon?: React.FC<{ className?: string }>;
}) {
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]" data-testid="structured-metric-card">
      <CardContent className="flex min-h-20 items-start justify-between gap-3 px-4 py-2.5">
        <span className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
          {helper ? <p className="mt-1 truncate text-xs text-muted-foreground">{helper}</p> : null}
        </span>
        {Icon ? (
          <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-border bg-muted text-muted-foreground">
            <Icon className="size-4" />
          </span>
        ) : null}
      </CardContent>
    </Card>
  );
}

function DatasetRegistryCard({
  title,
  description,
  datasets,
  emptyText,
  busy,
  primaryAction,
}: {
  title: string;
  description: string;
  datasets: StructuredDataset[];
  emptyText: string;
  busy?: string;
  primaryAction?: (dataset: StructuredDataset) => React.ReactNode;
}) {
  const [page, setPage] = React.useState(0);
  const pageSize = 6;
  const pageCount = Math.max(1, Math.ceil(datasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = datasets.slice(safePage * pageSize, safePage * pageSize + pageSize);

  React.useEffect(() => {
    setPage(0);
  }, [datasets.length]);

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-4 py-3">
        <CardTitle className="text-sm">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        <div className="grid gap-2">
          {datasets.length === 0 ? (
            <EmptyState icon={TableProperties} text={emptyText} />
          ) : (
            visibleDatasets.map((dataset) => (
              <div
                key={dataset.id}
                className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-2"
              >
                <DatasetIdentity dataset={dataset} />
                <div className="flex shrink-0 items-center gap-2">
                  {primaryAction?.(dataset)}
                  {busy ? null : null}
                </div>
              </div>
            ))
          )}
        </div>
        {datasets.length > pageSize ? (
          <ListPager
            label="数据集"
            page={safePage}
            pageCount={pageCount}
            total={datasets.length}
            pageSize={pageSize}
            visibleCount={visibleDatasets.length}
            onPageChange={setPage}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function DatabaseConnectionCard({
  payload,
  connections,
  activeConnection,
  activeConnectionId,
  busy,
  onPayloadChange,
  onSelectConnection,
  onTest,
  onSave,
  onDeleteConnection,
  onDiscover,
}: {
  payload: StructuredConnectionPayload;
  connections: StructuredConnection[];
  activeConnection: StructuredConnection | null;
  activeConnectionId: string;
  busy: string;
  onPayloadChange: (payload: StructuredConnectionPayload) => void;
  onSelectConnection: (id: string) => void;
  onTest: () => void;
  onSave: () => void;
  onDeleteConnection: (id: string) => void;
  onDiscover: () => void;
}) {
  const isSqlite = payload.engine === 'sqlite';
  const activeTarget = activeConnection ? connectionTargetLabel(activeConnection) : '';
  const activeDatasetCount = activeConnection ? Number(activeConnection.metadata?.dataset_count ?? 0) : 0;
  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-3 py-2.5">
        <CardTitle className="text-sm">新建连接</CardTitle>
        <CardDescription className="text-xs leading-5">建议使用只读账号。这里保存为新连接，不覆盖已保存连接。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2.5 px-3 pb-3 pt-0">
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="类型">
            <Select
              value={payload.engine}
              onValueChange={(engine) =>
                onPayloadChange({
                  ...payload,
                  engine: engine as StructuredConnectionPayload['engine'],
                  port: engine === 'postgres' ? 5432 : engine === 'mysql' ? 3306 : payload.port,
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sqlite">SQLite</SelectItem>
                <SelectItem value="mysql">MySQL</SelectItem>
                <SelectItem value="postgres">PostgreSQL</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="名称">
            <Input
              value={payload.display_name ?? ''}
              onChange={(event) => onPayloadChange({ ...payload, display_name: event.target.value })}
              placeholder="客户主数据只读库"
            />
          </Field>
          {isSqlite ? (
            <Field label="SQLite 路径">
              <Input
                value={payload.sqlite_path ?? ''}
                onChange={(event) => onPayloadChange({ ...payload, sqlite_path: event.target.value })}
                placeholder="D:\data\source.sqlite"
              />
            </Field>
          ) : (
            <>
              <Field label="主机">
                <Input
                  value={payload.host ?? ''}
                  onChange={(event) => onPayloadChange({ ...payload, host: event.target.value })}
                />
              </Field>
              <Field label="端口">
                <Input
                  value={payload.port ?? ''}
                  onChange={(event) =>
                    onPayloadChange({ ...payload, port: Number(event.target.value) || undefined })
                  }
                />
              </Field>
              <Field label="库名">
                <Input
                  value={payload.database ?? ''}
                  onChange={(event) => onPayloadChange({ ...payload, database: event.target.value })}
                />
              </Field>
              <Field label="用户名">
                <Input
                  value={payload.username ?? ''}
                  onChange={(event) => onPayloadChange({ ...payload, username: event.target.value })}
                />
              </Field>
              <Field label="密码">
                <Input
                  type="password"
                  value={payload.password ?? ''}
                  onChange={(event) => onPayloadChange({ ...payload, password: event.target.value })}
                />
              </Field>
            </>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onTest} disabled={Boolean(busy)}>
            <Server className="size-4" />
            测试新连接
          </Button>
          <Button size="sm" onClick={onSave} disabled={Boolean(busy)}>
            <Save className="size-4" />
            保存为新连接
          </Button>
        </div>
        <div className="grid gap-1.5">
          <Label>已保存连接</Label>
          <div className="flex flex-wrap gap-2">
            {connections.map((connection) => (
              <Button
                key={connection.id}
                variant={activeConnectionId === connection.id ? 'default' : 'outline'}
                size="sm"
                onClick={() => onSelectConnection(connection.id)}
              >
                {connection.display_name}
              </Button>
            ))}
            {connections.length === 0 ? (
              <span className="text-sm text-muted-foreground">暂无连接</span>
            ) : null}
          </div>
        </div>
        {activeConnection ? (
          <div
            className="grid gap-1.5 rounded-xl border border-[var(--success-border)] bg-[var(--success-surface)] px-3 py-2"
            data-testid="db-active-connection-card"
          >
            <div className="flex items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[var(--success-foreground)]">当前发现目标</span>
                <span className="mt-0.5 block truncate text-sm font-semibold" title={activeConnection.display_name}>
                  {activeConnection.display_name}
                </span>
                <span className="mt-0.5 block truncate text-xs text-muted-foreground" title={activeTarget}>
                  {activeTarget || activeConnection.engine.toUpperCase()}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                <span className="rounded-full bg-background px-2 py-1 text-xs font-semibold">
                  {activeDatasetCount} 个对象
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 rounded-lg text-muted-foreground hover:bg-background hover:text-destructive"
                  title="移除连接"
                  aria-label="移除当前连接"
                  data-testid="db-delete-active-connection"
                  onClick={() => onDeleteConnection(activeConnection.id)}
                  disabled={Boolean(busy)}
                >
                  <Trash2 className="size-4" />
                </Button>
              </span>
            </div>
            <span className="hidden text-xs leading-5 text-muted-foreground 2xl:block">
              发现表/视图会使用这条已保存连接的加密凭据；上方表单只用于新建连接。
            </span>
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border px-3 py-2.5 text-sm text-muted-foreground">
            保存或选择一条连接后，再发现表/视图。
          </div>
        )}
        <Button variant="outline" size="sm" onClick={onDiscover} disabled={!activeConnectionId || Boolean(busy)}>
          <Eye className="size-4" />
          发现表/视图
        </Button>
      </CardContent>
    </Card>
  );
}

function DiscoveredTablesCard({
  datasets,
  selected,
  mode,
  activeConnectionId,
  hasActiveConnection,
  busy,
  onToggle,
  onSelectAll,
  onSelectKeys,
  onClear,
  onRegister,
}: {
  datasets: StructuredDataset[];
  selected: Set<string>;
  mode: 'registered' | 'live';
  activeConnectionId: string;
  hasActiveConnection: boolean;
  busy: string;
  onToggle: (key: string) => void;
  onSelectAll: () => void;
  onSelectKeys: (keys: string[]) => void;
  onClear: () => void;
  onRegister: () => void;
}) {
  const isRegisteredMode = mode === 'registered';
  const hasDatasets = datasets.length > 0;
  const [query, setQuery] = React.useState('');
  const [schemaFilter, setSchemaFilter] = React.useState('__all__');
  const [page, setPage] = React.useState(0);
  const discoverySignature = React.useMemo(() => datasets.map(datasetKey).join('|'), [datasets]);
  const sortedDatasets = React.useMemo(
    () =>
      [...datasets].sort((left, right) => {
        const leftSchema = datasetSchemaLabel(left);
        const rightSchema = datasetSchemaLabel(right);
        if (leftSchema !== rightSchema) return leftSchema.localeCompare(rightSchema);
        return (left.table_name ?? left.name).localeCompare(right.table_name ?? right.name);
      }),
    [datasets],
  );
  const normalizedQuery = query.trim().toLowerCase();
  const schemaSummaries = React.useMemo(() => {
    const groups = new Map<string, { label: string; total: number; selected: number; tables: number; views: number }>();
    sortedDatasets.forEach((dataset) => {
      const label = datasetSchemaLabel(dataset);
      const current = groups.get(label) ?? { label, total: 0, selected: 0, tables: 0, views: 0 };
      current.total += 1;
      if (selected.has(datasetKey(dataset))) current.selected += 1;
      if (dataset.dataset_type === 'db_view') current.views += 1;
      else current.tables += 1;
      groups.set(label, current);
    });
    return Array.from(groups.values());
  }, [selected, sortedDatasets]);
  const tableCount = sortedDatasets.filter((dataset) => dataset.dataset_type !== 'db_view').length;
  const viewCount = sortedDatasets.length - tableCount;
  const schemaFilteredDatasets =
    schemaFilter === '__all__'
      ? sortedDatasets
      : sortedDatasets.filter((dataset) => datasetSchemaLabel(dataset) === schemaFilter);
  const filteredDatasets = normalizedQuery
    ? schemaFilteredDatasets.filter((dataset) =>
        [
          dataset.name,
          dataset.schema_name,
          dataset.table_name,
          dataset.dataset_type,
          dataset.source_kind,
          ...dataset.schema.map((column) => column.name),
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(normalizedQuery)),
      )
    : schemaFilteredDatasets;
  const pageSize = DATABASE_DISCOVERY_PAGE_SIZE;
  const pageCount = Math.max(1, Math.ceil(filteredDatasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = filteredDatasets.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const selectedInFilter = filteredDatasets.filter((dataset) => selected.has(datasetKey(dataset))).length;
  const schemaSummaryMap = React.useMemo(
    () => new Map(schemaSummaries.map((schema) => [schema.label, schema])),
    [schemaSummaries],
  );
  const visibleGroups = React.useMemo(() => {
    const groups = new Map<string, StructuredDataset[]>();
    visibleDatasets.forEach((dataset) => {
      const label = datasetSchemaLabel(dataset);
      groups.set(label, [...(groups.get(label) ?? []), dataset]);
    });
    return Array.from(groups, ([label, items]) => ({
      label,
      items,
      summary: schemaSummaryMap.get(label),
    }));
  }, [schemaSummaryMap, visibleDatasets]);
  const showSchemaGroupHeaders = schemaFilter === '__all__' && schemaSummaries.length > 1;

  React.useEffect(() => {
    setPage(0);
  }, [datasets.length, normalizedQuery, schemaFilter]);

  React.useEffect(() => {
    setQuery('');
    setSchemaFilter('__all__');
    setPage(0);
  }, [discoverySignature, mode]);

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]" data-testid="db-discovery-card">
      <CardHeader className="flex-row items-start justify-between gap-3 px-3 py-2">
        <div className="min-w-0">
          <CardTitle className="text-sm">{isRegisteredMode ? '已登记对象' : '发现结果'}</CardTitle>
          <CardDescription className="text-xs leading-5">
            {isRegisteredMode
              ? '当前连接已登记的数据集，可直接进入策略或交付；需要刷新结构时再发现表/视图。'
              : '一个连接可能包含多个 schema、表和视图，先按 schema 定位，再登记需要治理的数据集。'}
          </CardDescription>
        </div>
        <Badge variant="outline" className="shrink-0 rounded-full text-[10px]">
          {isRegisteredMode ? `已登记 ${datasets.length}` : `${datasets.length} 个对象`}
        </Badge>
      </CardHeader>
      <CardContent className="px-3 pb-3 pt-0">
        <div className="mb-2 grid gap-1.5 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5" data-testid="db-discovery-summary">
          <div className="grid gap-2 sm:grid-cols-4">
            <DiscoveryMetric label="Schema" value={schemaSummaries.length} />
            <DiscoveryMetric label="表" value={tableCount} />
            <DiscoveryMetric label="视图" value={viewCount} />
            <DiscoveryMetric
              label={isRegisteredMode ? '已登记' : '已选'}
              value={isRegisteredMode ? datasets.length : selected.size}
              tone="strong"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索 schema、表名或字段"
              className="h-8 min-w-44 flex-1"
              data-testid="db-discovery-search"
            />
            {isRegisteredMode ? (
              activeConnectionId && hasDatasets ? (
                <Button asChild size="sm" className="h-8 px-2.5 text-xs">
                  <Link to={`/structured/delivery?scope=connection&connectionId=${encodeURIComponent(activeConnectionId)}`}>
                    交付当前连接
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
              ) : null
            ) : (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={() => onSelectKeys(filteredDatasets.map(datasetKey))}
                  disabled={!hasDatasets || filteredDatasets.length === 0 || Boolean(busy)}
                >
                  全选当前筛选 ({filteredDatasets.length})
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={onSelectAll}
                  disabled={!hasDatasets || Boolean(busy)}
                >
                  全选全部
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                  onClick={onClear}
                  disabled={!hasDatasets || selected.size === 0 || Boolean(busy)}
                >
                  清空
                </Button>
                <Button
                  onClick={onRegister}
                  disabled={selected.size === 0 || Boolean(busy)}
                  size="sm"
                  className="h-8 px-2.5 text-xs"
                >
                  登记选中 ({selected.size})
                </Button>
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5" data-testid="db-schema-filter">
            <button
              type="button"
              onClick={() => setSchemaFilter('__all__')}
              aria-pressed={schemaFilter === '__all__'}
              className={cn(
                'rounded-full border px-2.5 py-0.5 text-xs transition hover:bg-background',
                schemaFilter === '__all__' ? 'border-foreground bg-background text-foreground' : 'border-border text-muted-foreground',
              )}
            >
              全部 {datasets.length}
            </button>
            {schemaSummaries.map((schema) => (
              <button
                key={schema.label}
                type="button"
                onClick={() => setSchemaFilter(schema.label)}
                aria-pressed={schemaFilter === schema.label}
                className={cn(
                  'rounded-full border px-2.5 py-0.5 text-xs transition hover:bg-background',
                  schemaFilter === schema.label
                    ? 'border-foreground bg-background text-foreground'
                    : 'border-border text-muted-foreground',
                )}
                title={`${schema.tables} 个表，${schema.views} 个视图`}
              >
                {schema.label} {schema.total}
                {schema.selected ? <span className="ml-1 text-[var(--success-foreground)]">已选 {schema.selected}</span> : null}
              </button>
            ))}
          </div>
          {schemaFilter !== '__all__' || normalizedQuery ? (
            <div className="text-xs text-muted-foreground">
              当前筛选 {filteredDatasets.length} 个对象{isRegisteredMode ? '' : `，已选 ${selectedInFilter} 个`}。
            </div>
          ) : null}
        </div>
        <div className="overflow-hidden rounded-xl border border-border" data-testid="db-discovery-list">
          {datasets.length === 0 ? (
            <EmptyState
              icon={Database}
              text={
                hasActiveConnection
                  ? isRegisteredMode
                    ? '当前连接还没有登记对象；点击“发现表/视图”后选择需要治理的表。'
                    : '先点击“发现表/视图”获取当前连接的对象'
                  : '先保存或选择一个数据库连接'
              }
            />
          ) : filteredDatasets.length === 0 ? (
            <EmptyState icon={Database} text="当前筛选没有匹配的表或视图" />
          ) : (
            <table className="w-full table-fixed text-xs">
              <thead className="bg-muted text-[11px] text-muted-foreground">
                <tr>
                  <th className="w-10 px-2 py-1.5 text-left">{isRegisteredMode ? '状态' : '选择'}</th>
                  <th className="w-[18%] px-2 py-1.5 text-left">Schema</th>
                  <th className="w-[28%] px-2 py-1.5 text-left">表/视图</th>
                  <th className="w-[12%] px-2 py-1.5 text-left">类型</th>
                  <th className="w-[18%] px-2 py-1.5 text-left">规模</th>
                  <th className="w-[14%] px-2 py-1.5 text-left">数据源</th>
                  {isRegisteredMode ? <th className="w-[10%] px-2 py-1.5 text-right">操作</th> : null}
                </tr>
              </thead>
              <tbody>
                {visibleGroups.map((group) => (
                  <React.Fragment key={group.label}>
                    {showSchemaGroupHeaders ? (
                      <tr className="border-t border-border bg-muted/25" data-testid="db-schema-group-header">
                        <td colSpan={isRegisteredMode ? 7 : 6} className="px-2 py-0.5">
                          <span className="flex min-w-0 items-center justify-between gap-3 text-[11px] text-muted-foreground">
                            <span className="flex min-w-0 items-center gap-2 font-medium text-foreground">
                              <Layers className="size-3.5 shrink-0 text-muted-foreground" />
                              <span className="truncate" title={group.label}>
                                {group.label}
                              </span>
                            </span>
                            <span className="shrink-0">
                              {group.summary?.tables ?? 0} 表 · {group.summary?.views ?? 0} 视图
                              {group.summary?.selected ? ` · 已选 ${group.summary.selected}` : ''}
                            </span>
                          </span>
                        </td>
                      </tr>
                    ) : null}
                    {group.items.map((dataset) => {
                      const key = datasetKey(dataset);
                      const rowsText = dataset.row_count_estimate == null ? '行数待采样' : `${dataset.row_count_estimate} 行`;
                      return (
                        <tr key={key} className="border-t border-border" data-testid="db-discovery-row">
                          <td className="px-2 py-1">
                            {isRegisteredMode ? (
                              <CheckCircle2 className="size-4 text-[var(--success-foreground)]" />
                            ) : (
                              <Checkbox checked={selected.has(key)} onCheckedChange={() => onToggle(key)} />
                            )}
                          </td>
                          <td className="px-2 py-1">
                            <span className="block truncate" title={datasetSchemaLabel(dataset)}>
                              {datasetSchemaLabel(dataset)}
                            </span>
                          </td>
                          <td className="px-2 py-1">
                            <span className="block truncate font-medium" title={dataset.name}>
                              {dataset.table_name ?? dataset.name}
                            </span>
                            <span className="block truncate text-[10px] text-muted-foreground" title={shapeKindLabel(dataset.shape_kind)}>
                              {shapeKindLabel(dataset.shape_kind)}
                            </span>
                          </td>
                          <td className="px-2 py-1">
                            <Badge variant="outline" className="text-[10px]">
                              {datasetTypeLabel(dataset)}
                            </Badge>
                          </td>
                          <td className="px-2 py-1 text-muted-foreground">
                            <span className="block truncate">{dataset.column_count} 列</span>
                            <span className="block truncate text-[10px]">{rowsText}</span>
                          </td>
                          <td className="px-2 py-1">
                            <Badge variant="outline" className="text-[10px]">
                              {dataset.source_kind.toUpperCase()}
                            </Badge>
                          </td>
                          {isRegisteredMode ? (
                            <td className="px-2 py-1 text-right">
                              <Button asChild variant="outline" size="sm" className="h-7 px-2">
                                <Link to={`/structured/datasets?datasetId=${encodeURIComponent(dataset.id)}`}>去策略</Link>
                              </Button>
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {filteredDatasets.length > pageSize ? (
          <div className="mt-1.5">
            <ListPager
              label="表/视图"
              page={safePage}
              pageCount={pageCount}
              total={filteredDatasets.length}
              pageSize={pageSize}
              visibleCount={visibleDatasets.length}
              onPageChange={setPage}
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function PolicyCanvas({
  dataset,
  profile,
  fieldReview,
  policyConfirmed,
  policySaved,
  preview,
  nextDatasetToReview,
  remainingDatasetReviewCount,
  busy,
  onConfirmChange,
  onAdvanceFieldReview,
  onProfile,
  onSave,
  onPreview,
  onNextDataset,
  returnDeliveryUrl,
}: {
  dataset: StructuredDataset | null;
  profile: StructuredProfile | null;
  fieldReview: FieldReviewProgress;
  policyConfirmed: boolean;
  policySaved: boolean;
  preview: StructuredPreview | null;
  nextDatasetToReview: StructuredDataset | null;
  remainingDatasetReviewCount: number;
  busy: string;
  onConfirmChange: (checked: boolean) => void;
  onAdvanceFieldReview: () => void;
  onProfile: () => void;
  onSave: () => void;
  onPreview: () => void;
  onNextDataset: () => void;
  returnDeliveryUrl: string;
}) {
  const canConfirmPolicy = Boolean(profile && fieldReview.allReviewed);
  const nextReviewLabel = dataset?.connection_id ? '继续下一张表' : '继续下一个数据集';
  const reviewScopeNoun = dataset?.connection_id ? '同连接' : '同来源';
  const nodes = [
    {
      key: 'dataset',
      title: '选择数据集',
      desc: dataset ? dataset.name : '先选一个治理对象',
      done: Boolean(dataset),
      active: !dataset,
    },
    {
      key: 'profile',
      title: '字段策略',
      desc: profile ? `${profile.columns.length} 个字段策略已生成` : '识别 PII 与技术列并给出默认策略',
      done: Boolean(profile),
      active: Boolean(dataset && !profile),
    },
    {
      key: 'confirm',
      title: '确认策略',
      desc: policyConfirmed
        ? '字段与动作已核对'
        : profile && !fieldReview.allReviewed
          ? `已确认 ${fieldReview.reviewedPages}/${fieldReview.totalPages} 页`
          : '核对字段、样本和动作',
      done: policyConfirmed,
      active: Boolean(profile && !policyConfirmed),
      confirmable: true,
    },
    {
      key: 'save',
      title: '保存策略',
      desc: policySaved ? '策略已固化并可验证' : '保存策略并生成样本',
      done: policySaved,
      active: Boolean(policyConfirmed && !policySaved),
    },
    {
      key: 'preview',
      title: '预览验证',
      desc: preview
        ? '脱敏样本已生成'
        : returnDeliveryUrl && policySaved
          ? '已可返回交付'
          : '验证输出效果',
      done: Boolean(preview || (returnDeliveryUrl && policySaved)),
      active: Boolean(policySaved && !preview && !returnDeliveryUrl),
    },
  ];
  const currentAction = !dataset
    ? {
        label: '先选择数据集',
        detail: '从左侧选择一个已登记数据集。',
        Icon: TableProperties,
        disabled: true,
      }
    : !profile
      ? {
          label: '生成字段策略',
          detail: '按列名和样本生成字段策略。',
          Icon: ShieldCheck,
          onClick: onProfile,
        }
      : !fieldReview.allReviewed
        ? {
            label: fieldReview.currentPageReviewed ? '继续复核未确认页' : `确认第 ${fieldReview.currentPage}/${fieldReview.totalPages} 页`,
            detail: fieldReview.currentPageReviewed
              ? `已确认 ${fieldReview.reviewedPages}/${fieldReview.totalPages} 页，继续下一页。`
              : '核对当前页字段、样本和动作后确认。',
            Icon: fieldReview.currentPageReviewed ? Eye : CheckCircle2,
            onClick: onAdvanceFieldReview,
          }
      : !policyConfirmed
        ? {
            label: '确认字段策略',
            detail: '确认字段、样本和动作无误后继续。',
            Icon: CheckCircle2,
            onClick: () => onConfirmChange(true),
          }
        : !policySaved
          ? {
              label: '保存并生成预览',
              detail: '固化当前策略，并立即用样本验证输出。',
              Icon: Save,
              onClick: onSave,
            }
          : returnDeliveryUrl
            ? {
                label: '返回交付',
                detail: '这个数据集已可交付，回到交付页继续选择。',
                Icon: PackageCheck,
                to: returnDeliveryUrl,
              }
          : !preview
            ? {
                label: '生成脱敏预览',
                detail: '用样本验证输出是否符合预期。',
                Icon: Eye,
                onClick: onPreview,
              }
            : {
                ...(nextDatasetToReview
                  ? {
                      label: nextReviewLabel,
                      detail: `还有 ${remainingDatasetReviewCount} 个${reviewScopeNoun}数据集未确认`,
                      Icon: ArrowRight,
                      onClick: onNextDataset,
                    }
                  : {
                      label: '进入交付',
                      detail: '策略已完成，可执行单次或批量交付。',
                      Icon: PackageCheck,
                      to: deliveryUrlForDataset(dataset),
                    }),
              };
  const CurrentIcon = currentAction.Icon;
  const currentActionTo = 'to' in currentAction ? currentAction.to : null;

  return (
    <Card
      className="page-surface border-border/70 shadow-[var(--shadow-control)]"
      data-testid="structured-policy-canvas"
    >
      <CardContent className="grid gap-1.5 p-1.5 xl:grid-cols-[17rem_minmax(0,1fr)_15rem]">
        <div className="grid min-h-16 content-center rounded-xl border border-border bg-muted/20 px-3 py-1.5">
          <span className="text-xs font-semibold text-muted-foreground">当前数据集</span>
          <span className="truncate text-sm font-semibold" title={dataset?.name}>
            {dataset?.name ?? '未选择'}
          </span>
          <span className="truncate text-xs text-muted-foreground">
            {dataset
              ? `${dataset.dataset_type.toUpperCase()} · ${dataset.column_count} 列 ${dataset.row_count_estimate ?? 0} 行`
              : '先从左侧选择治理对象'}
          </span>
        </div>
        <div className="relative rounded-xl border border-border bg-background px-3 py-1.5">
          <div className="pointer-events-none absolute left-12 right-12 top-6 hidden h-px bg-border lg:block" />
          <div className="relative z-10 grid h-full gap-1 lg:grid-cols-5">
            {nodes.map((node, index) => (
              <div
                key={node.key}
                data-testid={`policy-step-${node.key}`}
                className={cn(
                  'grid min-h-14 grid-rows-[auto_auto_auto] justify-items-center gap-0.5 rounded-lg px-2 py-0.5 text-center transition',
                  node.active && 'bg-muted/40',
                )}
              >
                <span
                  className={cn(
                    'grid size-7 place-items-center rounded-full border bg-card shadow-[var(--shadow-sm)]',
                    node.done
                      ? 'border-[var(--success-border)] bg-[var(--success-surface)]'
                      : node.active
                        ? 'border-foreground bg-background'
                        : 'border-border bg-card',
                  )}
                >
                  {node.confirmable ? (
                    <Checkbox
                      data-testid="policy-confirm-checkbox"
                      checked={policyConfirmed}
                      disabled={!canConfirmPolicy || Boolean(busy)}
                      onCheckedChange={(checked) => onConfirmChange(checked === true)}
                    />
                  ) : node.done ? (
                    <CheckCircle2 className="size-3.5 text-[var(--success-foreground)]" />
                  ) : (
                    <span className="text-xs font-semibold text-muted-foreground">{index + 1}</span>
                  )}
                </span>
                <span className="block max-w-full truncate text-[13px] font-semibold">{node.title}</span>
                <span className="block max-w-full truncate text-[11px] text-muted-foreground">{node.desc}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="grid min-h-16 grid-rows-[auto_1fr_auto] rounded-xl border border-foreground bg-foreground p-2 text-background">
          <span className="flex items-center gap-2 text-xs font-semibold text-background/70">
            <CurrentIcon className="size-4" />
            当前动作
          </span>
          <span className="min-w-0 self-center">
            <span className="block truncate text-sm font-semibold">{currentAction.label}</span>
            <span className="block truncate text-xs text-background/65">{currentAction.detail}</span>
          </span>
          {currentActionTo ? (
            <Button asChild size="sm" className="h-8 w-full bg-background text-foreground hover:bg-background/90">
              <Link to={currentActionTo} data-testid="policy-current-action">
                {currentAction.label}
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          ) : (
            <Button
              type="button"
              size="sm"
              className="h-8 w-full bg-background text-foreground hover:bg-background/90"
              data-testid="policy-current-action"
              onClick={'onClick' in currentAction ? currentAction.onClick : undefined}
              disabled={('disabled' in currentAction && currentAction.disabled) || Boolean(busy)}
            >
              {currentAction.label}
              <ArrowRight className="size-4" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function DatasetPickerCard({
  datasets,
  connections,
  selectedDatasetId,
  reviewedDatasetIds,
  dirtyDatasetId,
  onSelect,
  compact,
}: {
  datasets: StructuredDataset[];
  connections?: StructuredConnection[];
  selectedDatasetId: string;
  reviewedDatasetIds?: Set<string>;
  dirtyDatasetId?: string;
  onSelect: (datasetId: string) => void;
  compact?: boolean;
}) {
  const [query, setQuery] = React.useState('');
  const [page, setPage] = React.useState(0);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredDatasets = React.useMemo(
    () =>
      normalizedQuery
        ? datasets.filter((dataset) =>
            [dataset.name, dataset.source_kind, dataset.schema_name, dataset.table_name]
              .filter(Boolean)
              .some((value) => String(value).toLowerCase().includes(normalizedQuery)),
          )
        : datasets,
    [datasets, normalizedQuery],
  );
  const orderedDatasets = React.useMemo(
    () => [...filteredDatasets].sort(compareStructuredDatasetsForReview),
    [filteredDatasets],
  );
  const identityContextById = React.useMemo(
    () => buildDatasetIdentityContexts(orderedDatasets, connections ?? []),
    [connections, orderedDatasets],
  );
  const pageSize = compact ? 3 : 8;
  const orderedDatasetIds = React.useMemo(() => orderedDatasets.map((dataset) => dataset.id).join('|'), [orderedDatasets]);
  const pageCount = Math.max(1, Math.ceil(orderedDatasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = orderedDatasets.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const selectedDataset = datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null;
  const scopeSummary = React.useMemo(
    () => buildDatasetScopeSummary(selectedDataset, datasets, connections ?? []),
    [connections, datasets, selectedDataset],
  );
  const reviewedCount = reviewedDatasetIds
    ? datasets.filter((dataset) => reviewedDatasetIds.has(dataset.id)).length
    : 0;
  const dirtyCount = dirtyDatasetId && datasets.some((dataset) => dataset.id === dirtyDatasetId) ? 1 : 0;
  const pendingCount = Math.max(datasets.length - reviewedCount - dirtyCount, 0);
  const selectedScopeCount = selectedDataset
    ? datasets.filter((dataset) => isSameDatasetReviewScope(dataset, selectedDataset)).length
    : 0;
  const selectedScopeLabel = selectedDataset?.connection_id ? '当前连接' : '当前来源';
  const listSummary = datasets.length
    ? [
        normalizedQuery ? `筛选 ${orderedDatasets.length}/${datasets.length}` : `共 ${datasets.length} 个`,
        `已保存 ${reviewedCount}`,
        dirtyCount > 0 ? `待保存 ${dirtyCount}` : '',
        `待复核 ${pendingCount}`,
        selectedScopeCount > 1 ? `${selectedScopeLabel} ${selectedScopeCount}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
    : '选择一个数据集进行字段策略维护。';

  React.useEffect(() => {
    setPage(0);
  }, [orderedDatasetIds]);

  React.useEffect(() => {
    if (!selectedDatasetId) return;
    const selectedIndex = orderedDatasets.findIndex((dataset) => dataset.id === selectedDatasetId);
    if (selectedIndex < 0) return;
    const selectedPage = Math.floor(selectedIndex / pageSize);
    setPage((current) => (current === selectedPage ? current : selectedPage));
  }, [orderedDatasetIds, orderedDatasets, pageSize, selectedDatasetId]);

  return (
    <Card className="page-surface flex min-h-0 flex-col border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-3 py-2.5">
        <CardTitle className="text-sm">数据集</CardTitle>
        <CardDescription>{listSummary}</CardDescription>
      </CardHeader>
      <CardContent className="grid min-h-0 flex-1 grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-2 px-3 pb-3 pt-0">
        {scopeSummary ? (
          <div
            className="grid gap-1 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5"
            data-testid="dataset-scope-summary"
          >
            <span className="flex min-w-0 items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="block text-[10px] font-medium uppercase text-muted-foreground">{scopeSummary.eyebrow}</span>
                <span className="block truncate text-xs font-semibold" title={scopeSummary.title}>
                  {scopeSummary.title}
                </span>
              </span>
              <Badge variant="outline" className="shrink-0 text-[10px]">
                {scopeSummary.badge}
              </Badge>
            </span>
            <span className="truncate text-[11px] text-muted-foreground" title={scopeSummary.detail}>
              {scopeSummary.detail}
            </span>
          </div>
        ) : (
          <div className="hidden" />
        )}
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索数据集"
          className="h-9"
        />
        <div className="grid content-start gap-2 overflow-hidden pr-1">
          {filteredDatasets.length === 0 ? (
            <EmptyState icon={TableProperties} text="暂无数据集" />
          ) : (
            visibleDatasets.map((dataset) => {
              const selected = selectedDatasetId === dataset.id;
              const dirty = dirtyDatasetId === dataset.id;
              const reviewed = reviewedDatasetIds?.has(dataset.id) ?? false;
              return (
                <button
                  key={dataset.id}
                  type="button"
                  onClick={() => onSelect(dataset.id)}
                  data-testid="dataset-picker-item"
                  data-dataset-name={dataset.table_name ?? dataset.name}
                  data-dataset-context={datasetIdentityContextText(dataset, identityContextById.get(dataset.id))}
                  className={cn(
                    'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border text-left transition hover:bg-muted/35',
                    compact ? 'min-h-12 px-2.5 py-1.5' : 'min-h-14 px-3 py-2',
                    selected && 'border-foreground bg-muted/45',
                  )}
                >
                  <DatasetIdentity dataset={dataset} compact identityContext={identityContextById.get(dataset.id)} />
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    <CheckCircle2
                      className={cn(
                        'size-4 text-muted-foreground',
                        selected && 'text-foreground',
                        reviewed && 'text-[var(--success-foreground)]',
                        dirty && 'text-[var(--warning-foreground)]',
                      )}
                    />
                    {dirty || reviewed ? (
                      <span
                        className={cn(
                          'rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                          dirty
                            ? 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]'
                            : 'bg-[var(--success-surface)] text-[var(--success-foreground)]',
                        )}
                      >
                        {dirty ? '待保存' : '已保存'}
                      </span>
                    ) : null}
                  </span>
                </button>
              );
            })
          )}
        </div>
        {filteredDatasets.length > 0 ? (
          <ListPager
            label="数据集"
            page={safePage}
            pageCount={pageCount}
            total={orderedDatasets.length}
            pageSize={pageSize}
            visibleCount={visibleDatasets.length}
            onPageChange={setPage}
          />
        ) : (
          <div className="min-h-0" />
        )}
      </CardContent>
    </Card>
  );
}

function ProfilePolicyCard({
  dataset,
  profile,
  policy,
  fieldPage,
  currentPageReviewed,
  reviewedPageCount,
  pageCount,
  onFieldPageChange,
  onPolicyChange,
}: {
  dataset: StructuredDataset | null;
  profile: StructuredProfile | null;
  policy: StructuredColumnPolicy[];
  fieldPage: number;
  currentPageReviewed: boolean;
  reviewedPageCount: number;
  pageCount: number;
  onFieldPageChange: (page: number) => void;
  onPolicyChange: (policy: StructuredColumnPolicy[]) => void;
}) {
  const [fieldQuery, setFieldQuery] = React.useState('');
  const profileColumns = profile?.columns ?? EMPTY_STRUCTURED_COLUMNS;
  const policyByColumn = new Map(policy.map((item) => [item.column, item]));
  const reviewColumns = React.useMemo(() => orderColumnsForPolicyReview(profileColumns), [profileColumns]);
  const normalizedFieldQuery = fieldQuery.trim().toLowerCase();
  const matchedColumnIndexes = React.useMemo(
    () =>
      normalizedFieldQuery
        ? reviewColumns
            .map((column, index) => ({ column, index }))
            .filter(({ column }) => matchesPolicyColumnQuery(column, normalizedFieldQuery))
            .map(({ index }) => index)
        : [],
    [normalizedFieldQuery, reviewColumns],
  );
  const pageSize = FIELD_POLICY_PAGE_SIZE;
  const safePage = Math.min(fieldPage, pageCount - 1);
  const visibleColumns = reviewColumns.slice(safePage * pageSize, safePage * pageSize + pageSize);
  const visibleMatchedCount = normalizedFieldQuery
    ? visibleColumns.filter((column) => matchesPolicyColumnQuery(column, normalizedFieldQuery)).length
    : 0;
  const visiblePolicyRows = visibleColumns.map((column) => ({
    column,
    current: policyByColumn.get(column.name) ?? profileToPolicy(column),
  }));
  const visibleRedactedCount = visiblePolicyRows.filter(
    ({ current }) => current.enabled && current.action !== 'keep',
  ).length;
  const visibleHighRiskRows = visiblePolicyRows.filter(({ column }) =>
    ['high', 'critical'].includes(column.risk_level),
  );
  const visibleHighRiskTotal = visibleHighRiskRows.length;
  const visibleHighRiskRedacted = visibleHighRiskRows.filter(
    ({ current }) => current.enabled && current.action !== 'keep',
  ).length;
  const visibleRangeStart = profileColumns.length === 0 ? 0 : safePage * pageSize + 1;
  const visibleRangeEnd = Math.min(profileColumns.length, safePage * pageSize + visibleColumns.length);
  const matchIndexSignature = matchedColumnIndexes.join('|');
  const autoJumpSignature = `${profile?.dataset_id ?? ''}:${normalizedFieldQuery}:${matchIndexSignature}`;
  const lastAutoJumpSignatureRef = React.useRef('');

  React.useEffect(() => {
    setFieldQuery('');
    lastAutoJumpSignatureRef.current = '';
  }, [profile?.dataset_id]);

  React.useEffect(() => {
    if (!normalizedFieldQuery || matchedColumnIndexes.length === 0) {
      lastAutoJumpSignatureRef.current = '';
      return;
    }
    if (lastAutoJumpSignatureRef.current === autoJumpSignature) return;
    lastAutoJumpSignatureRef.current = autoJumpSignature;
    const targetPage = Math.floor(matchedColumnIndexes[0] / pageSize);
    if (targetPage !== safePage) onFieldPageChange(targetPage);
  }, [autoJumpSignature, matchedColumnIndexes, normalizedFieldQuery, onFieldPageChange, pageSize, safePage]);

  function goToFieldMatch(direction: -1 | 1) {
    if (matchedColumnIndexes.length === 0) return;
    const pageStart = safePage * pageSize;
    const pageEnd = pageStart + pageSize;
    const currentMatchIndex = matchedColumnIndexes.findIndex((index) => index >= pageStart && index < pageEnd);
    const baseIndex = currentMatchIndex >= 0 ? currentMatchIndex : direction > 0 ? -1 : 0;
    const nextMatchIndex = (baseIndex + direction + matchedColumnIndexes.length) % matchedColumnIndexes.length;
    onFieldPageChange(Math.floor(matchedColumnIndexes[nextMatchIndex] / pageSize));
  }

  return (
    <Card className="page-surface flex min-h-0 flex-col border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="flex-row items-start justify-between gap-3 px-3 py-2">
        <div className="min-w-0">
          <CardTitle className="truncate text-sm">{dataset ? dataset.name : '字段策略'}</CardTitle>
          {profile?.semantic_inference ? <SemanticInferenceSummary info={profile.semantic_inference} /> : null}
        </div>
        {profileColumns.length > 0 ? (
          <div className="flex min-w-[18rem] max-w-[28rem] flex-1 items-center justify-end gap-1.5">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={fieldQuery}
                onChange={(event) => setFieldQuery(event.target.value)}
                placeholder="定位字段、实体或样本"
                className="h-8 pl-7 pr-2 text-xs"
                data-testid="policy-field-search"
              />
            </div>
            <span
              className="min-w-16 shrink-0 text-right text-[11px] text-muted-foreground"
              data-testid="policy-field-search-count"
            >
              {normalizedFieldQuery
                ? matchedColumnIndexes.length > 0
                  ? `匹配 ${matchedColumnIndexes.length}`
                  : '无匹配'
                : '定位'}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 w-8 shrink-0 p-0"
              disabled={matchedColumnIndexes.length === 0}
              onClick={() => goToFieldMatch(-1)}
              aria-label="上一个匹配字段"
            >
              <ArrowLeft className="size-3.5" />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 w-8 shrink-0 p-0"
              disabled={matchedColumnIndexes.length === 0}
              onClick={() => goToFieldMatch(1)}
              aria-label="下一个匹配字段"
            >
              <ArrowRight className="size-3.5" />
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)_auto] gap-1 px-3 pb-2.5 pt-0">
        {profileColumns.length > 0 ? <PolicySummaryStrip columns={profileColumns} policy={policy} /> : null}
        <div className="min-h-0 overflow-hidden rounded-xl border border-border" data-testid="policy-table-frame">
          {profileColumns.length === 0 ? (
            <EmptyState
              icon={ShieldCheck}
              text={dataset ? '点击“生成字段策略”后开始复核' : '先选择数据集'}
            />
          ) : (
            <table className="w-full table-fixed text-[11.5px]" data-testid="policy-table">
              <thead className="sticky top-0 bg-muted text-[11px] text-muted-foreground">
                <tr>
                  <th className="w-[31%] px-2 py-1 text-left">字段</th>
                  <th className="w-[15%] px-2 py-1 text-left">实体</th>
                  <th className="w-[12%] px-2 py-1 text-left">风险</th>
                  <th className="w-[12%] px-2 py-1 text-left">置信度</th>
                  <th className="w-[23%] px-2 py-1 text-left">动作</th>
                  <th className="w-[7%] px-2 py-1 text-left">启用</th>
                </tr>
              </thead>
              <tbody>
                {visiblePolicyRows.map(({ column, current }) => {
                  const adjusted = isPolicyAdjusted(column, current);
                  const matchesSearch = Boolean(
                    normalizedFieldQuery && matchesPolicyColumnQuery(column, normalizedFieldQuery),
                  );
                  return (
                    <tr
                      key={column.name}
                      className={cn(
                        'border-t border-border',
                        matchesSearch && 'bg-[var(--success-surface)]',
                        adjusted && 'bg-[var(--warning-surface)]',
                      )}
                      data-testid="policy-row"
                      data-policy-column={column.name}
                      data-policy-adjusted={adjusted ? 'true' : 'false'}
                      data-policy-search-match={matchesSearch ? 'true' : 'false'}
                    >
                      <td className="max-w-56 px-2 py-1">
                        <span className="flex min-w-0 items-center gap-1.5 leading-tight" title={column.name}>
                          <span className="min-w-0 truncate font-medium">{column.name}</span>
                          {adjusted ? (
                            <span className="shrink-0 rounded-full bg-background px-1.5 py-0.5 text-[9.5px] font-medium text-[var(--warning-foreground)]">
                              已调整
                            </span>
                          ) : null}
                        </span>
                        <span
                          className="block truncate text-[10px] leading-[1.05] text-muted-foreground"
                          title={column.sample_values.map(displayValue).join(' / ')}
                        >
                          {column.sample_values.map(displayValue).join(' / ')}
                        </span>
                      </td>
                      <td className="px-2 py-1">{column.entity_type}</td>
                      <td className="px-2 py-1">
                        <RiskBadge risk={column.risk_level} />
                      </td>
                      <td className="px-2 py-1">{Math.round(column.confidence * 100)}%</td>
                      <td className="px-2 py-1">
                        <span className="flex min-w-0 items-center gap-1.5">
                          <Select
                            value={current.action}
                            onValueChange={(action) => {
                              const nextAction = action as StructuredPolicyAction;
                              onPolicyChange(
                                updatePolicy(policy, column, {
                                  action: nextAction,
                                  enabled: nextAction !== 'keep',
                                }),
                              );
                            }}
                          >
                            <SelectTrigger className="h-6 min-w-[4.75rem] flex-1 justify-between px-2 text-[11px]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {actionOptions.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {adjusted ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-6 shrink-0 px-2 text-[10px]"
                              data-testid="policy-reset-recommendation"
                              onClick={() => onPolicyChange(updatePolicy(policy, column, profileToPolicy(column)))}
                            >
                              恢复
                            </Button>
                          ) : null}
                        </span>
                      </td>
                      <td className="px-2 py-1">
                        <Checkbox
                          checked={current.enabled && current.action !== 'keep'}
                          onCheckedChange={(checked) => {
                            const enabled = checked === true;
                            onPolicyChange(
                              updatePolicy(policy, column, {
                                enabled,
                                action: enabled ? defaultEnabledPolicyAction(column, current) : 'keep',
                              }),
                            );
                          }}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="flex min-h-8 items-center justify-between gap-3 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5 text-xs text-muted-foreground">
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="min-w-0 truncate">
              {profileColumns.length === 0
                ? '生成字段策略后开始复核'
                : `字段 ${visibleRangeStart}-${visibleRangeEnd} / ${profileColumns.length} · 第 ${safePage + 1}/${pageCount} 页 · 已确认 ${reviewedPageCount}/${pageCount} 页`}
            </span>
            {profileColumns.length > 0 ? (
              <span className="hidden shrink-0 text-[10px] text-muted-foreground lg:inline">按风险优先排序</span>
            ) : null}
            {profileColumns.length > 0 ? (
              <span
                className="shrink-0 rounded-full border border-border bg-background px-2 py-0.5 text-[10px] text-muted-foreground"
                data-testid="policy-page-summary"
              >
                本页启用 {visibleRedactedCount}/{visibleColumns.length} · 高风险{' '}
                {visibleHighRiskTotal > 0 ? `${visibleHighRiskRedacted}/${visibleHighRiskTotal}` : '无'}
                {normalizedFieldQuery ? ` · 匹配 ${visibleMatchedCount}/${matchedColumnIndexes.length}` : ''}
              </span>
            ) : null}
            {profileColumns.length > 0 ? (
              <Badge
                variant="outline"
                className={cn(
                  'shrink-0 rounded-full text-[10px]',
                  currentPageReviewed
                    ? 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]'
                    : 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                )}
              >
                {currentPageReviewed ? '当前页已确认' : '当前页待确认'}
              </Badge>
            ) : null}
          </span>
          {profileColumns.length > pageSize ? (
            <span className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={safePage <= 0}
                onClick={() => onFieldPageChange(safePage - 1)}
              >
                上一组
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7"
                disabled={safePage >= pageCount - 1}
                onClick={() => onFieldPageChange(safePage + 1)}
              >
                下一组
              </Button>
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function PreviewCard({
  preview,
  profile,
  loading = false,
}: {
  preview: StructuredPreview | null;
  profile: StructuredProfile | null;
  loading?: boolean;
}) {
  const columns = React.useMemo(() => {
    if (!preview) return [];
    const profileByColumn = new Map((profile?.columns ?? []).map((column, index) => [column.name, { column, index }]));
    const previewOrder = new Map(preview.columns.map((column, index) => [column, index]));
    const riskWeight: Record<StructuredColumnProfile['risk_level'], number> = {
      critical: 4,
      high: 3,
      medium: 2,
      low: 1,
    };
    const redactedColumns = preview.policy
      .filter((item) => item.enabled && item.action !== 'keep' && preview.columns.includes(item.column))
      .map((item) => item.column)
      .sort((left, right) => {
        const leftProfile = profileByColumn.get(left);
        const rightProfile = profileByColumn.get(right);
        const leftRisk = leftProfile ? riskWeight[leftProfile.column.risk_level] : 0;
        const rightRisk = rightProfile ? riskWeight[rightProfile.column.risk_level] : 0;
        if (leftRisk !== rightRisk) return rightRisk - leftRisk;
        return (previewOrder.get(left) ?? 0) - (previewOrder.get(right) ?? 0);
      });
    const fallbackColumns = preview.columns.filter((column) => !redactedColumns.includes(column));
    return [...redactedColumns, ...fallbackColumns].slice(0, 4);
  }, [preview, profile]);
  const redactedColumnCount =
    preview?.policy.filter((item) => item.enabled && item.action !== 'keep' && preview.columns.includes(item.column)).length ?? 0;
  const redactedColumnSet = React.useMemo(
    () =>
      new Set(
        preview?.policy
          .filter((item) => item.enabled && item.action !== 'keep' && preview.columns.includes(item.column))
          .map((item) => item.column) ?? [],
      ),
    [preview],
  );
  const previewStats = React.useMemo(() => {
    const changedColumns = new Set<string>();
    let changedCellCount = 0;
    let changedRedactedCellCount = 0;
    if (!preview) {
      return {
        displayedRedactedColumnCount: 0,
        hiddenRedactedColumnCount: 0,
        contextColumnCount: 0,
        changedColumns,
        changedRedactedColumnCount: 0,
        changedCellCount,
        changedRedactedCellCount,
      };
    }
    const rowCount = Math.min(preview.original_rows.length, preview.redacted_rows.length, 5);
    for (const column of preview.columns) {
      for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
        const originalValue = displayValue(preview.original_rows[rowIndex]?.[column]);
        const redactedValue = displayValue(preview.redacted_rows[rowIndex]?.[column]);
        if (originalValue !== redactedValue) {
          changedColumns.add(column);
          changedCellCount += 1;
          if (redactedColumnSet.has(column)) changedRedactedCellCount += 1;
        }
      }
    }
    const displayedRedactedColumnCount = columns.filter((column) => redactedColumnSet.has(column)).length;
    const changedRedactedColumnCount = Array.from(changedColumns).filter((column) => redactedColumnSet.has(column)).length;
    return {
      displayedRedactedColumnCount,
      hiddenRedactedColumnCount: Math.max(redactedColumnSet.size - displayedRedactedColumnCount, 0),
      contextColumnCount: Math.max(columns.length - displayedRedactedColumnCount, 0),
      changedColumns,
      changedRedactedColumnCount,
      changedCellCount,
      changedRedactedCellCount,
    };
  }, [columns, preview, redactedColumnSet]);
  const previewContextColumnCount = previewStats.contextColumnCount;
  const previewDescription = loading
    ? '正在按已保存策略生成样本预览。'
    : preview
    ? previewContextColumnCount > 0
      ? `优先展示 ${previewStats.displayedRedactedColumnCount}/${redactedColumnCount} 个脱敏字段，并补充 ${previewContextColumnCount} 个上下文字段。`
      : `展示 ${columns.length}/${redactedColumnCount} 个脱敏字段的前 5 行样本。`
    : '保存策略后优先查看被脱敏字段的前 5 行样本。';
  const previewWarning = Boolean(preview && redactedColumnCount > 0 && previewStats.changedRedactedColumnCount === 0);
  return (
    <Card className="page-surface flex min-h-0 flex-col border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="px-3 py-2.5">
        <CardTitle className="text-sm">脱敏预览</CardTitle>
        <CardDescription>{previewDescription}</CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 px-3 pb-3 pt-0">
        {!preview ? (
          <EmptyState icon={Eye} text={loading ? '正在生成脱敏预览' : '保存策略后查看脱敏字段预览'} />
        ) : (
          <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_minmax(0,1fr)] gap-2">
            <PreviewValidationStrip
              columnCount={columns.length}
              displayedRedactedColumnCount={previewStats.displayedRedactedColumnCount}
              totalRedactedColumnCount={redactedColumnCount}
              hiddenRedactedColumnCount={previewStats.hiddenRedactedColumnCount}
              changedColumnCount={previewStats.changedColumns.size}
              changedRedactedColumnCount={previewStats.changedRedactedColumnCount}
              changedCellCount={previewStats.changedCellCount}
              changedRedactedCellCount={previewStats.changedRedactedCellCount}
              warning={previewWarning}
            />
            <PreviewTable title="原始数据" columns={columns} rows={preview.original_rows} />
            <PreviewTable
              title="去标识化后"
              columns={columns}
              rows={preview.redacted_rows}
              muted
              compareRows={preview.original_rows}
              changedColumns={previewStats.changedColumns}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PreviewValidationStrip({
  columnCount,
  displayedRedactedColumnCount,
  totalRedactedColumnCount,
  hiddenRedactedColumnCount,
  changedColumnCount,
  changedRedactedColumnCount,
  changedCellCount,
  changedRedactedCellCount,
  warning,
}: {
  columnCount: number;
  displayedRedactedColumnCount: number;
  totalRedactedColumnCount: number;
  hiddenRedactedColumnCount: number;
  changedColumnCount: number;
  changedRedactedColumnCount: number;
  changedCellCount: number;
  changedRedactedCellCount: number;
  warning: boolean;
}) {
  return (
    <div
      className={cn(
        'flex min-h-9 flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-1.5 text-xs',
        warning
          ? 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]'
          : 'border-[var(--success-border)] bg-[var(--success-surface)] text-[var(--success-foreground)]',
      )}
      data-testid="preview-validation"
      data-preview-changed-columns={changedColumnCount}
      data-preview-changed-redacted-columns={changedRedactedColumnCount}
      data-preview-changed-cells={changedCellCount}
      data-preview-changed-redacted-cells={changedRedactedCellCount}
    >
      <span className="font-semibold">{warning ? '预览待检查' : '预览验证'}</span>
      <span className="flex flex-wrap items-center gap-2 text-muted-foreground">
        <span>显示 {columnCount} 列</span>
        <span>
          脱敏列 {displayedRedactedColumnCount}/{totalRedactedColumnCount}
        </span>
        <span>
          脱敏变化 {changedRedactedColumnCount}/{totalRedactedColumnCount}
        </span>
        <span>变化列 {changedColumnCount}</span>
        <span>改写样本 {changedCellCount}</span>
        {hiddenRedactedColumnCount > 0 ? <span>未展示 {hiddenRedactedColumnCount} 列</span> : null}
      </span>
      {warning ? <span className="basis-full text-[11px]">已配置脱敏，但当前样本未看到变化，需检查策略或样本值。</span> : null}
    </div>
  );
}

function PolicySummaryStrip({
  columns,
  policy,
}: {
  columns: StructuredColumnProfile[];
  policy: StructuredColumnPolicy[];
}) {
  const policyByColumn = new Map(policy.map((item) => [item.column, item]));
  const policyRows = columns.map((column) => ({
    column,
    current: policyByColumn.get(column.name) ?? profileToPolicy(column),
  }));
  const redactedRows = policyRows.filter(({ current }) => current.enabled && current.action !== 'keep');
  const highRiskRows = policyRows.filter(({ column }) => ['high', 'critical'].includes(column.risk_level));
  const redacted = redactedRows.length;
  const retained = columns.length - redacted;
  const highRiskTotal = highRiskRows.length;
  const highRiskRedacted = highRiskRows.filter(({ current }) => current.enabled && current.action !== 'keep').length;
  const semanticRows = policyRows.filter(({ column }) =>
    (column.reasons ?? []).some((reason) => String(reason).includes('semantic')),
  );
  const semanticRedacted = redactedRows.filter(({ column }) =>
    (column.reasons ?? []).some((reason) => String(reason).includes('semantic')),
  ).length;
  const semanticTotal = semanticRows.length;
  const adjustedCount = policyRows.filter(({ column, current }) => isPolicyAdjusted(column, current)).length;
  const total = Math.max(columns.length, 1);
  const redactedPct = (redacted / total) * 100;
  const retainedPct = (retained / total) * 100;
  const riskPct = highRiskTotal > 0 ? (highRiskRedacted / highRiskTotal) * 100 : 0;
  const highRiskRetained = Math.max(highRiskTotal - highRiskRedacted, 0);
  const formatPct = (value: number) => {
    const rounded = Math.round(value * 10) / 10;
    return Number.isInteger(rounded) ? `${rounded}%` : `${rounded.toFixed(1)}%`;
  };
  const highRiskCoverage = highRiskTotal > 0 ? `${highRiskRedacted}/${highRiskTotal}` : '无';
  const highRiskTone =
    highRiskTotal === 0
      ? 'bg-muted text-foreground'
      : highRiskRetained === 0
        ? 'bg-[var(--success-surface)] text-[var(--success-foreground)]'
        : 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]';

  const items = [
    { label: '字段总数', value: columns.length, tone: 'bg-muted text-foreground' },
    { label: '启用脱敏', value: redacted, tone: 'bg-foreground text-background' },
    { label: '保留字段', value: retained, tone: 'bg-muted text-foreground' },
    { label: '高风险已处理', value: highRiskCoverage, tone: highRiskTone },
    { label: '语义命中字段', value: semanticTotal, tone: 'bg-[var(--success-surface)] text-[var(--success-foreground)]' },
    { label: '语义脱敏', value: semanticRedacted, tone: 'bg-muted text-foreground' },
    {
      label: '人工调整',
      value: adjustedCount,
      tone: adjustedCount > 0 ? 'bg-[var(--warning-surface)] text-[var(--warning-foreground)]' : 'bg-muted text-foreground',
    },
  ];

  return (
    <div className="grid gap-1 rounded-xl border border-border bg-muted/20 px-2.5 py-1.5" data-testid="policy-summary">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        {items.map((item) => (
          <span key={item.label} className="inline-flex items-center gap-1 text-[10.5px] text-muted-foreground">
            <span>{item.label}</span>
            <span className={cn('rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold', item.tone)}>
              {item.value}
            </span>
          </span>
        ))}
      </div>
      <div
        className="flex h-2 overflow-hidden rounded-full bg-muted"
        aria-label={`脱敏 ${redacted} 个字段，保留或不处理 ${retained} 个字段`}
        data-testid="policy-distribution"
      >
        <span className="bg-foreground" style={{ width: `${redactedPct}%` }} />
        <span className="bg-muted-foreground/25" style={{ width: `${retainedPct}%` }} />
      </div>
      <div className="hidden flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground 2xl:flex">
        <span>
          当前策略：字段 {columns.length} = 启用脱敏 {redacted} + 保留/不处理 {retained}
        </span>
        <span>脱敏 {redacted}/{columns.length}（{formatPct(redactedPct)}）</span>
        <span>保留 {retained}/{columns.length}（{formatPct(retainedPct)}）</span>
        <span>
          高风险已处理 {highRiskCoverage}
          {highRiskTotal > 0 ? `（${formatPct(riskPct)}）` : ''}
          {highRiskRetained > 0 ? `，仍保留 ${highRiskRetained} 个需确认` : ''}
        </span>
        <span>语义命中 {semanticTotal}，启用脱敏 {semanticRedacted}</span>
        <span>人工调整 {adjustedCount} 个</span>
      </div>
    </div>
  );
}

function DeliveryChecklist({
  selectedCount,
  unreviewedCount,
  exportFormat,
  deliveryModeLabel,
  latestJobStatus,
}: {
  selectedCount: number;
  unreviewedCount: number;
  exportFormat: StructuredExportFormat;
  deliveryModeLabel: string;
  latestJobStatus: string;
}) {
  const checks = [
    {
      label: '选择数据集',
      detail: selectedCount > 0 ? `${selectedCount} 个已选` : '等待选择',
      done: selectedCount > 0,
    },
    {
      label: '任务模式',
      detail: deliveryModeLabel,
      done: selectedCount > 0,
    },
    {
      label: '策略复核',
      detail:
        selectedCount === 0
          ? '待选择'
          : unreviewedCount > 0
            ? `已选均已复核；${unreviewedCount} 个未纳入`
            : '已选均已复核',
      done: selectedCount > 0,
    },
    {
      label: '包内格式',
      detail: `${exportFormat.toUpperCase()} · ZIP 包`,
      done: true,
    },
    {
      label: '后台任务',
      detail: latestJobStatus ? structuredJobStatusLabel(latestJobStatus) : '未创建',
      done: latestJobStatus === 'completed',
    },
  ];
  return (
    <div className="grid gap-1.5 rounded-xl border border-border bg-muted/20 p-1.5 sm:grid-cols-2">
      {checks.map((check) => (
        <div key={check.label} className="flex min-w-0 items-center justify-between gap-2 rounded-lg bg-background px-2.5 py-1.5">
          <span className="flex min-w-0 items-center gap-2">
            <CheckCircle2 className={cn('size-4 shrink-0', check.done ? 'text-[var(--success-foreground)]' : 'text-muted-foreground')} />
            <span className="truncate text-sm font-medium">{check.label}</span>
          </span>
          <span className="truncate text-xs text-muted-foreground">{check.detail}</span>
        </div>
      ))}
    </div>
  );
}

function structuredJobStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    pending: '待处理',
    processing: '处理中',
    running: '处理中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };
  return labels[status] ?? status;
}

function buildDatasetIdentityContexts(
  datasets: StructuredDataset[],
  connections: StructuredConnection[],
): Map<string, DatasetIdentityContext> {
  const connectionNameById = new Map(connections.map((connection) => [connection.id, connection.display_name]));
  const duplicateGroups = new Map<string, StructuredDataset[]>();
  datasets.forEach((dataset) => {
    const key = datasetIdentityName(dataset).trim().toLowerCase();
    duplicateGroups.set(key, [...(duplicateGroups.get(key) ?? []), dataset]);
  });

  const contexts = new Map<string, DatasetIdentityContext>();
  duplicateGroups.forEach((group) => {
    group.forEach((dataset, index) => {
      contexts.set(dataset.id, {
        connectionName: dataset.connection_id ? connectionNameById.get(dataset.connection_id) : undefined,
        duplicateCount: group.length,
        duplicateIndex: index + 1,
      });
    });
  });
  return contexts;
}

function datasetIdentityName(dataset: StructuredDataset): string {
  return dataset.connection_id ? dataset.table_name || dataset.name : dataset.name;
}

function datasetIdentityContextText(dataset: StructuredDataset, context?: DatasetIdentityContext): string {
  const parts: string[] = [];
  if (dataset.connection_id) {
    if (context?.connectionName) parts.push(context.connectionName);
    if (dataset.schema_name || dataset.table_name) {
      parts.push([dataset.schema_name, dataset.table_name ?? dataset.name].filter(Boolean).join('.'));
    }
  } else if (context && context.duplicateCount > 1) {
    parts.push(`同名 ${context.duplicateIndex}/${context.duplicateCount}`);
    if (dataset.source_id) parts.push(`来源 ${shortEntityId(dataset.source_id)}`);
  }
  parts.push(`${dataset.source_kind.toUpperCase()} · ${datasetTypeLabel(dataset)} · ${dataset.column_count} 列`);
  return parts.filter(Boolean).join(' · ');
}

function shortEntityId(value: string): string {
  return value.replace(/-/g, '').slice(0, 8) || value.slice(0, 8);
}

function matchesDeliveryDatasetQuery(
  dataset: StructuredDataset,
  query: string,
  connections: StructuredConnection[],
): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  const connectionName = dataset.connection_id
    ? connections.find((connection) => connection.id === dataset.connection_id)?.display_name
    : '';
  return [
    dataset.name,
    dataset.table_name,
    dataset.schema_name,
    dataset.source_kind,
    dataset.dataset_type,
    dataset.shape_kind,
    connectionName,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalized));
}

function DeliveryDatasetCard({
  datasets,
  connections,
  selectedIds,
  onToggle,
  onSelectAll,
  onClear,
}: {
  datasets: StructuredDataset[];
  connections: StructuredConnection[];
  selectedIds: Set<string>;
  onToggle: (datasetId: string) => void;
  onSelectAll: (datasetIds?: string[]) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = React.useState('');
  const [page, setPage] = React.useState(0);
  const pageSize = 5;
  const deliverableDatasets = React.useMemo(() => datasets.filter(isDatasetDeliveryReady), [datasets]);
  const deliverableIds = React.useMemo(() => new Set(deliverableDatasets.map((dataset) => dataset.id)), [deliverableDatasets]);
  const deliverableCount = deliverableDatasets.length;
  const effectiveSelectedCount = Array.from(selectedIds).filter((datasetId) => deliverableIds.has(datasetId)).length;
  const datasetListSignature = React.useMemo(
    () => datasets.map((dataset) => `${dataset.id}:${isDatasetDeliveryReady(dataset) ? 'ready' : 'pending'}`).join('|'),
    [datasets],
  );
  const orderedDatasets = React.useMemo(
    () =>
      datasets.filter((dataset) => matchesDeliveryDatasetQuery(dataset, query, connections)).sort((left, right) => {
        const leftReviewed = isDatasetDeliveryReady(left);
        const rightReviewed = isDatasetDeliveryReady(right);
        if (leftReviewed !== rightReviewed) return leftReviewed ? -1 : 1;
        return compareStructuredDatasetsForReview(left, right);
      }),
    [connections, datasets, query],
  );
  const filteredDeliverableIds = React.useMemo(
    () => orderedDatasets.filter(isDatasetDeliveryReady).map((dataset) => dataset.id),
    [orderedDatasets],
  );
  const normalizedQuery = query.trim();
  const identityContextById = React.useMemo(
    () => buildDatasetIdentityContexts(orderedDatasets, connections),
    [connections, orderedDatasets],
  );
  const pageCount = Math.max(1, Math.ceil(orderedDatasets.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const visibleDatasets = orderedDatasets.slice(safePage * pageSize, safePage * pageSize + pageSize);

  React.useEffect(() => {
    setPage(0);
  }, [datasetListSignature, normalizedQuery]);

  return (
    <Card className="page-surface border-border/70 shadow-[var(--shadow-control)]">
      <CardHeader className="flex-row items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <CardTitle className="text-sm">选择数据集</CardTitle>
          <CardDescription>只选择已复核的数据集；待复核表先回到策略页确认。</CardDescription>
        </div>
        <Badge variant="outline" className="shrink-0 rounded-full text-[10px]">
          已选 {effectiveSelectedCount}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-2 px-4 pb-4 pt-0">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索数据集、表名、schema 或连接"
          className="h-9"
          data-testid="delivery-dataset-search"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-muted/25 px-3 py-2">
          <span className="text-sm text-muted-foreground">
            共 {datasets.length} 个数据集，可交付 {deliverableCount} 个，已选 {effectiveSelectedCount} 个
            {normalizedQuery ? `，筛选 ${orderedDatasets.length} 个，可交付 ${filteredDeliverableIds.length} 个` : ''}
            ，当前页 {visibleDatasets.length} 个
          </span>
          <span className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onSelectAll(normalizedQuery ? filteredDeliverableIds : undefined)}
              disabled={(normalizedQuery ? filteredDeliverableIds.length : deliverableCount) === 0}
            >
              {normalizedQuery ? '全选筛选结果' : '全选可交付'}
            </Button>
            <Button variant="outline" size="sm" onClick={onClear} disabled={selectedIds.size === 0}>
              清空
            </Button>
          </span>
        </div>
        <div className="grid gap-2">
          {datasets.length === 0 ? (
            <EmptyState icon={TableProperties} text="暂无可交付数据集" />
          ) : orderedDatasets.length === 0 ? (
            <EmptyState icon={TableProperties} text="没有匹配的数据集" />
          ) : (
            visibleDatasets.map((dataset) => {
              const reviewed = isDatasetDeliveryReady(dataset);
              const selected = reviewed && selectedIds.has(dataset.id);
              return (
                <div
                  key={dataset.id}
                  data-testid="delivery-dataset-row"
                  data-delivery-ready={reviewed ? 'true' : 'false'}
                  data-dataset-name={dataset.table_name ?? dataset.name}
                  data-dataset-context={datasetIdentityContextText(dataset, identityContextById.get(dataset.id))}
                  className={cn(
                    'grid min-h-16 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border px-3 py-2 transition',
                    selected && 'border-foreground bg-muted/45',
                    !reviewed && 'bg-muted/20 text-muted-foreground',
                  )}
                >
                  <Checkbox
                    aria-label={`选择 ${dataset.name}`}
                    checked={selected}
                    disabled={!reviewed}
                    onCheckedChange={() => onToggle(dataset.id)}
                  />
                  <DatasetIdentity dataset={dataset} identityContext={identityContextById.get(dataset.id)} />
                  <span className="flex shrink-0 items-center gap-2">
                    <Badge
                      variant={reviewed ? 'outline' : 'secondary'}
                      className={cn(
                        'shrink-0 text-[10px]',
                        reviewed
                          ? 'border-[var(--success-border)] text-[var(--success-foreground)]'
                          : 'border-[var(--warning-border)] bg-[var(--warning-surface)] text-[var(--warning-foreground)]',
                      )}
                    >
                      {reviewed ? '已复核' : '待复核'}
                    </Badge>
                    {!reviewed ? (
                      <Button asChild variant="outline" size="sm" className="h-7 bg-background px-2 text-[11px]">
                        <Link to={policyReviewUrlForDataset(dataset, { returnToDelivery: true })}>去复核</Link>
                      </Button>
                    ) : null}
                  </span>
                </div>
              );
            })
          )}
        </div>
        {orderedDatasets.length > pageSize ? (
          <ListPager
            label="数据集"
            page={safePage}
            pageCount={pageCount}
            total={orderedDatasets.length}
            pageSize={pageSize}
            visibleCount={visibleDatasets.length}
            onPageChange={setPage}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function ListPager({
  label,
  page,
  pageCount,
  total,
  pageSize,
  visibleCount,
  onPageChange,
}: {
  label: string;
  page: number;
  pageCount: number;
  total: number;
  pageSize: number;
  visibleCount: number;
  onPageChange: (page: number) => void;
}) {
  const start = total === 0 ? 0 : page * pageSize + 1;
  const end = total === 0 ? 0 : Math.min(total, page * pageSize + visibleCount);
  return (
    <div className="flex min-h-8 flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-muted/25 px-2.5 py-1.5 text-xs text-muted-foreground">
      <span className="min-w-0 truncate">
        {label} {start}-{end} / {total} · 第 {page + 1}/{pageCount} 页
      </span>
      {pageCount > 1 ? (
        <span className="ml-auto flex gap-1.5">
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={page <= 0}
            onClick={() => onPageChange(page - 1)}
          >
            上一组
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={page >= pageCount - 1}
            onClick={() => onPageChange(page + 1)}
          >
            下一组
          </Button>
        </span>
      ) : null}
    </div>
  );
}

function PreviewTable({
  title,
  columns,
  rows,
  muted,
  compareRows,
  changedColumns,
}: {
  title: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  muted?: boolean;
  compareRows?: Array<Record<string, unknown>>;
  changedColumns?: Set<string>;
}) {
  return (
    <div className="min-h-0 min-w-0 overflow-hidden rounded-xl border border-border">
      <div className={cn('border-b border-border px-3 py-2 text-sm font-medium', muted && 'bg-muted/40')}>
        {title}
      </div>
      <div className="overflow-hidden">
        <table className="w-full table-fixed text-xs">
          <thead className="sticky top-0 bg-muted text-muted-foreground">
            <tr>
              {columns.map((column) => (
                <th key={column} className="px-2 py-2 text-left">
                  <span className="block truncate" title={column}>
                    {column}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 5).map((row, index) => (
              <tr key={index} className="border-t border-border">
                {columns.map((column) => {
                  const value = displayValue(row[column]);
                  const changed =
                    Boolean(muted && compareRows && changedColumns?.has(column)) &&
                    displayValue(compareRows?.[index]?.[column]) !== value;
                  return (
                    <td
                      key={column}
                      className={cn('px-2 py-2', changed && 'bg-[var(--success-surface)]')}
                      data-preview-changed={changed ? 'true' : undefined}
                    >
                      <span className="block truncate" title={value}>
                        {value}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DiscoveryMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'strong';
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-background px-2.5 py-1.5 text-sm">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn('font-semibold', tone === 'strong' && 'text-[var(--success-foreground)]')}>{value}</span>
    </div>
  );
}

type DatasetIdentityContext = {
  connectionName?: string;
  duplicateCount: number;
  duplicateIndex: number;
};

function DatasetIdentity({
  dataset,
  compact,
  identityContext,
}: {
  dataset: StructuredDataset;
  compact?: boolean;
  identityContext?: DatasetIdentityContext;
}) {
  const isDbDataset = Boolean(dataset.connection_id);
  const primaryName = isDbDataset ? dataset.table_name || dataset.name : dataset.name;
  const rowText = dataset.row_count_estimate == null ? '行数待采样' : `${dataset.row_count_estimate} 行`;
  const metaItems = isDbDataset
    ? [
        identityContext?.connectionName,
        datasetSchemaLabel(dataset),
        datasetTypeLabel(dataset),
        `${dataset.column_count} 列`,
        rowText,
      ]
    : [
        identityContext && identityContext.duplicateCount > 1
          ? `同名 ${identityContext.duplicateIndex}/${identityContext.duplicateCount}`
          : '',
        identityContext && identityContext.duplicateCount > 1 && dataset.source_id
          ? `来源 ${shortEntityId(dataset.source_id)}`
          : '',
        datasetTypeLabel(dataset),
        `${dataset.column_count} 列`,
        rowText,
      ];
  return (
    <span className="min-w-0">
      <span className={cn('block truncate font-medium', compact ? 'text-xs' : 'text-sm')} title={dataset.name}>
        {primaryName}
      </span>
      <span className="mt-1 flex flex-wrap items-center gap-1 text-[10.5px] text-muted-foreground">
        <Badge variant="outline" className="text-[10px]" title={dataset.source_kind}>
          {dataset.source_kind.toUpperCase()}
        </Badge>
        {metaItems.filter((item): item is string => Boolean(item)).map((item, index) => (
          <span key={`${index}:${item}`} className="truncate">
            {item}
          </span>
        ))}
      </span>
    </span>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function EmptyState({ icon: Icon, text }: { icon: React.FC<{ className?: string }>; text: string }) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-2 px-4 py-8 text-center text-muted-foreground">
      <Icon className="size-5" />
      <span className="text-sm">{text}</span>
    </div>
  );
}

function RiskBadge({ risk }: { risk: StructuredColumnProfile['risk_level'] }) {
  const meta = {
    low: { label: '低', tone: 'border-border text-muted-foreground' },
    medium: { label: '中', tone: 'border-[var(--warning-foreground)] text-[var(--warning-foreground)]' },
    high: { label: '高', tone: 'border-[var(--error-foreground)] text-[var(--error-foreground)]' },
    critical: {
      label: '极高',
      tone: 'border-[var(--error-foreground)] bg-[var(--error-surface)] text-[var(--error-foreground)]',
    },
  }[risk];
  return (
    <Badge variant="outline" className={cn('text-[10px]', meta.tone)} title={risk}>
      {meta.label}
    </Badge>
  );
}

function SemanticInferenceSummary({
  info,
}: {
  info: NonNullable<StructuredProfile['semantic_inference']>;
}) {
  const status = info.status ?? 'unknown';
  const matched = typeof info.matched_columns === 'number' ? info.matched_columns : 0;
  const duration = typeof info.duration_ms === 'number' ? info.duration_ms : 0;
  const meta = semanticInferenceStatusMeta(status, matched);
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
      <Badge variant={meta.variant} className="text-[10px]">
        {meta.label}
      </Badge>
      <span>{meta.detail}</span>
      {meta.showMatched ? <span>命中 {matched} 字段</span> : null}
      {duration > 0 ? <span>{duration} ms</span> : null}
    </div>
  );
}

function semanticInferenceStatusMeta(
  status: string,
  matched: number,
): {
  label: string;
  detail: string;
  showMatched: boolean;
  variant: React.ComponentProps<typeof Badge>['variant'];
} {
  if (status === 'used') {
    return {
      label: '语义增强已启用',
      detail: 'HaS 补充了模糊字段判断',
      showMatched: true,
      variant: 'default',
    };
  }
  if (status === 'used_no_matches') {
    return {
      label: '语义增强未新增',
      detail: matched > 0 ? '已合并语义命中' : '字段策略以本地规则为准',
      showMatched: true,
      variant: 'outline',
    };
  }
  if (status === 'skipped_no_candidates') {
    return {
      label: '本地规则已覆盖',
      detail: '没有需要模型兜底的模糊字段',
      showMatched: false,
      variant: 'outline',
    };
  }
  if (status === 'skipped_empty') {
    return {
      label: '无样本可分析',
      detail: '请确认数据集有可读取样本',
      showMatched: false,
      variant: 'outline',
    };
  }
  if (status === 'unavailable') {
    return {
      label: '语义服务未启用',
      detail: '已使用列名和样本规则生成策略',
      showMatched: false,
      variant: 'outline',
    };
  }
  if (status === 'failed') {
    return {
      label: '语义增强失败',
      detail: '已回退到本地字段策略',
      showMatched: false,
      variant: 'outline',
    };
  }
  return {
    label: '语义状态未知',
    detail: '已使用当前字段策略',
    showMatched: false,
    variant: 'outline',
  };
}

function toggleSet(set: Set<string>, key: string): Set<string> {
  const next = new Set(set);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function sameSetValues(set: Set<string>, values: string[]): boolean {
  if (set.size !== values.length) return false;
  return values.every((value) => set.has(value));
}

function datasetKey(dataset: StructuredDataset): string {
  return `${dataset.schema_name ?? ''}.${dataset.table_name ?? dataset.name}`;
}

function datasetSchemaLabel(dataset: StructuredDataset): string {
  return dataset.schema_name || (dataset.source_kind === 'sqlite' ? 'main' : 'default');
}

function datasetReviewScope(dataset: StructuredDataset): string {
  if (dataset.connection_id) return `connection:${dataset.connection_id}`;
  if (dataset.source_id) return `source:${dataset.source_id}`;
  return `dataset:${dataset.id}`;
}

function isSameDatasetReviewScope(left: StructuredDataset, right: StructuredDataset): boolean {
  return datasetReviewScope(left) === datasetReviewScope(right);
}

function compareStructuredDatasetsForReview(left: StructuredDataset, right: StructuredDataset): number {
  const leftSchema = datasetSchemaLabel(left);
  const rightSchema = datasetSchemaLabel(right);
  if (leftSchema !== rightSchema) return leftSchema.localeCompare(rightSchema);
  return (left.table_name ?? left.name).localeCompare(right.table_name ?? right.name);
}

function buildDatasetScopeSummary(
  selectedDataset: StructuredDataset | null,
  datasets: StructuredDataset[],
  connections: StructuredConnection[],
): { eyebrow: string; title: string; badge: string; detail: string } | null {
  if (!selectedDataset) return null;
  const scopeDatasets = datasets.filter((dataset) => isSameDatasetReviewScope(dataset, selectedDataset));
  if (scopeDatasets.length <= 1 && !selectedDataset.connection_id) return null;

  if (selectedDataset.connection_id) {
    const connection = connections.find((item) => item.id === selectedDataset.connection_id) ?? null;
    const schemaCount = new Set(scopeDatasets.map(datasetSchemaLabel)).size;
    const tableCount = scopeDatasets.filter((dataset) => dataset.dataset_type !== 'db_view').length;
    const viewCount = scopeDatasets.filter((dataset) => dataset.dataset_type === 'db_view').length;
    const title = connection?.display_name || `${selectedDataset.source_kind.toUpperCase()} 数据库连接`;
    return {
      eyebrow: '当前连接',
      title,
      badge: `${scopeDatasets.length} 对象`,
      detail: `${schemaCount} schema · ${tableCount} 表 · ${viewCount} 视图`,
    };
  }

  if (selectedDataset.source_id && scopeDatasets.length > 1) {
    return {
      eyebrow: '当前批次',
      title: selectedDataset.name,
      badge: `${scopeDatasets.length} 表`,
      detail: `同一文件来源 · ${scopeDatasets.reduce((sum, dataset) => sum + dataset.column_count, 0)} 个字段`,
    };
  }

  return null;
}

function orderColumnsForPolicyReview(columns: StructuredColumnProfile[]): StructuredColumnProfile[] {
  const riskWeight: Record<StructuredColumnProfile['risk_level'], number> = {
    critical: 4,
    high: 3,
    medium: 2,
    low: 1,
  };
  return columns
    .map((column, index) => ({ column, index }))
    .sort((left, right) => {
      const leftRisk = riskWeight[left.column.risk_level] ?? 0;
      const rightRisk = riskWeight[right.column.risk_level] ?? 0;
      if (leftRisk !== rightRisk) return rightRisk - leftRisk;

      const leftRedacts = left.column.recommended_policy !== 'keep';
      const rightRedacts = right.column.recommended_policy !== 'keep';
      if (leftRedacts !== rightRedacts) return leftRedacts ? -1 : 1;

      const leftSemantic = (left.column.reasons ?? []).some((reason) => String(reason).includes('semantic'));
      const rightSemantic = (right.column.reasons ?? []).some((reason) => String(reason).includes('semantic'));
      if (leftSemantic !== rightSemantic) return leftSemantic ? -1 : 1;

      if (left.column.confidence !== right.column.confidence) {
        return right.column.confidence - left.column.confidence;
      }
      return left.index - right.index;
    })
    .map(({ column }) => column);
}

function matchesPolicyColumnQuery(column: StructuredColumnProfile, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return [
    column.name,
    column.entity_type,
    column.risk_level,
    column.data_type,
    column.recommended_policy,
    ...(column.reasons ?? []),
    ...column.sample_values.map(displayValue),
  ].some((value) => String(value).toLowerCase().includes(normalizedQuery));
}

function connectionTargetLabel(connection: StructuredConnection): string {
  const metadata = connection.metadata ?? {};
  const target = metadata.target;
  if (typeof target === 'string' && target.trim()) return target;
  if (connection.engine === 'sqlite') {
    const sqlitePath = metadata.sqlite_path;
    return typeof sqlitePath === 'string' && sqlitePath.trim() ? sqlitePath : 'SQLite 数据库';
  }
  const host = typeof metadata.host === 'string' ? metadata.host : '';
  const port = typeof metadata.port === 'number' || typeof metadata.port === 'string' ? String(metadata.port) : '';
  const database = typeof metadata.database === 'string' ? metadata.database : '';
  const endpoint = [host, port ? `:${port}` : '', database ? `/${database}` : ''].join('');
  return endpoint || connection.engine.toUpperCase();
}

function deliveryUrlForDataset(dataset: StructuredDataset | null): string {
  if (!dataset) return '/structured/delivery';
  const params = new URLSearchParams({ datasetId: dataset.id });
  if (dataset.connection_id) {
    params.set('scope', 'connection');
    params.set('connectionId', dataset.connection_id);
  } else if (dataset.source_id) {
    params.set('scope', 'source');
    params.set('sourceId', dataset.source_id);
  }
  return `/structured/delivery?${params.toString()}`;
}

function policyReviewUrlForDataset(
  dataset: StructuredDataset,
  options: { returnToDelivery?: boolean } = {},
): string {
  const params = new URLSearchParams({ datasetId: dataset.id });
  if (options.returnToDelivery) params.set('returnTo', 'delivery');
  return `/structured/datasets?${params.toString()}`;
}

function preservePolicyReturnParams(searchParams: URLSearchParams, datasetId: string): Record<string, string> {
  const params: Record<string, string> = { datasetId };
  if (searchParams.get('returnTo') === 'delivery') params.returnTo = 'delivery';
  return params;
}

function isDatasetDeliveryReady(dataset: StructuredDataset): boolean {
  return Boolean(dataset.policy_reviewed_at);
}

function datasetTypeLabel(dataset: StructuredDataset): string {
  if (dataset.dataset_type === 'db_view') return '视图';
  if (dataset.dataset_type === 'db_table') return '表';
  if (dataset.dataset_type === 'sheet') return 'Sheet';
  return '文件表';
}

function shapeKindLabel(shape: StructuredDataset['shape_kind']): string {
  const labels: Record<StructuredDataset['shape_kind'], string> = {
    flat_table: '平面表',
    relational_multi_table: '关系表',
    event_log: '事件表',
    wide_feature_table: '宽表',
    json_kv_table: 'JSON/KV',
  };
  return labels[shape] ?? shape;
}

function profileToPolicy(column: StructuredColumnProfile): StructuredColumnPolicy {
  return {
    column: column.name,
    action: column.recommended_policy,
    entity_type: column.entity_type,
    enabled: column.recommended_policy !== 'keep',
    params: {},
  };
}

function isPolicyAdjusted(column: StructuredColumnProfile, current: StructuredColumnPolicy): boolean {
  const recommended = profileToPolicy(column);
  return current.action !== recommended.action || Boolean(current.enabled) !== Boolean(recommended.enabled);
}

function defaultEnabledPolicyAction(
  column: StructuredColumnProfile,
  current?: StructuredColumnPolicy,
): StructuredPolicyAction {
  if (current?.action && current.action !== 'keep') return current.action;
  if (column.recommended_policy && column.recommended_policy !== 'keep') return column.recommended_policy;
  return 'mask';
}

function updatePolicy(
  policy: StructuredColumnPolicy[],
  column: StructuredColumnProfile,
  patch: Partial<StructuredColumnPolicy>,
): StructuredColumnPolicy[] {
  const current = policy.find((item) => item.column === column.name) ?? profileToPolicy(column);
  const nextItem = { ...current, ...patch };
  const exists = policy.some((item) => item.column === column.name);
  if (!exists) return [...policy, nextItem];
  return policy.map((item) => (item.column === column.name ? nextItem : item));
}

function displayValue(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function isFileDataset(dataset: StructuredDataset): boolean {
  return Boolean(dataset.source_id) || !dataset.connection_id;
}
