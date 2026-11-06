import { HttpEventType } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { PublicConfig } from '../../core/api.models';
import { ApiService, apiErrorMessage } from '../../core/api.service';
import { WorkflowStore } from '../../core/workflow.store';
import { DropZone } from '../../shared/drop-zone';
import { DEFAULT_SECONDS_PER_RESUME, formatBytes, formatDuration } from '../../shared/labels';

const ACCEPTED = ['.pdf', '.docx', '.txt'];

type FileState = 'ready' | 'invalid' | 'uploading' | 'queued' | 'error';

interface FileRow {
  key: string;
  file: File;
  state: FileState;
  message: string;
}

@Component({
  selector: 'app-upload',
  imports: [RouterLink, MatButtonModule, MatIconModule, MatProgressBarModule, MatTooltipModule, DropZone],
  templateUrl: './upload.html',
  styleUrl: './upload.scss',
})
export class UploadPage {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly store = inject(WorkflowStore);
  protected readonly formatBytes = formatBytes;

  protected readonly config = signal<PublicConfig | null>(null);
  protected readonly rows = signal<FileRow[]>([]);
  protected readonly uploadPercent = signal<number | null>(null);
  protected readonly jobId = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly readyRows = computed(() => this.rows().filter((r) => r.state === 'ready'));
  protected readonly submitted = computed(() => this.jobId() !== null || this.uploadPercent() !== null);
  protected readonly overLimit = computed(() => {
    const max = this.config()?.max_resumes_per_job;
    return max !== undefined && this.readyRows().length > max;
  });
  protected readonly estimate = computed(() => formatDuration(this.readyRows().length * DEFAULT_SECONDS_PER_RESUME));
  protected readonly serverErrors = computed(() => this.rows().filter((r) => r.state === 'error').length);

  constructor() {
    // Take over any resumes already picked on the Setup page.
    this.onFiles(this.store.pendingResumes());
    this.store.pendingResumes.set([]);
    this.api.getConfig().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (c) => {
        this.config.set(c);
        this.rows.update((rows) => rows.map((r) => this.validate(r.file, r.key)));
      },
      error: (err) => this.error.set(apiErrorMessage(err)),
    });
  }

  protected onFiles(files: File[]): void {
    if (this.submitted()) this.startOver();
    const existing = new Set(this.rows().map((r) => r.key));
    const added = files
      .map((f) => this.validate(f, `${f.name}:${f.size}:${f.lastModified}`))
      .filter((r) => {
        if (existing.has(r.key)) return false;
        existing.add(r.key);
        return true;
      });
    this.rows.update((rows) => [...rows, ...added]);
  }

  protected remove(key: string): void {
    this.rows.update((rows) => rows.filter((r) => r.key !== key));
  }

  protected startOver(): void {
    this.rows.set([]);
    this.jobId.set(null);
    this.uploadPercent.set(null);
    this.error.set(null);
  }

  protected start(): void {
    const rubric = this.store.rubric();
    const ready = this.readyRows();
    if (!rubric || ready.length === 0 || this.overLimit()) return;
    this.error.set(null);
    this.uploadPercent.set(0);
    this.setStates(ready, 'uploading', 'Uploading…');

    this.api
      .startScoring(ready.map((r) => r.file), { rubric, model: this.store.model() ?? undefined })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress && event.total) {
            this.uploadPercent.set(Math.round((100 * event.loaded) / event.total));
          } else if (event.type === HttpEventType.Response && event.body) {
            const created = event.body;
            this.uploadPercent.set(100);
            this.jobId.set(created.job_id);
            // The backend returns candidates in upload order; map server-side extraction results back to rows.
            ready.forEach((row, i) => {
              const c = created.candidates[i];
              if (c?.status === 'error') this.setStates([row], 'error', c.error ?? 'Could not read file');
              else this.setStates([row], 'queued', 'Text extracted · queued for scoring');
            });
          }
        },
        error: (err) => {
          this.uploadPercent.set(null);
          this.setStates(ready, 'ready', 'Ready');
          this.error.set(apiErrorMessage(err));
        },
      });
  }

  private setStates(targets: FileRow[], state: FileState, message: string): void {
    const keys = new Set(targets.map((t) => t.key));
    this.rows.update((rows) => rows.map((r) => (keys.has(r.key) ? { ...r, state, message } : r)));
  }

  private validate(file: File, key: string): FileRow {
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
    const maxMb = this.config()?.max_file_mb;
    if (!ACCEPTED.includes(ext)) {
      return { key, file, state: 'invalid', message: `Unsupported type (${ext || 'none'}); use PDF, DOCX or TXT` };
    }
    if (file.size === 0) return { key, file, state: 'invalid', message: 'File is empty' };
    if (maxMb !== undefined && file.size > maxMb * 1024 * 1024) {
      return { key, file, state: 'invalid', message: `Too large; the limit is ${maxMb} MB` };
    }
    return { key, file, state: 'ready', message: 'Ready' };
  }
}
