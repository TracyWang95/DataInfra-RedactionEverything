export const en: Record<string, string> = {
  // Navigation
  'nav.playground': 'Playground',
  'nav.batch': 'Batch',
  'nav.batch.sub': 'Create or resume wizard',
  'nav.history': 'History',
  'nav.jobs': 'Jobs',
  'nav.jobs.sub': 'Text / image batch queue',
  'nav.redactionList': 'Redaction List',
  'nav.redactionList.sub': 'Named presets & selection',
  'nav.recognitionSettings': 'Recognition',
  'nav.recognitionSettings.sub': 'Text / image recognition rules',
  'nav.modelConfig': 'Model Config',
  'nav.textModel': 'Text Model',
  'nav.visionModel': 'Vision Service',

  // Playground
  'playground.title': 'Redaction Workspace',
  'playground.upload.hint': 'Drag & drop or click to upload',
  'playground.upload.formats': 'Supports Word, PDF, and image files',
  'playground.recognize': 'Recognize',
  'playground.recognizing': 'Recognizing...',
  'playground.redact': 'Redact',
  'playground.redacting': 'Redacting...',
  'playground.reupload': 'Re-upload',
  'playground.undo': 'Undo',
  'playground.redo': 'Redo',
  'playground.selectAll': 'Select All',
  'playground.deselectAll': 'Deselect All',
  'playground.entities': 'Entities',
  'playground.boundingBoxes': 'Regions',

  // Common
  'common.confirm': 'Confirm',
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.save': 'Save',
  'common.export': 'Export',
  'common.import': 'Import',
  'common.loading': 'Loading...',
  'common.noData': 'No data',
  'common.success': 'Success',
  'common.error': 'Error',
  'common.retry': 'Retry',

  // File types
  'file.word': 'Word Document',
  'file.pdf': 'PDF Document',
  'file.image': 'Image',

  // Entity types
  'entity.PERSON': 'Name',
  'entity.ID_CARD': 'ID Card',
  'entity.PHONE': 'Phone',
  'entity.ADDRESS': 'Address',
  'entity.ORG': 'Organization',
  'entity.BANK_CARD': 'Bank Card',
  'entity.CASE_NUMBER': 'Case Number',
  'entity.DATE': 'Date',
  'entity.AMOUNT': 'Amount',

  // Replacement modes
  'mode.smart': 'Smart Replace',
  'mode.mask': 'Mask',
  'mode.custom': 'Custom',
  'mode.structured': 'Structured Tags',

  // Jobs
  'job.status.draft': 'Draft',
  'job.status.queued': 'Queued',
  'job.status.running': 'Running',
  'job.status.awaiting_review': 'Awaiting Review',
  'job.status.redacting': 'Redacting',
  'job.status.completed': 'Completed',
  'job.status.failed': 'Failed',
  'job.status.cancelled': 'Cancelled',

  // Settings
  'settings.title': 'Settings',
  'settings.presets': 'Presets',
  'settings.presets.export': 'Export Presets',
  'settings.presets.import': 'Import Presets',

  // Report
  'report.title': 'Redaction Report',
  'report.totalEntities': 'Total Entities',
  'report.redactedEntities': 'Redacted',
  'report.coverage': 'Coverage',
  'report.typeDistribution': 'Type Distribution',
  'report.confidenceDistribution': 'Confidence',
  'report.high': 'High',
  'report.medium': 'Medium',
  'report.low': 'Low',

  // Health
  'health.title': 'Service Status',
  'health.allOnline': 'All services online',
  'health.someOffline': 'Some services offline',
  'health.backendDown': 'Backend disconnected',
  'health.checking': 'Checking services...',
  'health.detecting': 'Checking...',
  'health.online': 'Online',
  'health.offline': 'Offline',
  'health.backendProbe': 'Backend probe',
  'health.frontendRoundTrip': 'Frontend round-trip',
  'health.gpuMemory': 'GPU Memory',
  'health.gpuNotDetected': 'Not detected',
  'health.probeTime': 'Probe time',
  'health.refreshTitle': 'Refresh service status',

  // Offline
  'offline.banner': 'Network disconnected. Some features may be unavailable.',

  // Onboarding
  'onboarding.skip': 'Skip',
  'onboarding.prev': 'Previous',
  'onboarding.next': 'Next',
  'onboarding.start': 'Get Started',

  // Page headers
  'page.batch.title': 'Batch',
  'page.batch.sub': 'Choose type & create a job',
  'page.batchText.title': 'Batch Processing',
  'page.batchText.sub': 'Plain text / selectable-text PDFs',
  'page.batchImage.title': 'Batch Processing',
  'page.batchImage.sub': 'Image-based text',
  'page.batchSmart.title': 'Smart Batch',
  'page.batchSmart.sub': 'Mixed files with auto-detection',
  'page.redactionList.title': 'Redaction List',
  'page.redactionList.sub': 'Named presets & selection, synced with Playground / batch wizard',
  'page.recognitionSettings.title': 'Recognition Settings',
  'page.recognitionSettings.sub': 'PII types, regex & semantic rules',
  'page.jobDetail.title': 'Job Details',
  'page.jobDetail.sub': 'Queue progress, edit, confirm per file',
  'page.jobs.title': 'Jobs',
  'page.jobs.sub': 'Text batch / image batch, queue & review',
  'page.history.title': 'History',
  'page.history.sub': 'Uploaded files, pagination, bulk ZIP',
  'page.textModel.title': 'Text Model',
  'page.textModel.sub': 'Text NER, HaS (llama-server)',
  'page.visionModel.title': 'Vision Service',
  'page.visionModel.sub': 'HaS Image, PaddleOCR-VL registration & detection',

  // Sidebar
  'sidebar.subtitle': 'Anonymization Data Infrastructure',
  'sidebar.devInProgress': 'In Dev',
};
