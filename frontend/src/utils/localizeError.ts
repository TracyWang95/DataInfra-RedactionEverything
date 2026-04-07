// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { t, useI18n } from '@/i18n';

type ErrorLike = {
  message?: unknown;
  status?: unknown;
  response?: {
    status?: unknown;
    data?: {
      message?: unknown;
      detail?: unknown;
    };
  };
};

function toText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function extractStatus(raw: string, error?: ErrorLike): string | null {
  const explicit =
    typeof error?.status === 'number'
      ? String(error.status)
      : typeof error?.response?.status === 'number'
        ? String(error.response.status)
        : null;
  if (explicit) return explicit;

  const match = raw.match(/\b(\d{3})\b/);
  return match ? match[1] : null;
}

function isChinese(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text);
}

export function localizeErrorMessage(error: unknown, fallbackKey = 'common.error'): string {
  const candidate = (error && typeof error === 'object' ? error : null) as ErrorLike | null;
  const locale = useI18n.getState().locale;
  const raw =
    toText(candidate?.response?.data?.message) ||
    toText(candidate?.response?.data?.detail) ||
    toText(candidate?.message) ||
    toText(error);

  if (!raw) {
    return t(fallbackKey);
  }

  const lower = raw.toLowerCase();
  const status = extractStatus(raw, candidate ?? undefined);

  if (
    lower.includes('failed to fetch') ||
    lower.includes('network error') ||
    lower.includes('networkerror') ||
    raw.includes('网络连接失败')
  ) {
    return t('common.networkError');
  }

  if (
    lower.includes('request failed with status code') ||
    lower === 'request failed' ||
    raw.includes('请求失败')
  ) {
    if (status) {
      return (Number(status) >= 500 ? t('common.serverErrorWithStatus') : t('common.requestFailedWithStatus'))
        .replace('{status}', status);
    }
    return t('common.requestFailed');
  }

  if (
    lower.includes('download failed') ||
    raw.includes('下载失败')
  ) {
    if (status) {
      return t('common.downloadFailedWithStatus').replace('{status}', status);
    }
    return t('common.downloadFailed');
  }

  if (
    lower.includes('failed to load file') ||
    lower.includes('failed to load config') ||
    lower.startsWith('failed to load ') ||
    lower === 'load failed' ||
    raw.includes('加载文件失败')
  ) {
    if (status) {
      return t('common.loadFailedWithStatus').replace('{status}', status);
    }
    return t('common.loadFailed');
  }

  if (
    lower === 'fetch failed' ||
    lower === 'export failed' ||
    lower === 'import failed'
  ) {
    if (status) {
      return (Number(status) >= 500 ? t('common.serverErrorWithStatus') : t('common.requestFailedWithStatus'))
        .replace('{status}', status);
    }
    return t(fallbackKey);
  }

  if (lower === 'failed' || raw === '失败') {
    return t(fallbackKey);
  }

  if (isChinese(raw)) {
    return raw;
  }

  if (/[A-Za-z]/.test(raw)) {
    return locale === 'en' ? raw : t(fallbackKey);
  }

  return t(fallbackKey);
}
