// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';

export type NoticeState = {
  busy: string;
  message: string;
  error: string;
  setMessage: (message: string) => void;
  setError: (error: string) => void;
  run: (name: string, fn: () => Promise<void>) => Promise<void>;
};

export function useNotice(): NoticeState {
  const [busy, setBusy] = React.useState('');
  const [message, setMessage] = React.useState('');
  const [error, setError] = React.useState('');

  const run = React.useCallback(async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setMessage('');
    setError('');
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  }, []);

  return { busy, message, error, setMessage, setError, run };
}
