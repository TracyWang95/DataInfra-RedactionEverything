// Copyright 2026 DataInfra-RedactionEverything Contributors

import { useState } from 'react';
import { useT } from '@/i18n';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { authFetch } from '@/services/api-client';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ChangePasswordDialog({ open, onClose }: Props) {
  const t = useT();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const reset = () => {
    setOldPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setError(null);
    setDone(false);
  };

  const close = () => {
    reset();
    onClose();
  };

  async function submit() {
    if (newPassword !== confirmPassword) {
      setError(t('auth.changePassword.mismatch'));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await authFetch('/api/v1/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = (await res.json()) as { detail?: string };
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep status text */
        }
        throw new Error(detail);
      }
      // Backend rotates the session cookie in the response - no re-login needed.
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.changePassword.failed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent className="max-w-md p-6" data-testid="change-password-dialog">
        <DialogHeader className="text-left">
          <DialogTitle className="text-base font-semibold">
            {t('auth.changePassword')}
          </DialogTitle>
          <DialogDescription className="text-sm text-muted-foreground">
            {done ? t('auth.changePassword.success') : t('auth.changePassword.desc')}
          </DialogDescription>
        </DialogHeader>

        {!done && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="cp-old">{t('auth.changePassword.old')}</Label>
              <Input
                id="cp-old"
                type="password"
                autoComplete="current-password"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cp-new">{t('auth.changePassword.new')}</Label>
              <Input
                id="cp-new"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t('auth.changePassword.policy')}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cp-confirm">{t('auth.confirmPassword')}</Label>
              <Input
                id="cp-confirm"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>
        )}

        <DialogFooter className="gap-2 pt-2 sm:justify-end">
          {done ? (
            <Button type="button" onClick={close} data-testid="change-password-done">
              {t('common.confirm')}
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={close}>
                {t('common.cancel')}
              </Button>
              <Button
                type="button"
                disabled={saving || !oldPassword || !newPassword || !confirmPassword}
                onClick={() => void submit()}
                data-testid="change-password-submit"
              >
                {saving ? t('auth.changePassword.saving') : t('auth.changePassword')}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
