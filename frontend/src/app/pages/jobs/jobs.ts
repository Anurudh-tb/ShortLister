import { DatePipe } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { ACTIVE_JOB_STATES, JobSummary } from '../../core/api.models';
import { ApiService, apiErrorMessage } from '../../core/api.service';
import { JOB_STATE_LABEL } from '../../shared/labels';

@Component({
  selector: 'app-jobs',
  imports: [
    DatePipe, RouterLink, MatButtonModule, MatIconModule, MatProgressBarModule, MatProgressSpinnerModule,
    MatSnackBarModule, MatTooltipModule,
  ],
  templateUrl: './jobs.html',
  styleUrl: './jobs.scss',
})
export class JobsPage {
  private readonly api = inject(ApiService);
  private readonly snack = inject(MatSnackBar);
  protected readonly JOB_STATE_LABEL = JOB_STATE_LABEL;
  protected readonly apiErrorMessage = apiErrorMessage;

  protected readonly jobs = rxResource({ stream: () => this.api.listJobs() });
  protected readonly confirming = signal<string | null>(null);

  protected isActive(j: JobSummary): boolean {
    return ACTIVE_JOB_STATES.includes(j.status);
  }

  protected remove(j: JobSummary): void {
    if (this.confirming() !== j.job_id) {
      this.confirming.set(j.job_id);
      setTimeout(() => this.confirming.update((id) => (id === j.job_id ? null : id)), 5000);
      return;
    }
    this.api.deleteJob(j.job_id).subscribe({
      next: () => {
        this.confirming.set(null);
        this.jobs.update((list) => list?.filter((x) => x.job_id !== j.job_id));
        this.snack.open('Job and all candidate data deleted.', undefined, { duration: 4000 });
      },
      error: (err) => this.snack.open(apiErrorMessage(err), 'Dismiss', { duration: 5000 }),
    });
  }
}
