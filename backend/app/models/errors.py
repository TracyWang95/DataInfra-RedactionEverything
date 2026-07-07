"""Semantic service-layer exceptions for HTTP status-code mapping.

These deliberately subclass ``ValueError`` so that every existing
``except ValueError`` handler keeps working unchanged; routes that want
precise status codes catch the subclasses *before* ``ValueError``.
"""


class NotFoundError(ValueError):
    """Requested resource does not exist (routes map this to HTTP 404)."""


class ConflictError(ValueError):
    """Operation conflicts with the resource's current state (HTTP 409)."""


class ValidationError(ValueError):
    """Request is semantically invalid (HTTP 400)."""
