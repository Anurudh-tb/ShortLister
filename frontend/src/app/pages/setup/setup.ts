import { HttpEventType } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { Router /* , RouterLink */ } from '@angular/router'; // RouterLink only used by the disabled rubric link

import { ModelsResponse, PublicConfig } from '../../core/api.models';
import { ApiService, apiErrorMessage } from '../../core/api.service';
import { WorkflowStore } from '../../core/workflow.store';
import { DropZone } from '../../shared/drop-zone';
import { formatBytes } from '../../shared/labels';

const ACCEPTED = ['.pdf', '.docx', '.txt'];

@Component({
  selector: 'app-setup',
  imports: [
    FormsModule, /* RouterLink, */ MatButtonModule, MatFormFieldModule, MatIconModule,
    MatProgressSpinnerModule, MatSelectModule, DropZone,
  ],
  templateUrl: './setup.html',
  styleUrl: './setup.scss',
})
export class SetupPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly store = inject(WorkflowStore);
  protected readonly formatBytes = formatBytes;

  // Kept in the store so the JD survives leaving and returning to this page.
  protected readonly jdText = this.store.jdText;
  protected readonly jdFile = this.store.jdFile;

  /** Default JD and criteria from the backend, used when no JD is given. */
  protected readonly config = signal<PublicConfig | null>(null);
  protected readonly defaults = computed(() => {
    const c = this.config();
    return c?.default_jd && c.default_criteria ? { jd: c.default_jd, criteria: c.default_criteria } : null;
  });

  protected readonly models = signal<ModelsResponse | null>(null);
  protected readonly modelsError = signal<string | null>(null);
  protected readonly selectedModel = signal<string | null>(this.store.model());

  protected readonly resumes = signal<File[]>(this.store.pendingResumes());
  protected readonly resumesSize = computed(() => this.resumes().reduce((a, f) => a + f.size, 0));

  protected readonly generating = signal(false);
  protected readonly scoring = signal(false);
  protected readonly error = signal<string | null>(null);

  /** ~4 chars per token, same heuristic as the backend. */
  protected readonly approxTokens = computed(() => Math.round(this.jdText().length / 4));
  private readonly hasJd = computed(() => !!this.jdFile() || this.jdText().trim().length >= 50);
  /** No JD file and no typed text: the backend scores against the default JD and criteria. */
  protected readonly usingDefaults = computed(() => !this.jdFile() && !this.jdText().trim());
  protected readonly busy = computed(() => this.generating() || this.scoring());
  protected readonly canGenerate = computed(() => !this.busy() && !!this.selectedModel() && this.hasJd());
  protected readonly canScore = computed(
    () =>
      !this.busy() &&
      !!this.selectedModel() &&
      this.resumes().length > 0 &&
      (this.hasJd() || (this.usingDefaults() && !!this.defaults())),
  );

  constructor() {
    this.loadModels();
    this.api
      .getConfig()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: (c) => this.config.set(c), error: () => this.config.set(null) });
  }

  protected loadModels(): void {
    this.modelsError.set(null);
    this.api
      .listModels()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.models.set(res);
          const names = res.models.map((m) => m.name);
          const current = this.selectedModel();
          if (!current || !names.includes(current)) {
            this.selectedModel.set(names.includes(res.default_model) ? res.default_model : (names[0] ?? null));
          }
        },
        error: (err) => this.modelsError.set(apiErrorMessage(err)),
      });
  }

  protected onFiles(files: File[]): void {
    this.jdFile.set(files[0] ?? null);
    this.error.set(null);
  }

  protected onResumes(files: File[]): void {
    const keyOf = (f: File) => `${f.name}:${f.size}:${f.lastModified}`;
    const existing = new Set(this.resumes().map(keyOf));
    const skipped: string[] = [];
    const added = files.filter((f) => {
      const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase();
      if (!ACCEPTED.includes(ext)) {
        skipped.push(f.name);
        return false;
      }
      if (existing.has(keyOf(f))) return false;
      existing.add(keyOf(f));
      return true;
    });
    this.setResumes([...this.resumes(), ...added]);
    // A picked folder can hold many unrelated files; name only the first few.
    const names = skipped.slice(0, 3).join(', ') + (skipped.length > 3 ? ` and ${skipped.length - 3} more` : '');
    this.error.set(skipped.length ? `Skipped ${names}: use PDF, DOCX or TXT` : null);
  }

  protected removeResume(file: File): void {
    this.setResumes(this.resumes().filter((f) => f !== file));
  }

  protected setResumes(files: File[]): void {
    this.resumes.set(files);
    this.store.pendingResumes.set(files); // carried to the Resumes page if the user edits the rubric first
  }

  protected onTextInput(value: string): void {
    // With an uploaded JD, typed text is extra criteria sent alongside the file, so the file is kept.
    this.jdText.set(value);
  }

  protected generate(): void {
    const model = this.selectedModel();
    if (!this.canGenerate() || !model) return;
    this.generating.set(true);
    this.error.set(null);
    this.api
      .generateRubric({ jdFile: this.jdFile() ?? undefined, jdText: this.jdText(), model })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.store.jdText.set(res.jd_text);
          this.store.model.set(res.model);
          this.store.setGeneratedRubric(res.rubric, res.warnings);
          this.generating.set(false);
          this.router.navigateByUrl('/rubric');
        },
        error: (err) => {
          this.error.set(apiErrorMessage(err));
          this.generating.set(false);
        },
      });
  }

  /**
   * One step: the backend builds the rubric from the JD, then scores every resume against it. With no
   * JD, nothing JD-related is sent and the backend uses its default JD and criteria.
   */
  protected score(): void {
    const model = this.selectedModel();
    if (!this.canScore() || !model) return;
    this.scoring.set(true);
    this.error.set(null);
    this.api
      .startScoring(this.resumes(), { jdFile: this.jdFile() ?? undefined, jdText: this.jdText(), model })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (event) => {
          if (event.type !== HttpEventType.Response || !event.body) return;
          this.store.model.set(model);
          this.setResumes([]);
          this.scoring.set(false);
          this.router.navigate(['/jobs', event.body.job_id]);
        },
        error: (err) => {
          this.error.set(apiErrorMessage(err));
          this.scoring.set(false);
        },
      });
  }
}
