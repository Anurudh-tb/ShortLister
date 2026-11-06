import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { switchMap } from 'rxjs';

import { ApiService, apiErrorMessage } from '../../core/api.service';
import { AuthStore } from '../../core/auth';

const MIN_PASSWORD_LENGTH = 8;

/** Sign-up for new users: POST /api/auth/signup, then signs straight in with POST /api/auth/login. */
@Component({
  selector: 'app-signup',
  imports: [FormsModule],
  templateUrl: './signup.html',
  styleUrl: '../login/login.scss',
})
export class SignupPage {
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthStore);

  protected readonly minLength = MIN_PASSWORD_LENGTH;
  protected readonly username = signal('');
  protected readonly password = signal('');
  protected readonly confirm = signal('');
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  /** Read-only until focused, so the browser doesn't autofill saved credentials (see login page). */
  protected readonly locked = signal(true);

  constructor() {
    this.auth.signOut();
  }

  protected unlock(): void {
    this.locked.set(false);
  }

  protected submit(): void {
    const username = this.username().trim();
    const password = this.password();
    // Same rules as the backend, which checks them again.
    const problem = !username
      ? 'Choose a username.'
      : password.length < MIN_PASSWORD_LENGTH || !/[A-Za-z]/.test(password) || !/\d/.test(password)
        ? `Password must be at least ${MIN_PASSWORD_LENGTH} characters with a letter and a number.`
        : password !== this.confirm()
          ? 'The passwords do not match.'
          : null;
    if (problem) {
      this.error.set(problem);
      return;
    }
    this.error.set(null);
    this.busy.set(true);
    this.api
      .signup(username, password)
      .pipe(switchMap(() => this.api.login(username, password)))
      .subscribe({
        next: (res) => {
          this.busy.set(false);
          this.password.set('');
          this.confirm.set('');
          this.auth.signIn(res.username, res.access_token, res.expires_in);
          this.router.navigateByUrl('/setup');
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(
            err.status === 0
              ? 'Could not reach the server. Check that the backend is running and try again.'
              : apiErrorMessage(err),
          );
        },
      });
  }

  protected signIn(): void {
    this.router.navigateByUrl('/login');
  }
}
