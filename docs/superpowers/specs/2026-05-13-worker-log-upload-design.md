# Worker Log Upload — Design

**Status:** Approved (2026-05-13)
**Replaces:** the GlitchTip-based telemetry shipped in #43 / #46 / #48 / #50
**Components:** `services/local_worker`, `services/app` (Django)

## Background

After three releases (0.4.0 → 0.4.3) the worker's remote-diagnostics
story still has duplicate-shipping bugs in GlitchTip and depends on a
self-hosted Sentry-API-compatible service that is far more
infrastructure than the worker pool justifies. The actual requirement
is simple: **when a worker user has trouble, the maintainer needs to
get that worker's session log onto their machine.** GlitchTip's
issue/log search, retention tiers, OTLP ingest, and breadcrumb model
solve a much larger problem.

## Goals

- One-click crash uploads from the worker to the Wood League server,
  reusing the worker's existing API key.
- An explicit `submit-log "note"` command for volunteered uploads.
- Maintainer accesses uploads through Django admin; downloads via
  presigned URLs from a Railway object-storage bucket.
- Remove every line of `sentry-sdk` / GlitchTip plumbing from the
  worker.

## Non-Goals

- Searchable log indexing, breadcrumbs, issue grouping, retention
  tiers. If we ever need that we revisit; for now `grep` over a few
  files is fine.
- Real-time streaming. Uploads are post-hoc, per session.
- Anonymous uploads. The worker has an API key; we use it.

## Architecture

```
+----------+      POST /api/worker/logs/    +-----------+
|  worker  | ------------------------------>|  Django   |
| (PyPI)   |   Authorization: Bearer <key>  |  worker   |
|          |   multipart: log + note + meta |  endpoint |
+----------+                                +-----+-----+
                                                  |
                                                  v
                                    +-----------------------------+
                                    | Railway object-storage      |
                                    | bucket: "worker-logs"       |
                                    |   <worker_id>/<ts>.log      |
                                    +-----------------------------+
                                                  ^
                                                  |
+---------+         presigned URL            +----+-----+
| admin   | <-------------------------------- |  Django  |
| browser |   listed in WorkerLogUpload      |  admin   |
+---------+   admin changelist               +----------+
```

## Django side

### New model: `worker.WorkerLogUpload`

```python
class WorkerLogUpload(models.Model):
    worker = models.ForeignKey(Worker, on_delete=models.CASCADE)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    bucket_key = models.CharField(max_length=512)   # path inside the bucket
    size_bytes = models.PositiveIntegerField()
    note = models.TextField(blank=True)             # user-supplied or ""
    reason = models.CharField(                       # how the upload was triggered
        max_length=16,
        choices=[("crash", "crash"), ("manual", "manual")],
    )
    worker_version = models.CharField(max_length=32, blank=True)
    host_summary = models.JSONField(default=dict)    # banner snapshot
```

`bucket_key` template: `<worker_id_hash>/<iso8601-ts>.log` (matches the
worker_id hashing we already do, so the bucket can't be reverse-mapped
to a raw API key).

### Endpoint: `POST /api/worker/logs/`

- Auth: same `Authorization: Bearer <worker-api-key>` middleware the
  worker already uses for job claim / report.
- Body: `multipart/form-data` with three parts:
  - `log` — the file (max 100 MB; reject larger with 413).
  - `note` — optional UTF-8 string (max 4 KB).
  - `metadata` — JSON: `{"reason": "crash"|"manual", "worker_version": "...", "host_summary": {...}}`.
- Behavior:
  1. Authenticate worker by API key; reject 401 if unknown.
  2. Stream the file body to the bucket using
     `boto3.client("s3", endpoint_url=settings.RAILWAY_BUCKET_ENDPOINT)`
     with key `<worker_id_hash>/<ts>.log`.
  3. Create the `WorkerLogUpload` row inside the same transaction (if
     the bucket upload succeeds).
  4. Return `201 {"id": ..., "bucket_key": "..."}`.
- Rate-limit: 1 upload per worker per minute (manual or crash). Crash
  uploads bypass with a `force=true` query param honoured server-side
  to allow follow-up crashes.

### Admin

- Register `WorkerLogUpload` in Django admin with a custom
  `list_display`: worker name, uploaded_at, size_kb, reason, first line
  of note.
- Add a "Download" action per row that returns an HTTP 302 to a
  bucket-issued presigned URL (default 15-minute TTL, configurable via
  `WORKER_LOG_PRESIGN_TTL_SECONDS`).
- Add a list-page action "Bulk download zip" that creates a tar+gz of
  the selected logs server-side and streams it back — useful when
  triaging several at once.

### Bucket provisioning

- Railway → add object storage plugin → name `worker-logs`.
- Add the four env vars Railway emits (`AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL_S3`, `BUCKET_NAME`) to the
  Django service.
- Settings:
  ```python
  WORKER_LOG_BUCKET = os.environ["BUCKET_NAME"]
  WORKER_LOG_S3_ENDPOINT = os.environ["AWS_ENDPOINT_URL_S3"]
  WORKER_LOG_PRESIGN_TTL_SECONDS = int(
      os.environ.get("WORKER_LOG_PRESIGN_TTL_SECONDS", "900")
  )
  ```

## Worker side

### Remove

- `sentry-sdk` from `pyproject.toml`.
- `_DEFAULT_GLITCHTIP_DSN` constant.
- `init_telemetry`'s `sentry_sdk.init(...)` call and the
  `LoggingIntegration` import.
- `tests/test_init_telemetry.py` and the telemetry portions of
  `tests/test_telemetry.py` that exercise sentry-sdk.

### Repurpose the consent prompt

The existing JSON config (`<user_config_dir>/config.json`) already
stores a `telemetry: bool` flag. Migrate that key in place:

- Read the existing config file; treat the legacy `telemetry` bool as
  the new `log_upload_consent` bool. Write back the renamed key. Both
  reads gracefully handle either spelling for one release.
- First-run prompt text becomes:
  > "Allow the worker to upload its session log to Wood League when
  > something goes wrong, so the maintainers can help debug? [y/N]"

### CLI changes

```
wood-league-worker submit-log "what happened"  # explicit upload
wood-league-worker telemetry status            # renamed in help text;
                                               # subcommand name stays
                                               # for backward compat
```

`submit-log`:
1. Read the current `worker.log`.
2. Build the metadata block from the most recent session banner.
3. POST to `/api/worker/logs/` with `reason=manual`.
4. Print the returned `id` and `bucket_key`.

Crash hook:
- Install `sys.excepthook` inside `_startup`. On uncaught exception:
  1. Print the traceback to stderr as today.
  2. If consent is True, prompt: "Upload this crash log to maintainers? [Y/n]"
     (default Y because consent was already given upfront).
  3. POST to `/api/worker/logs/` with `reason=crash`.

The session banner already captures hardware/engine info; we send that
JSON-encoded as `metadata.host_summary`.

### New module: `services/local_worker/local_worker/log_upload.py`

- `upload_log(reason: Literal["crash", "manual"], note: str = "") -> int`
- `install_crash_hook()`
- Both fail soft: any HTTP/network error is logged locally and the
  worker continues. We never let upload failures crash a `run`.

## Storage / privacy

- Logs may contain absolute paths that include the user's home dir
  name. Documented in the consent prompt's expanded help (printed if
  the user types `?` instead of `y`/`n`).
- The Django bucket entries are never publicly listable; only the
  admin user can mint presigned URLs.
- The bucket has no public ACL; presigned URLs are the only access
  path.
- Retention: configurable via a server cron that deletes
  `WorkerLogUpload` rows + bucket keys older than
  `WORKER_LOG_RETENTION_DAYS` (default 30). Cron lives in
  `services/app/worker/management/commands/prune_worker_logs.py`.

## Migration / rollout

- Bump `wood-league-worker` 0.4.3 → 0.5.0 (removing a dep + new
  features = minor).
- Django: ship the migration and the bucket plugin in one Railway
  deploy.
- Worker: ship the upload-only release. Existing GlitchTip
  installation can be torn down once at least one user has upgraded;
  no harm in leaving it dormant until then.
- Update wiki and worker README:
  - Drop the "Diagnostics and telemetry" GlitchTip wording.
  - Replace with a "Sharing logs with maintainers" section describing
    `submit-log`, the crash prompt, and the consent semantics.

## Testing

### Worker (unit)

- `submit-log` posts the right multipart body; metadata + note are
  attached.
- Crash hook captures + uploads when consent is True; no-ops when
  False.
- Network failure during upload prints a user-visible warning and
  exits 0; does not raise.
- Consent-config migration: legacy `{"telemetry": true}` reads as new
  `log_upload_consent=True`.

### Django (unit / integration)

- `POST /api/worker/logs/` happy path: 201, bucket gets the file,
  `WorkerLogUpload` row created.
- 401 on missing/wrong API key.
- 413 on >100 MB body.
- Rate-limit enforced per worker; `force=true` bypasses.
- Admin download action returns a 302 to a presigned URL with the
  configured TTL.

### Manual

- Trigger an intentional crash from `run` and confirm the upload
  prompt + upload succeed end-to-end on Railway.
- Download from Django admin and confirm the file contents match the
  local `worker.log`.

## Open Questions

None at design time. Confirm the Railway bucket plugin name during
provisioning.
