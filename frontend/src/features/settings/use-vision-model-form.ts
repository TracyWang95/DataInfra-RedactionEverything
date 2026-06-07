// Copyright 2026 DataInfra-RedactionEverything Contributors
// SPDX-License-Identifier: Apache-2.0

import { useState, useCallback } from 'react';
import { DEFAULT_MODEL_FORM, type ModelConfig } from './hooks/use-model-config';

interface ConfirmState {
  title: string;
  message: string;
  danger?: boolean;
  onConfirm: () => void | Promise<void>;
}

export function useVisionModelForm(
  saveModelConfig: (form: Partial<ModelConfig>, editingId: string | null) => Promise<boolean>,
) {
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<Partial<ModelConfig>>({ ...DEFAULT_MODEL_FORM });
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);

  const openAdd = useCallback(() => {
    setEditingId(null);
    setForm({ ...DEFAULT_MODEL_FORM, enabled: true });
    setShowModal(true);
  }, []);

  const openEdit = useCallback((config: ModelConfig) => {
    setEditingId(config.id);
    setForm({ ...config });
    setShowModal(true);
  }, []);

  const handleSave = useCallback(async () => {
    const ok = await saveModelConfig(form, editingId);
    if (!ok) return;
    setShowModal(false);
    setEditingId(null);
    setForm({ ...DEFAULT_MODEL_FORM });
  }, [form, editingId, saveModelConfig]);

  const closeModal = useCallback(() => {
    setShowModal(false);
    setEditingId(null);
  }, []);

  const updateForm = useCallback((patch: Partial<ModelConfig>) => {
    setForm((current) => ({ ...current, ...patch }));
  }, []);

  const requestConfirm = useCallback((state: ConfirmState) => {
    setConfirmState(state);
  }, []);

  const confirmAndClose = useCallback(() => {
    confirmState?.onConfirm();
    setConfirmState(null);
  }, [confirmState]);

  const cancelConfirm = useCallback(() => {
    setConfirmState(null);
  }, []);

  return {
    showModal,
    editingId,
    form,
    confirmState,
    openAdd,
    openEdit,
    handleSave,
    closeModal,
    updateForm,
    requestConfirm,
    confirmAndClose,
    cancelConfirm,
  };
}
