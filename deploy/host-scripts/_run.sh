#!/bin/bash
echo "=== fetchWithTimeout: does it attach token / credentials? ==="
cat ~/redaction-deploy/frontend/src/utils/fetchWithTimeout.* 2>/dev/null | head -60
echo "=== how login stores token (cookie vs localStorage) + axios interceptor ==="
grep -rnE 'localStorage|setItem|access_token|document.cookie|Authorization|Bearer|credentials|interceptor|withCredentials' ~/redaction-deploy/frontend/src/services/api.ts ~/redaction-deploy/frontend/src/features/**/auth*.ts* ~/redaction-deploy/frontend/src/**/useAuth*.ts* 2>/dev/null | head -20
echo "=== login endpoint: does backend SET a cookie? ==="
grep -rnE 'set_cookie|access_token|Set-Cookie|response.set_cookie|httponly' ~/redaction-deploy/backend/app/api/auth_api.py 2>/dev/null | head -10
echo "=== DONE ==="
