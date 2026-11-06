import { Component, computed, effect, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';

import { Criterion, Rubric } from '../../core/api.models';
import { WEIGHT_TOTAL, normalizeWeights, rubricProblems } from '../../core/rubric-utils';
import { WorkflowStore } from '../../core/workflow.store';

interface Row extends Criterion {
  key: number; // stable identity for @for tracking while editing
}

let nextKey = 1;
const toRows = (r: Rubric | null): Row[] => (r?.criteria ?? []).map((c) => ({ ...c, key: nextKey++ }));

@Component({
  selector: 'app-rubric-editor',
  imports: [RouterLink, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatIconModule, MatInputModule, MatTooltipModule],
  templateUrl: './rubric-editor.html',
  styleUrl: './rubric-editor.scss',
})
export class RubricEditorPage {
  protected readonly store = inject(WorkflowStore);
  private readonly router = inject(Router);

  protected readonly jobTitle = signal(this.store.rubric()?.job_title ?? '');
  protected readonly rows = signal<Row[]>(toRows(this.store.rubric()));

  protected readonly total = computed(() => this.rows().reduce((a, r) => a + (Number(r.weight) || 0), 0));
  protected readonly problems = computed(() => rubricProblems(this.rows()));
  protected readonly mustHaveCount = computed(() => this.rows().filter((r) => r.must_have).length);
  protected readonly WEIGHT_TOTAL = WEIGHT_TOTAL;

  constructor() {
    // Persist every edit so navigating away and back keeps the work.
    effect(() => {
      if (this.rows().length === 0 && !this.store.rubric()) return;
      this.store.rubric.set(this.toRubric());
    });
  }

  protected update(key: number, patch: Partial<Criterion>): void {
    this.rows.update((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  protected setWeight(key: number, raw: string): void {
    const n = raw === '' ? 0 : Math.round(Number(raw));
    this.update(key, { weight: Number.isFinite(n) ? Math.max(0, Math.min(WEIGHT_TOTAL, n)) : 0 });
  }

  protected add(): void {
    this.rows.update((rows) => [...rows, { key: nextKey++, name: '', description: '', weight: 0, must_have: false }]);
  }

  protected remove(key: number): void {
    this.rows.update((rows) => rows.filter((r) => r.key !== key));
  }

  protected move(key: number, delta: -1 | 1): void {
    this.rows.update((rows) => {
      const i = rows.findIndex((r) => r.key === key);
      const j = i + delta;
      if (i < 0 || j < 0 || j >= rows.length) return rows;
      const copy = [...rows];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  }

  protected normalize(): void {
    const weights = normalizeWeights(this.rows().map((r) => Number(r.weight) || 0));
    this.rows.update((rows) => rows.map((r, i) => ({ ...r, weight: weights[i] })));
  }

  protected reset(): void {
    const generated = this.store.generatedRubric();
    this.rows.set(toRows(generated));
    this.jobTitle.set(generated?.job_title ?? '');
  }

  protected continue(): void {
    if (this.problems().length) return;
    this.store.rubric.set(this.toRubric());
    this.router.navigateByUrl('/upload');
  }

  private toRubric(): Rubric {
    return {
      job_title: this.jobTitle().trim() || null,
      criteria: this.rows().map(({ key: _key, ...c }) => ({
        ...c,
        name: c.name.trim(),
        description: c.description.trim(),
        weight: Number(c.weight) || 0,
      })),
    };
  }
}
