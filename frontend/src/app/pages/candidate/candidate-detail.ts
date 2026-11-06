import { DecimalPipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { CandidateResult, Decision, JobDetail } from '../../core/api.models';
import { ApiService, apiErrorMessage } from '../../core/api.service';
import { pollJob } from '../../core/job-polling';
import { WorkflowStore } from '../../core/workflow.store';
import { EvidenceChip } from '../../shared/evidence-chip';
import { CONFIDENCE_HELP } from '../../shared/labels';

@Component({
  selector: 'app-candidate-detail',
  imports: [
    DecimalPipe, RouterLink, MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatSnackBarModule,
    MatTooltipModule, EvidenceChip,
  ],
  templateUrl: './candidate-detail.html',
  styleUrl: './candidate-detail.scss',
})
export class CandidateDetailPage {
  readonly jobId = input.required<string>();
  readonly candidateId = input.required<string>();

  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly store = inject(WorkflowStore);
  protected readonly CONFIDENCE_HELP = CONFIDENCE_HELP;

  protected readonly job = signal<JobDetail | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly notesDraft = signal('');
  protected readonly savingNotes = signal(false);
  protected readonly notesSaved = signal(false);

  protected readonly candidate = computed(() => this.job()?.candidates.find((c) => c.id === this.candidateId()) ?? null);
  protected readonly scored = computed(() => (this.job()?.candidates ?? []).filter((c) => c.status === 'done'));
  protected readonly position = computed(() => this.scored().findIndex((c) => c.id === this.candidateId()));
  protected readonly prev = computed(() => this.scored()[this.position() - 1] ?? null);
  protected readonly next = computed(() => this.scored()[this.position() + 1] ?? null);
  protected readonly notesDirty = computed(() => this.notesDraft() !== (this.candidate()?.notes ?? ''));

  private poll?: Subscription;
  private loadedNotesFor: string | null = null;

  constructor() {
    effect(() => this.load(this.jobId()));
    // Load the saved notes once per candidate, without clobbering what the user is typing on later polls.
    effect(() => {
      const c = this.candidate();
      if (c && this.loadedNotesFor !== c.id) {
        this.loadedNotesFor = c.id;
        this.notesDraft.set(c.notes);
        this.notesSaved.set(false);
      }
    });
  }

  protected load(jobId: string): void {
    this.poll?.unsubscribe();
    this.poll = pollJob(this.api, jobId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (j) => this.job.set(j), error: (err) => this.loadError.set(apiErrorMessage(err)) });
  }

  protected setDecision(c: CandidateResult, decision: Decision): void {
    const next: Decision = c.decision === decision ? 'pending' : decision;
    this.review(c, { decision: next });
  }

  protected saveNotes(c: CandidateResult): void {
    this.savingNotes.set(true);
    this.review(c, { notes: this.notesDraft() }, () => {
      this.savingNotes.set(false);
      this.notesSaved.set(true);
    });
  }

  private review(c: CandidateResult, patch: Partial<Pick<CandidateResult, 'decision' | 'notes'>>, done?: () => void): void {
    this.api.reviewCandidate(this.jobId(), c.id, patch).subscribe({
      next: (updated) => {
        this.job.update((j) => j && { ...j, candidates: j.candidates.map((x) => (x.id === updated.id ? { ...x, ...patch } : x)) });
        done?.();
      },
      error: (err) => {
        this.savingNotes.set(false);
        this.snack.open(apiErrorMessage(err), 'Dismiss', { duration: 5000 });
      },
    });
  }
}
