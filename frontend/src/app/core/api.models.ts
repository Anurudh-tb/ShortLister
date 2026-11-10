// Typed mirrors of backend/models/schemas.py. Keep in sync with the Pydantic models.

export interface Criterion {
  name: string;
  description: string;
  weight: number;
  must_have: boolean;
}

export interface Rubric {
  job_title: string | null;
  criteria: Criterion[];
}

export interface RubricResponse {
  rubric: Rubric;
  jd_text: string;
  model: string;
  warnings: string[];
}

export interface ModelInfo {
  name: string;
  size_bytes: number | null;
  parameter_size: string | null;
  family: string | null;
}

export interface PublicConfig {
  provider: string;
  default_model: string;
  num_ctx: number;
  max_file_mb: number;
  max_resumes_per_job: number;
  must_have_min_score: number;
  persist_resume_text: boolean;
  ocr_enabled: boolean;
  /** Used when resumes are scored without a JD; null if the backend's default files are missing or invalid. */
}

export interface ModelsResponse {
  provider: string;
  default_model: string;
  models: ModelInfo[];
}

export type EvidenceStatus = 'verified' | 'fuzzy' | 'unverified' | 'not_found';
export type ConfidenceLabel = 'high' | 'medium' | 'low';
export type CandidateStatus = 'pending' | 'scoring' | 'done' | 'error';
export type JobState = 'queued' | 'generating_rubric' | 'running' | 'completed' | 'failed' | 'cancelled';
export type Decision = 'pending' | 'shortlisted' | 'rejected';

export const ACTIVE_JOB_STATES: readonly JobState[] = ['queued', 'generating_rubric', 'running'];

export interface CriterionResult {
  criterion: string;
  weight: number;
  must_have: boolean;
  score: number;
  evidence: string;
  reasoning: string;
  evidence_status: EvidenceStatus;
  evidence_match: number;
  confidence: number;
}

export interface CandidateResult {
  id: string;
  filename: string;
  status: CandidateStatus;
  error: string | null;
  candidate_name: string | null;
  best_fit_role: string | null;
  rank: number | null;
  total_score: number | null;
  must_have_ok: boolean | null;
  must_have_missing: string[];
  confidence: number | null;
  confidence_label: ConfidenceLabel | null;
  criteria: CriterionResult[];
  strengths: string[];
  gaps: string[];
  summary: string;
  warnings: string[];
  decision: Decision;
  notes: string;
  /** Reused from the server's score cache instead of calling the model again. */
  cached: boolean;
}

export interface JobProgress {
  total: number;
  done: number;
  failed: number;
  percent: number;
}

export interface JobSummary {
  job_id: string;
  status: JobState;
  created_at: string;
  model: string;
  job_title: string | null;
  progress: JobProgress;
  error: string | null;
}

export interface JobDetail extends JobSummary {
  rubric: Rubric | null;
  candidates: CandidateResult[];
}

export interface ScoreJobCreated {
  job_id: string;
  status: JobState;
  candidates: CandidateResult[];
}

export interface CandidateReview {
  decision?: Decision;
  notes?: string;
}

/** Error body shape produced by the backend: {"detail": {"code", "detail"}}. */
export interface ApiErrorBody {
  detail: { code: string; detail: string } | string | { msg: string }[];
}

export interface LoginResponse {
  username: string;
  access_token: string;
  token_type: 'bearer';
  /** Token lifetime in seconds. */
  expires_in: number;
}

export interface SignupResponse {
  id: number;
  username: string;
  created_at: string;
}
