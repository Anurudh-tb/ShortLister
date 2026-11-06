import { Component, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { AuthStore } from './core/auth';
import { WorkflowStore } from './core/workflow.store';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatButtonModule, MatIconModule, MatSlideToggleModule, MatTooltipModule],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly store = inject(WorkflowStore);
  protected readonly auth = inject(AuthStore);
  private readonly router = inject(Router);

  /** The sign-in and sign-up pages are full-screen, without the app header. */
  protected readonly isLogin = toSignal(
    this.router.events.pipe(
      filter((e) => e instanceof NavigationEnd),
      map((e) => /^\/(login|signup)\b/.test(e.urlAfterRedirects)),
    ),
    { initialValue: false },
  );

  protected readonly steps = [
    { path: '/setup', label: 'Setup', n: 1 },
    // Rubric and Resumes steps disabled; see app.routes.ts. Resumes are uploaded on Setup.
    // { path: '/rubric', label: 'Rubric', n: 2 },
    // { path: '/upload', label: 'Resumes', n: 3 },
    { path: '/jobs', label: 'Results', n: 2 },
  ];

  protected signOut(): void {
    this.auth.signOut();
    this.router.navigateByUrl('/login');
  }
}
