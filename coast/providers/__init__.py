"""제공자 층 — base.SnapshotProvider 계약, parquet.ParquetProvider(1차), live.LiveProvider(자리)."""
from .base import SnapshotProvider  # noqa: F401
from .parquet import ParquetProvider  # noqa: F401
