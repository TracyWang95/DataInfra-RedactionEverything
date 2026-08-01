"""Compat shims loaded automatically via PYTHONPATH for HaS/vLLM on Ascend."""

try:
    from transformers.tokenization_utils_base import PreTrainedTokenizerBase

    if not hasattr(PreTrainedTokenizerBase, "all_special_tokens_extended"):
        # Removed in newer transformers; vLLM 0.11 still reads this attribute.
        def _all_special_tokens_extended(self):
            try:
                return list(self.all_special_tokens)
            except Exception:
                return []

        PreTrainedTokenizerBase.all_special_tokens_extended = property(  # type: ignore[attr-defined]
            _all_special_tokens_extended
        )
except Exception:
    pass
