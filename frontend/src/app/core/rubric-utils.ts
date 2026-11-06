import { Criterion } from './api.models';

export const WEIGHT_TOTAL = 100;

/** Scale weights to integers summing to exactly 100 (largest-remainder; mirrors backend normalize_weights). */
export function normalizeWeights(weights: number[]): number[] {
  if (weights.length === 0) return [];
  const clean = weights.map((w) => (Number.isFinite(w) && w > 0 ? w : 0));
  const sum = clean.reduce((a, b) => a + b, 0);
  const scaled = sum === 0 ? clean.map(() => WEIGHT_TOTAL / clean.length) : clean.map((w) => (w * WEIGHT_TOTAL) / sum);
  const floors = scaled.map(Math.floor);
  let remainder = WEIGHT_TOTAL - floors.reduce((a, b) => a + b, 0);
  const order = scaled.map((s, i) => ({ i, frac: s - floors[i] })).sort((a, b) => b.frac - a.frac || a.i - b.i);
  for (const { i } of order) {
    if (remainder-- <= 0) break;
    floors[i] += 1;
  }
  return floors;
}

export function rubricProblems(criteria: Criterion[]): string[] {
  const problems: string[] = [];
  if (criteria.length === 0) problems.push('Add at least one criterion.');
  const total = criteria.reduce((a, c) => a + (Number(c.weight) || 0), 0);
  if (total !== WEIGHT_TOTAL) problems.push(`Weights add up to ${total}; they must total ${WEIGHT_TOTAL}.`);
  if (criteria.some((c) => !c.name.trim())) problems.push('Every criterion needs a name.');
  const names = criteria.map((c) => c.name.trim().toLowerCase()).filter(Boolean);
  if (new Set(names).size !== names.length) problems.push('Criterion names must be unique.');
  if (criteria.some((c) => !Number.isInteger(Number(c.weight)) || c.weight < 0 || c.weight > WEIGHT_TOTAL)) {
    problems.push('Weights must be whole numbers between 0 and 100.');
  }
  return problems;
}
