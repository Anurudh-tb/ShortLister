import { Observable, switchMap, takeWhile, timer } from 'rxjs';

import { ACTIVE_JOB_STATES, JobDetail } from './api.models';
import { ApiService } from './api.service';

export const POLL_INTERVAL_MS = 2000;

/** Emit the job immediately, then every 2 s while it is still running (including the final state). */
export function pollJob(api: ApiService, jobId: string): Observable<JobDetail> {
  return timer(0, POLL_INTERVAL_MS).pipe(
    switchMap(() => api.getJob(jobId)),
    takeWhile((job) => ACTIVE_JOB_STATES.includes(job.status), true),
  );
}
