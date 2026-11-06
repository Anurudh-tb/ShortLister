import { Injectable, effect, signal } from '@angular/core';

import { CandidateResult, Rubric } from './api.models';

const SESSION_KEY = 'shortlister.workflow';
const BLIND_KEY = 'shortlister.blind';

interface PersistedWorkflow {
  jdText: string;
  model: string | null;
  rubric: Rubric | null;
  generatedRubric: Rubric | null;
  rubricWarnings: string[];
}

/** Wizard state shared by the Setup -> Rubric -> Upload pages; survives page reloads (sessionStorage). */
@Injectable({ providedIn: 'root' })
export class WorkflowStore {
  private readonly saved = readJson<PersistedWorkflow>(sessionStorage, SESSION_KEY);

  readonly jdText = signal(this.saved?.jdText ?? '');
  /** Uploaded JD file; wins over jdText. Files can't be serialised, so it only survives in-app navigation. */
  readonly jdFile = signal<File | null>(null);
  readonly model = signal<string | null>(this.saved?.model ?? null);
  /** The rubric being edited / used for scoring. */
  readonly rubric = signal<Rubric | null>(this.saved?.rubric ?? null);
  /** The rubric exactly as the model generated it, for "reset". */
  readonly generatedRubric = signal<Rubric | null>(this.saved?.generatedRubric ?? null);
  readonly rubricWarnings = signal<string[]>(this.saved?.rubricWarnings ?? []);
  /** Resumes picked on Setup, handed to the Resumes page. Files can't be serialised, so not persisted. */
  readonly pendingResumes = signal<File[]>([]);
  /** Blind review: hide names and filenames to reduce bias. Per-browser preference. */
  readonly blindMode = signal(readJson<boolean>(localStorage, BLIND_KEY) ?? false);

  constructor() {
    effect(() => {
      const state: PersistedWorkflow = {
        jdText: this.jdText(),
        model: this.model(),
        rubric: this.rubric(),
        generatedRubric: this.generatedRubric(),
        rubricWarnings: this.rubricWarnings(),
      };
      writeJson(sessionStorage, SESSION_KEY, state);
    });
    effect(() => writeJson(localStorage, BLIND_KEY, this.blindMode()));
  }

  setGeneratedRubric(rubric: Rubric, warnings: string[]): void {
    this.generatedRubric.set(structuredClone(rubric));
    this.rubric.set(structuredClone(rubric));
    this.rubricWarnings.set(warnings);
  }

  displayName(c: Pick<CandidateResult, 'id' | 'candidate_name' | 'filename'>): string {
    if (this.blindMode()) return `Candidate ${c.id.slice(0, 4).toUpperCase()}`;
    return c.candidate_name || c.filename;
  }

  displayFilename(c: Pick<CandidateResult, 'filename'>): string {
    return this.blindMode() ? 'hidden in blind mode' : c.filename;
  }
}

function readJson<T>(storage: Storage, key: string): T | null {
  try {
    const raw = storage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJson(storage: Storage, key: string, value: unknown): void {
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or disabled: state just won't survive a reload.
  }
}
