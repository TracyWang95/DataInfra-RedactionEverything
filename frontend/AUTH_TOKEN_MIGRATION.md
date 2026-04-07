# Auth Token Migration Assessment: localStorage → httpOnly Cookie

## Current State
JWT stored in `localStorage` via `api-client.ts`. XSS vulnerability: any injected script can steal tokens.

## Target
httpOnly cookie set by backend on `/auth/login` response. Frontend uses `credentials: 'include'` instead of `Authorization` header.

## Backend Changes Required
- `/auth/login` and `/auth/setup`: return token via `Set-Cookie` (httpOnly, Secure, SameSite=Strict)
- `/auth/refresh`: read token from cookie instead of header
- CORS: add `allow_credentials=True` (already set) + ensure `Access-Control-Allow-Origin` is NOT `*`
- CSRF middleware: already implemented (double-submit cookie pattern)

## Frontend Changes Required
- Remove `localStorage.getItem/setItem('auth_token')` from `api-client.ts`
- Remove `Authorization: Bearer` interceptor
- Add `withCredentials: true` to axios instance
- Update `authenticatedBlobUrl()` to use fetch with `credentials: 'include'`

## Risks
- Breaking change for API consumers using Bearer tokens (need transition period)
- Cross-origin setups (frontend/backend on different ports) need careful CORS config
- Mobile/non-browser clients still need Bearer token support

## Recommendation
**Defer to v1.1.** Current CSRF middleware + SameSite cookie already mitigates most browser attacks. Implement as opt-in feature with both auth methods supported during transition.
