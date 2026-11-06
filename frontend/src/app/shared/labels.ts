import { ConfidenceLabel, EvidenceStatus, JobState } from '../core/api.models';

export const EVIDENCE_LABEL: Record<EvidenceStatus, string> = {
  verified: 'Verified quote',
  fuzzy: 'Near-exact quote',
  unverified: 'Unverified',
  not_found: 'No evidence',
};

export const EVIDENCE_HELP: Record<EvidenceStatus, string> = {
  verified: 'This exact text appears in the resume.',
  fuzzy: 'Text very close to this appears in the resume (minor differences).',
  unverified: 'This quote could NOT be found in the resume. The model may have paraphrased or invented it; treat the score with caution.',
  not_found: 'The model found nothing in the resume supporting this criterion.',
};

export const CONFIDENCE_HELP: Record<ConfidenceLabel, string> = {
  high: 'Evidence for the scores was found in the resume.',
  medium: 'Some evidence could not be verified, or the document was OCR\'d or truncated.',
  low: 'Several quotes could not be verified. Review this candidate manually.',
};

export const JOB_STATE_LABEL: Record<JobState, string> = {
  queued: 'Queued',
  generating_rubric: 'Generating rubric',
  running: 'Scoring',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export function formatBytes(n: number | null | undefined): string {
  if (!n) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  const m = Math.round(seconds / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** Rough CPU-inference guess before any resume has been scored (seconds per resume). */
export const DEFAULT_SECONDS_PER_RESUME = 90;
