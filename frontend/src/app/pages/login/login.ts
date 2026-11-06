import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService, apiErrorMessage } from '../../core/api.service';
import { AuthStore } from '../../core/auth';

/** Sign-in screen for registered users. The backend checks the users table and returns a JWT for later API calls. */
@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class LoginPage {
  private readonly router = inject(Router);
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthStore);

  protected readonly username = signal('');
  protected readonly password = signal('');
  protected readonly error = signal<string | null>(null);
  protected readonly info = signal<string | null>(null);
  protected readonly busy = signal(false);
  /**
   * Fields start read-only so the browser doesn't fill in saved credentials; each becomes editable on focus.
   * Saved passwords can still be picked manually from the browser's own key icon.
   */
  protected readonly locked = signal(true);

  constructor() {
    // Opening the login page ends any previous session in this tab.
    this.auth.signOut();
  }

  protected unlock(): void {
    this.locked.set(false);
  }

  protected submit(): void {
    this.info.set(null);
    const username = this.username().trim();
    if (!username) {
      this.error.set('Enter your username.');
      return;
    }
    if (!this.password()) {
      this.error.set('Enter your password.');
      return;
    }
    this.error.set(null);
    this.busy.set(true);
    this.api.login(username, this.password()).subscribe({
      next: (res) => {
        this.busy.set(false);
        this.password.set('');
        this.auth.signIn(res.username, res.access_token, res.expires_in);
        this.router.navigateByUrl('/setup');
      },
      error: (err: HttpErrorResponse) => {
        this.busy.set(false);
        this.password.set('');
        this.error.set(
          err.status === 401
            ? 'Incorrect username or password.'
            : err.status === 0
              ? 'Could not reach the server. Check that the backend is running and try again.'
              : apiErrorMessage(err), // e.g. 429: "Too many attempts. Try again in 15 minutes."
        );
      },
    });
  }

  protected forgotPassword(): void {
    this.error.set(null);
    this.info.set('Password reset is not available yet. Contact your administrator.');
  }

  protected signUp(): void {
    this.router.navigateByUrl('/signup');
  }
}
