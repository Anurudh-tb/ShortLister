import { HttpClient, HttpErrorResponse, HttpEvent } from '@angular/common/http';
import { Injectable, InjectionToken, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  ApiErrorBody,
  CandidateResult,
  CandidateReview,
  JobDetail,
  JobSummary,
  LoginResponse,
  ModelsResponse,
  PublicConfig,
  Rubric,
  RubricResponse,
  ScoreJobCreated,
  SignupResponse,
} from './api.models';

/** Base URL of the backend API. Defaults to same-origin `/api` (dev proxy / nginx in Docker). */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', { factory: () => '/api' });

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** Register a new user. */
  signup(username: string, password: string): Observable<SignupResponse> {
    return this.http.post<SignupResponse>(`${this.base}/auth/signup`, { username, password });
  }

  /** Check the credentials; returns a JWT for later requests. */
  login(username: string, password: string): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(`${this.base}/auth/login`, { username, password });
  }

  getConfig(): Observable<PublicConfig> {
    return this.http.get<PublicConfig>(`${this.base}/config`);
  }

  listModels(): Observable<ModelsResponse> {
    return this.http.get<ModelsResponse>(`${this.base}/models`);
  }

  generateRubric(input: { jdText?: string; jdFile?: File; model?: string }): Observable<RubricResponse> {
    const form = new FormData();
    if (input.jdText) form.append('jd_text', input.jdText);
    if (input.jdFile) form.append('jd_file', input.jdFile, input.jdFile.name);
    if (input.model) form.append('model', input.model);
    return this.http.post<RubricResponse>(`${this.base}/rubric`, form);
  }

  /**
   * Starts a scoring job; emits upload progress events and finally the response.
   * Pass an edited rubric, or a JD (file and/or text) and the backend generates the rubric itself.
   */
  startScoring(
    resumes: File[],
    input: { rubric?: Rubric; jdText?: string; jdFile?: File; model?: string },
  ): Observable<HttpEvent<ScoreJobCreated>> {
    const form = new FormData();
    if (input.rubric) form.append('rubric', JSON.stringify(input.rubric));
    if (input.jdText) form.append('jd_text', input.jdText);
    if (input.jdFile) form.append('jd_file', input.jdFile, input.jdFile.name);
    if (input.model) form.append('model', input.model);
    for (const f of resumes) form.append('resumes', f, f.name);
    return this.http.post<ScoreJobCreated>(`${this.base}/score`, form, { reportProgress: true, observe: 'events' });
  }

  listJobs(): Observable<JobSummary[]> {
    return this.http.get<JobSummary[]>(`${this.base}/jobs`);
  }

  getJob(jobId: string): Observable<JobDetail> {
    return this.http.get<JobDetail>(`${this.base}/jobs/${encodeURIComponent(jobId)}`);
  }

  deleteJob(jobId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/jobs/${encodeURIComponent(jobId)}`);
  }

  reviewCandidate(jobId: string, candidateId: string, review: CandidateReview): Observable<CandidateResult> {
    return this.http.patch<CandidateResult>(
      `${this.base}/jobs/${encodeURIComponent(jobId)}/candidates/${encodeURIComponent(candidateId)}`,
      review,
    );
  }

  exportUrl(jobId: string, format: 'csv' | 'xlsx'): string {
    return `${this.base}/jobs/${encodeURIComponent(jobId)}/export?format=${format}`;
  }
}

/** Turn any HTTP failure into a single human-readable sentence. */
export function apiErrorMessage(err: unknown): string {
  if (!(err instanceof HttpErrorResponse)) return 'Something went wrong. Please try again.';
  if (err.status === 0) return 'Cannot reach the backend. Is it running on port 8000?';
  const body = err.error as ApiErrorBody | null;
  const detail = body?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && 'detail' in detail) return detail.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail.map((d) => d.msg).join('; ');
  return `Request failed (HTTP ${err.status}).`;
}
