import { Component, computed, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { EvidenceStatus } from '../core/api.models';
import { EVIDENCE_HELP, EVIDENCE_LABEL } from './labels';

const ICON: Record<EvidenceStatus, string> = {
  verified: 'verified',
  fuzzy: 'check',
  unverified: 'report',
  not_found: 'remove',
};

@Component({
  selector: 'app-evidence-chip',
  imports: [MatIconModule, MatTooltipModule],
  template: `
    <span class="chip" [class]="tone()" [matTooltip]="help()" tabindex="0">
      <mat-icon>{{ icon() }}</mat-icon>{{ label() }}
    </span>
  `,
})
export class EvidenceChip {
  readonly status = input.required<EvidenceStatus>();
  readonly match = input<number | null>(null);

  protected readonly icon = computed(() => ICON[this.status()]);
  protected readonly label = computed(() => EVIDENCE_LABEL[this.status()]);
  protected readonly tone = computed(() =>
    ({ verified: 'ok', fuzzy: 'ok', unverified: 'bad', not_found: 'plain' })[this.status()],
  );
  protected readonly help = computed(() => {
    const m = this.match();
    const base = EVIDENCE_HELP[this.status()];
    return this.status() === 'fuzzy' || this.status() === 'unverified' ? `${base} (best match ${m ?? 0}%)` : base;
  });
}
