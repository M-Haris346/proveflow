"""Shared base model: immutable, rejects unknown fields at every boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """All proveflow domain models are frozen and forbid extra fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")
