import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { ACTIVE_JOB_STATES, CandidateResult, Decision, JobDetail } from '../../core/api.models';
import { ApiService, apiErrorMessage } from '../../core/api.service';
import { pollJob } from '../../core/job-polling';
import { WorkflowStore } from '../../core/workflow.store';
import { CONFIDENCE_HELP, DEFAULT_SECONDS_PER_RESUME, JOB_STATE_LABEL, formatDuration } from '../../shared/labels';

type DecisionFilter = 'all' | Decision;
const MAX_COMPARE = 3;

@Component({
  selector: 'app-results',
  imports: [
    DatePipe, DecimalPipe, RouterLink, MatButtonModule, MatButtonToggleModule, MatCheckboxModule, MatIconModule,
    MatProgressBarModule, MatProgressSpinnerModule, MatSlideToggleModule, MatSnackBarModule, MatSortModule,
    MatTableModule, MatTooltipModule,
  ],
  templateUrl: './results.html',
  styleUrl: './results.scss',
})
export class ResultsPage {
  readonly jobId = input.required<string>();

  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly store = inject(WorkflowStore);
  protected readonly JOB_STATE_LABEL = JOB_STATE_LABEL;
  protected readonly MAX_COMPARE = MAX_COMPARE;

  protected readonly job = signal<JobDetail | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly lastUpdate = signal(Date.now());

  // Filters / sorting / selection
  protected readonly mustHaveOnly = signal(false);
  protected readonly decisionFilter = signal<DecisionFilter>('all');
  protected readonly minScore = signal(0);
  protected readonly sort = signal<Sort>({ active: 'rank', direction: 'asc' });
  protected readonly selected = signal<ReadonlySet<string>>(new Set());
  protected readonly confirmDelete = signal(false);

  // 'role' (best-fit role / designation) column hidden for now; add it back after 'candidate' to show it.
  protected readonly columns = ['select', 'rank', 'candidate', /* 'role', */ 'score', 'musthave', 'confidence', 'decision'];

  protected readonly active = computed(() => {
    const j = this.job();
    return !!j && ACTIVE_JOB_STATES.includes(j.status);
  });

  protected readonly rows = computed(() => {
    const j = this.job();
    if (!j) return [];
    const minScore = this.minScore();
    const filtered = j.candidates.filter(
      (c) =>
        (!this.mustHaveOnly() || c.must_have_ok === true) &&
        (this.decisionFilter() === 'all' || c.decision === this.decisionFilter()) &&
        (minScore === 0 || (c.total_score ?? -1) >= minScore),
    );
    return this.sortRows(filtered, this.sort());
  });

  protected readonly hiddenCount = computed(() => (this.job()?.candidates.length ?? 0) - this.rows().length);

  protected readonly counts = computed(() => {
    const cs = this.job()?.candidates ?? [];
    return {
      shortlisted: cs.filter((c) => c.decision === 'shortlisted').length,
      rejected: cs.filter((c) => c.decision === 'rejected').length,
      mustHaveOk: cs.filter((c) => c.must_have_ok).length,
    };
  });

  /** Remaining time, learned from this job's own pace once the first resume is done. */
  protected readonly eta = computed(() => {
    const j = this.job();
    if (!j || !this.active()) return null;
    const remaining = j.progress.total - j.progress.done - j.progress.failed;
    if (remaining <= 0) return null;
    const elapsed = (this.lastUpdate() - Date.parse(j.created_at)) / 1000;
    const perResume = j.progress.done > 0 ? elapsed / j.progress.done : DEFAULT_SECONDS_PER_RESUME;
    return formatDuration(perResume * remaining);
  });

  private poll?: Subscription;

  constructor() {
    effect(() => this.startPolling(this.jobId()));
  }

  protected startPolling(jobId: string): void {
    this.poll?.unsubscribe();
    this.loadError.set(null);
    this.poll = pollJob(this.api, jobId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (j) => {
          this.job.set(j);
          this.lastUpdate.set(Date.now());
        },
        error: (err) => this.loadError.set(apiErrorMessage(err)),
      });
  }

  protected confidenceHelp(c: CandidateResult): string {
    return c.confidence_label ? CONFIDENCE_HELP[c.confidence_label] : '';
  }

  protected open(c: CandidateResult): void {
    this.router.navigate(['/jobs', this.jobId(), 'candidates', c.id]);
  }

  protected toggleSelect(c: CandidateResult): void {
    this.selected.update((s) => {
      const next = new Set(s);
      if (next.has(c.id)) next.delete(c.id);
      else if (next.size < MAX_COMPARE) next.add(c.id);
      return next;
    });
  }

  protected compare(): void {
    this.router.navigate(['/jobs', this.jobId(), 'compare'], { queryParams: { ids: [...this.selected()].join(',') } });
  }

  protected setDecision(c: CandidateResult, decision: Decision): void {
    const next: Decision = c.decision === decision ? 'pending' : decision; // clicking again undoes
    this.patchLocal(c.id, { decision: next });
    this.api.reviewCandidate(this.jobId(), c.id, { decision: next }).subscribe({
      error: (err) => {
        this.patchLocal(c.id, { decision: c.decision });
        this.snack.open(apiErrorMessage(err), 'Dismiss', { duration: 5000 });
      },
    });
  }

  protected deleteJob(): void {
    if (!this.confirmDelete()) {
      this.confirmDelete.set(true);
      setTimeout(() => this.confirmDelete.set(false), 5000);
      return;
    }
    this.poll?.unsubscribe();
    this.api.deleteJob(this.jobId()).subscribe({
      next: () => {
        this.snack.open('Job and all candidate data deleted.', undefined, { duration: 4000 });
        this.router.navigateByUrl('/jobs');
      },
      error: (err) => this.snack.open(apiErrorMessage(err), 'Dismiss', { duration: 5000 }),
    });
  }

  protected clearFilters(): void {
    this.mustHaveOnly.set(false);
    this.decisionFilter.set('all');
    this.minScore.set(0);
  }

  private patchLocal(id: string, patch: Partial<CandidateResult>): void {
    this.job.update((j) => j && { ...j, candidates: j.candidates.map((c) => (c.id === id ? { ...c, ...patch } : c)) });
  }

  private sortRows(rows: CandidateResult[], sort: Sort): CandidateResult[] {
    if (!sort.direction) return rows;
    const dir = sort.direction === 'asc' ? 1 : -1;
    const value = (c: CandidateResult): number | string => {
      switch (sort.active) {
        case 'score':
          return c.total_score ?? -1;
        case 'confidence':
          return c.confidence ?? -1;
        case 'candidate':
          return this.store.displayName(c).toLowerCase();
        case 'role':
          return (c.best_fit_role ?? '').toLowerCase();
        default:
          return c.rank ?? Number.MAX_SAFE_INTEGER;
      }
    };
    return [...rows].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
    });
  }
}
