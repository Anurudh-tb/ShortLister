import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, input } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { CandidateResult, CriterionResult } from '../../core/api.models';
import { ApiService, apiErrorMessage } from '../../core/api.service';
import { WorkflowStore } from '../../core/workflow.store';
import { EvidenceChip } from '../../shared/evidence-chip';

interface CompareRow {
  criterion: string;
  weight: number;
  mustHave: boolean;
  cells: (CriterionResult | null)[];
  best: number;
}

@Component({
  selector: 'app-compare',
  imports: [DecimalPipe, RouterLink, MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatTooltipModule, EvidenceChip],
  templateUrl: './compare.html',
  styleUrl: './compare.scss',
})
export class ComparePage {
  readonly jobId = input.required<string>();
  /** Comma-separated candidate ids from the `?ids=` query param. */
  readonly ids = input<string>('');

  private readonly api = inject(ApiService);
  protected readonly store = inject(WorkflowStore);
  protected readonly apiErrorMessage = apiErrorMessage;

  protected readonly job = rxResource({ params: () => this.jobId(), stream: ({ params }) => this.api.getJob(params) });

  protected readonly candidates = computed<CandidateResult[]>(() => {
    const all = this.job.value()?.candidates ?? [];
    const wanted = this.ids().split(',').filter(Boolean);
    return wanted.map((id) => all.find((c) => c.id === id)).filter((c): c is CandidateResult => !!c && c.status === 'done');
  });

  protected readonly rows = computed<CompareRow[]>(() => {
    const rubric = this.job.value()?.rubric;
    const cands = this.candidates();
    if (!rubric) return [];
    return rubric.criteria.map((crit) => {
      const cells = cands.map((c) => c.criteria.find((x) => x.criterion === crit.name) ?? null);
      return {
        criterion: crit.name,
        weight: crit.weight,
        mustHave: crit.must_have,
        cells,
        best: Math.max(...cells.map((x) => x?.score ?? 0)),
      };
    });
  });

  protected readonly bestTotal = computed(() => Math.max(...this.candidates().map((c) => c.total_score ?? 0)));
}
