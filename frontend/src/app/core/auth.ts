import { HttpErrorResponse, HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, tap, throwError } from 'rxjs';

const AUTH_KEY = 'shortlister.auth';

interface Session {
  username: string;
  token: string;
  /** Epoch ms after which the backend rejects the token. */
  expiresAt: number;
}

function readSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    const s = raw ? (JSON.parse(raw) as Session) : null;
    return s?.token && s.expiresAt > Date.now() ? s : null;
  } catch {
    return null;
  }
}

/**
 * Signed-in user and their JWT for this browser tab. Kept in sessionStorage (cleared when the tab
 * closes), never localStorage, and the password itself is never stored.
 */
@Injectable({ providedIn: 'root' })
export class AuthStore {
  private readonly session = signal<Session | null>(readSession());
  readonly user = computed(() => this.session()?.username ?? null);

  get token(): string | null {
    const s = this.session();
    return s && s.expiresAt > Date.now() ? s.token : null;
  }

  signIn(username: string, token: string, expiresInSeconds: number): void {
    const s: Session = { username, token, expiresAt: Date.now() + expiresInSeconds * 1000 };
    this.session.set(s);
    try {
      sessionStorage.setItem(AUTH_KEY, JSON.stringify(s));
    } catch {
      /* storage unavailable: stays signed in until reload */
    }
  }

  /** Swap in a renewed token for the same user (sent by the backend while the session is active). */
  renew(token: string, expiresInSeconds: number): void {
    const user = this.user();
    if (user) this.signIn(user, token, expiresInSeconds);
  }

  signOut(): void {
    this.session.set(null);
    try {
      sessionStorage.removeItem(AUTH_KEY);
    } catch {
      /* ignore */
    }
  }
}

/** Sends signed-out visitors (or ones whose token has expired) to the login page. */
export const authGuard: CanActivateFn = () =>
  inject(AuthStore).token ? true : inject(Router).createUrlTree(['/login']);

/**
 * Adds `Authorization: Bearer <token>` to API calls and picks up renewed tokens from the
 * X-Access-Token response header (tokens are short-lived). A 401 from the API ends the session.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  const token = auth.token;
  const isLogin = /\/auth\/(login|signup)$/.test(req.url);
  const authed = token && !isLogin ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
  return next(authed).pipe(
    tap((event) => {
      if (!(event instanceof HttpResponse)) return;
      const renewed = event.headers.get('X-Access-Token');
      const expiresIn = Number(event.headers.get('X-Access-Token-Expires-In'));
      if (renewed && expiresIn > 0) auth.renew(renewed, expiresIn);
    }),
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !isLogin) {
        auth.signOut();
        router.navigateByUrl('/login');
      }
      return throwError(() => err);
    }),
  );
};
