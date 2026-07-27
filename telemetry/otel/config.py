"""Configuration for telemetry retention policies.

This module handles loading and parsing retention policy configs from YAML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _get_repo_root() -> Path:
    """Return the dancing-bear repo root (two levels above telemetry/otel/config.py)."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DataTypeRetention:
    """Retention configuration for a single data type (metrics, events, or spans)."""

    keep_days: int


@dataclass(frozen=True)
class RetentionConfig:
    """Complete retention policy configuration."""

    metrics: DataTypeRetention
    events: DataTypeRetention
    spans: DataTypeRetention
    min_records_after_prune: int = 10

    @classmethod
    def from_dict(cls, d: dict) -> RetentionConfig:
        """Parse a RetentionConfig from a dict."""
        metrics_keep = d.get("metrics", {}).get("keep_days", 30)
        events_keep = d.get("events", {}).get("keep_days", 30)
        spans_keep = d.get("spans", {}).get("keep_days", 30)
        min_records = d.get("min_records_after_prune", 10)
        return cls(
            metrics=DataTypeRetention(keep_days=metrics_keep),
            events=DataTypeRetention(keep_days=events_keep),
            spans=DataTypeRetention(keep_days=spans_keep),
            min_records_after_prune=min_records,
        )


def _resolve_config_path(config_dir: str | None = None) -> Path:
    """Resolve the path to retention.yaml config file.

    Args:
        config_dir: Optional override for the directory containing retention.yaml.

    Returns:
        Path to retention.yaml
    """
    if config_dir:
        return Path(config_dir) / "retention.yaml"
    return _get_repo_root() / "configs" / "telemetry" / "retention.yaml"


def load_retention_config(config_dir: str | None = None) -> RetentionConfig:
    """Load retention configuration from YAML file.

    Args:
        config_dir: Optional override for config directory.

    Returns:
        RetentionConfig object.

    Raises:
        FileNotFoundError: If config file not found.
        yaml.YAMLError: If config file is invalid YAML.
    """
    import yaml  # lazy import — not always needed
    config_path = _resolve_config_path(config_dir)

    if not config_path.exists():
        raise FileNotFoundError(f"Retention config not found at {config_path}")

    with open(config_path) as f:
        config_dict = yaml.safe_load(f) or {}

    return RetentionConfig.from_dict(config_dict)
