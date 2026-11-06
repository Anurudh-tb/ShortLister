import { Criterion } from './api.models';
import { normalizeWeights, rubricProblems } from './rubric-utils';

const c = (name: string, weight: number): Criterion => ({ name, description: '', weight, must_have: false });

describe('normalizeWeights (mirrors backend largest-remainder)', () => {
  it.each([
    [[40, 35, 25], [40, 35, 25]],
    [[1, 1, 1], [34, 33, 33]],
    [[0, 0], [50, 50]],
    [[10, 10, 10, 10, 10, 10, 10], [15, 15, 14, 14, 14, 14, 14]],
    [[3, 3, 4], [30, 30, 40]],
  ])('%j -> %j', (input, expected) => {
    const out = normalizeWeights(input);
    expect(out).toEqual(expected);
    expect(out.reduce((a, b) => a + b, 0)).toBe(100);
  });

  it('treats negative / NaN weights as 0', () => {
    expect(normalizeWeights([-5, NaN, 10])).toEqual([0, 0, 100]);
  });
});

describe('rubricProblems', () => {
  it('accepts a valid rubric', () => {
    expect(rubricProblems([c('Python', 60), c('AWS', 40)])).toEqual([]);
  });

  it('reports a wrong total, blank and duplicate names', () => {
    const problems = rubricProblems([c('Python', 50), c(' python', 30), c('', 10)]);
    expect(problems.join(' ')).toContain('add up to 90');
    expect(problems.join(' ')).toContain('needs a name');
    expect(problems.join(' ')).toContain('unique');
  });

  it('requires at least one criterion', () => {
    expect(rubricProblems([])[0]).toContain('at least one');
  });
});
