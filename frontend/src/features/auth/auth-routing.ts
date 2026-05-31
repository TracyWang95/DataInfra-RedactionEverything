// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

export type AuthMode = 'login' | 'register';

export function sanitizeNextPath(next: string | null | undefined): string {
  if (!next || !next.startsWith('/') || next.startsWith('//')) return '/';
  return next;
}

export function resolveAuthNext(search: string): string {
  return sanitizeNextPath(new URLSearchParams(search).get('next'));
}

export function resolveAuthMode(search: string): AuthMode {
  return new URLSearchParams(search).get('mode') === 'register' ? 'register' : 'login';
}

export function isRegisterAuthSearch(search: string): boolean {
  return resolveAuthMode(search) === 'register';
}
