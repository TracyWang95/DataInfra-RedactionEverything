/**
 * Batch wizard — multi-file redaction workflow.
 *
 * Migration complete:
 * - batch-hub.tsx (fully rebuilt with ShadCN)
 * - batch-wizard.tsx (page orchestrator with step routing)
 * - hooks/use-batch-wizard.ts (all wizard state and actions)
 * - components/ — step progress + 5 step components
 */

export { BatchHub } from './batch-hub';
export { BatchWizard as Batch } from './batch-wizard';
