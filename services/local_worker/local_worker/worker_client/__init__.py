"""
Title: worker_client/__init__.py — HTTP client for the Wood League worker API
Description:
    Re-exports WorkerClient, WorkerClientError, and Job for use by the worker loop.

Changelog:
    2026-05-10: Copied from packages/shared to make local_worker self-contained for PyPI
"""
from .client import WorkerClient, WorkerClientError
from .models import Job

__all__ = ["WorkerClient", "WorkerClientError", "Job"]
