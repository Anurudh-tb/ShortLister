import { Routes } from '@angular/router';

import { authGuard } from './core/auth';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'login' },
  { path: 'login', title: 'Sign in · Resume Shortlister', loadComponent: () => import('./pages/login/login').then((m) => m.LoginPage) },
  { path: 'signup', title: 'Sign up · Resume Shortlister', loadComponent: () => import('./pages/signup/signup').then((m) => m.SignupPage) },
  { path: 'setup', canActivate: [authGuard], title: 'Setup · Resume Shortlister', loadComponent: () => import('./pages/setup/setup').then((m) => m.SetupPage) },
  // Rubric step disabled: Setup scores directly and the backend generates the rubric from the JD.
  // { path: 'rubric', title: 'Rubric · Resume Shortlister', loadComponent: () => import('./pages/rubric/rubric-editor').then((m) => m.RubricEditorPage) },
  // Resumes step disabled: resumes are uploaded on Setup.
  // { path: 'upload', title: 'Resumes · Resume Shortlister', loadComponent: () => import('./pages/upload/upload').then((m) => m.UploadPage) },
  { path: 'jobs', canActivate: [authGuard], title: 'Jobs · Resume Shortlister', loadComponent: () => import('./pages/jobs/jobs').then((m) => m.JobsPage) },
  { path: 'jobs/:jobId', canActivate: [authGuard], title: 'Results · Resume Shortlister', loadComponent: () => import('./pages/results/results').then((m) => m.ResultsPage) },
  {
    path: 'jobs/:jobId/compare',
    canActivate: [authGuard],
    title: 'Compare · Resume Shortlister',
    loadComponent: () => import('./pages/compare/compare').then((m) => m.ComparePage),
  },
  {
    path: 'jobs/:jobId/candidates/:candidateId',
    canActivate: [authGuard],
    title: 'Candidate · Resume Shortlister',
    loadComponent: () => import('./pages/candidate/candidate-detail').then((m) => m.CandidateDetailPage),
  },
  { path: '**', redirectTo: 'login' },
];
