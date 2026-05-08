# Add Analysis Worker API

**priority:** high  
**status:** completed  
**created:** 2026-05-06  
**claimed-by:** Copilot


## Description

This is a single Django server. You are adding /api/v1/ endpoints to the
existing project — NOT creating a separate application or second process.

════════════════════════════════════════════════════════════
EXISTING PROJECT — DO NOT BREAK
════════════════════════════════════════════════════════════

Apps already present (do not modify their public APIs):
  accounts, dashboard, games, analysis, openings, players, search, ingest

Key facts:
  • Project package directory contains settings.py and urls.py — confirm
    the exact name by reading manage.py before editing anything.
  • accounts.User is a custom email-based model (AUTH_USER_MODEL).
  • LoginRequiredMiddleware enforces session auth on every route except
    /auth/login/ and /auth/logout/.
  • Admin pages live at /admin/analysis-status/ and /admin/members/ —
    match their Tailwind v4 styling exactly.
  • HTMX partials live at /_partials/<app>/... via each app's
    partial_urls.py. Views branch on request.htmx.
  • The ingest app has management commands run_analysis_worker and
    run_lc0_worker. Both use SELECT FOR UPDATE SKIP LOCKED to claim jobs
    and reset stale jobs (running > 10 min) back to pending on startup.
  • config.md requires: run `bandit -ll <file>` after EVERY .py edit and
    fix any Medium/High findings before moving on.
  • A pre-commit snyk hook blocks commits with Medium/High code issues.
  • Railway deploys via railway.toml; `python manage.py migrate` runs
    automatically on deploy.

════════════════════════════════════════════════════════════
STEP 1 — ADD DEPENDENCIES
════════════════════════════════════════════════════════════

Append to requirements.txt:
  djangorestframework>=3.15
  djangorestframework-api-key>=3.0

════════════════════════════════════════════════════════════
STEP 2 — CREATE THE `api` APP
════════════════════════════════════════════════════════════

  python manage.py startapp api

Add to INSTALLED_APPS in settings.py (after existing apps):
  'rest_framework',
  'rest_framework_api_key',
  'api',

════════════════════════════════════════════════════════════
STEP 3 — DRF SETTINGS
════════════════════════════════════════════════════════════

Add to settings.py:

  REST_FRAMEWORK = {
      # No session auth on the API — key auth is permission-based
      'DEFAULT_AUTHENTICATION_CLASSES': [],
      'DEFAULT_PERMISSION_CLASSES': [
          'rest_framework_api_key.permissions.HasAPIKey',
      ],
      'DEFAULT_THROTTLE_CLASSES': [
          'rest_framework.throttling.ScopedRateThrottle',
      ],
      'DEFAULT_THROTTLE_RATES': {
          'checkout': '60/min',
          'complete': '120/min',
          'heartbeat': '600/min',
      },
      'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
  }

  # Workers send:  X-Api-Key: <key>
  API_KEY_CUSTOM_HEADER = 'HTTP_X_API_KEY'

  # Tunable fault-tolerance constants (override in .env)
  import os
  STALE_JOB_TIMEOUT_MINUTES = int(os.environ.get('STALE_JOB_TIMEOUT_MINUTES', 15))
  MAX_JOB_RETRIES = int(os.environ.get('MAX_JOB_RETRIES', 3))

Also add these two variables to the .env documentation table in README.md:
  STALE_JOB_TIMEOUT_MINUTES   No   15   Minutes before a running job is
                                        considered stale and requeued
  MAX_JOB_RETRIES             No    3   Max attempts before a job is
                                        marked failed

════════════════════════════════════════════════════════════
STEP 4 — BYPASS LoginRequiredMiddleware FOR /api/v1/
════════════════════════════════════════════════════════════

Open accounts/middleware.py (or wherever LoginRequiredMiddleware lives).
Add /api/v1/ to the exempt prefixes alongside /auth/login/ and
/auth/logout/. The API uses key auth, not session auth.

Example pattern (adapt to the actual implementation):

  EXEMPT_PREFIXES = ('/auth/login/', '/auth/logout/', '/api/v1/')

  def __call__(self, request):
      if any(request.path.startswith(p) for p in EXEMPT_PREFIXES):
          return self.get_response(request)
      ...

════════════════════════════════════════════════════════════
STEP 5 — WorkerAPIKey MODEL  (api/models.py)
════════════════════════════════════════════════════════════

  from django.conf import settings
  from django.db import models
  from rest_framework_api_key.models import AbstractAPIKey

  class WorkerAPIKey(AbstractAPIKey):
      """
      API key issued to a remote analysis worker.
      Keys are hashed at rest; the raw key is shown exactly once at
      creation. The 8-char prefix is non-secret and safe to log/store.
      """
      worker_name  = models.CharField(max_length=128)
      created_by   = models.ForeignKey(
          settings.AUTH_USER_MODEL,
          on_delete=models.SET_NULL,
          null=True, blank=True,
          related_name='issued_api_keys',
      )
      last_used_at = models.DateTimeField(null=True, blank=True)
      notes        = models.TextField(blank=True)

      class Meta(AbstractAPIKey.Meta):
          verbose_name        = 'Worker API Key'
          verbose_name_plural = 'Worker API Keys'

Generate the migration:
  python manage.py makemigrations api

════════════════════════════════════════════════════════════
STEP 6 — ADDITIVE MIGRATION ON analysis_jobs
════════════════════════════════════════════════════════════

Add three nullable fields to the existing AnalysisJob model in
analysis/models.py:

  # Who claimed this job (non-secret key prefix — safe to store/log)
  claimed_by_key_prefix = models.CharField(
      max_length=8, null=True, blank=True,
      help_text='8-char API key prefix of the worker that claimed this job',
  )
  # When the job was checked out (separate from started_at)
  claimed_at = models.DateTimeField(null=True, blank=True)
  # Per-job Lc0 node budget; null for Stockfish jobs
  nodes = models.IntegerField(
      null=True, blank=True,
      help_text='Lc0 MCTS node budget for this job; null means use LC0_NODES setting',
  )

Generate the migration:
  python manage.py makemigrations analysis

Verify the generated migration contains ONLY AddField operations — no
AlterField on existing columns. If it contains anything else, stop and
investigate before proceeding.

════════════════════════════════════════════════════════════
STEP 7 — SHARED SERVICE LAYER  (analysis/services/jobs.py)
════════════════════════════════════════════════════════════

Create analysis/services/__init__.py (empty) and
analysis/services/jobs.py with the following public API.

The management commands run_analysis_worker and run_lc0_worker must be
refactored to call these functions instead of containing the logic inline.
Pass key_prefix=None from management commands (local execution has no key).

  from datetime import timedelta
  from django.conf import settings
  from django.db import transaction
  from django.utils import timezone
  from analysis.models import (
      AnalysisJob, GameAnalysis, MoveAnalysis,
      Lc0GameAnalysis, Lc0MoveAnalysis,
  )

  # ── Constants ────────────────────────────────────────────────────────────

  def _stale_timeout() -> timedelta:
      return timedelta(minutes=settings.STALE_JOB_TIMEOUT_MINUTES)

  def _max_retries() -> int:
      return settings.MAX_JOB_RETRIES

  # ── Stale recovery ───────────────────────────────────────────────────────

  def recover_stale_jobs(engine: str) -> int:
      """
      Reset jobs stuck in 'running' for longer than STALE_JOB_TIMEOUT_MINUTES
      back to 'pending'. Called automatically before every checkout.
      Returns the number of jobs recovered.
      """
      cutoff = timezone.now() - _stale_timeout()
      return AnalysisJob.objects.filter(
          engine=engine,
          status=AnalysisJob.STATUS_RUNNING,
          started_at__lt=cutoff,
      ).update(
          status=AnalysisJob.STATUS_PENDING,
          worker_id=None,
          started_at=None,
          claimed_at=None,
          claimed_by_key_prefix=None,
      )

  # ── Claim jobs ───────────────────────────────────────────────────────────

  def claim_jobs(
      *,
      engine: str,
      batch_size: int,
      worker_id: str,
      key_prefix: str | None = None,
  ) -> list[AnalysisJob]:
      """
      Atomically claim up to batch_size pending jobs using
      SELECT FOR UPDATE SKIP LOCKED. Runs stale recovery first.
      Returns the claimed AnalysisJob instances with their related Game.
      """
      with transaction.atomic():
          recover_stale_jobs(engine)
          jobs = list(
              AnalysisJob.objects
              .select_for_update(skip_locked=True)
              .filter(engine=engine, status=AnalysisJob.STATUS_PENDING)
              .order_by('-priority', 'created_at')
              [:batch_size]
          )
          if not jobs:
              return []
          now = timezone.now()
          job_ids = [j.id for j in jobs]
          AnalysisJob.objects.filter(id__in=job_ids).update(
              status=AnalysisJob.STATUS_RUNNING,
              started_at=now,
              claimed_at=now,
              worker_id=worker_id,
              claimed_by_key_prefix=key_prefix,
          )
          return list(
              AnalysisJob.objects
              .filter(id__in=job_ids)
              .select_related('game')
          )

  # ── Complete: Stockfish ──────────────────────────────────────────────────

  def complete_stockfish_job(
      *,
      job_id: int,
      worker_id: str,
      key_prefix: str | None,
      payload: dict,
  ) -> None:
      """
      Write Stockfish results and mark the job completed.
      Raises AnalysisJob.DoesNotExist if the job is not found,
      not in 'running' state, or the worker_id / key_prefix do not match.
      """
      with transaction.atomic():
          # Ownership check: worker_id AND key_prefix must match the claim
          filters = dict(
              id=job_id,
              status=AnalysisJob.STATUS_RUNNING,
              worker_id=worker_id,
          )
          if key_prefix is not None:
              filters['claimed_by_key_prefix'] = key_prefix
          job = AnalysisJob.objects.select_for_update().get(**filters)

          # Upsert game_analysis
          GameAnalysis.objects.update_or_create(
              game=job.game,
              defaults=dict(
                  white_accuracy=payload['white_accuracy'],
                  black_accuracy=payload['black_accuracy'],
                  white_acpl=payload['white_acpl'],
                  black_acpl=payload['black_acpl'],
                  white_blunders=payload['white_blunders'],
                  white_mistakes=payload['white_mistakes'],
                  white_inaccuracies=payload['white_inaccuracies'],
                  black_blunders=payload['black_blunders'],
                  black_mistakes=payload['black_mistakes'],
                  black_inaccuracies=payload['black_inaccuracies'],
                  engine_depth=payload['engine_depth'],
                  analyzed_at=timezone.now(),
              ),
          )

          # Replace move_analysis rows for this game
          MoveAnalysis.objects.filter(game=job.game).delete()
          MoveAnalysis.objects.bulk_create([
              MoveAnalysis(
                  game=job.game,
                  ply=m['ply'],
                  san=m['san'],
                  fen=m['fen'],
                  cp_eval=m['cp_eval'],
                  cpl=m['cpl'],
                  best_move=m['best_move'],
                  classification=m['classification'],
              )
              for m in payload['moves']
          ])

          job.status = AnalysisJob.STATUS_COMPLETED
          job.completed_at = timezone.now()
          job.save(update_fields=['status', 'completed_at'])

  # ── Complete: Lc0 ───────────────────────────────────────────────────────

  def complete_lc0_job(
      *,
      job_id: int,
      worker_id: str,
      key_prefix: str | None,
      payload: dict,
  ) -> None:
      """
      Write Lc0 results and mark the job completed.
      Same ownership semantics as complete_stockfish_job.
      """
      with transaction.atomic():
          filters = dict(
              id=job_id,
              status=AnalysisJob.STATUS_RUNNING,
              worker_id=worker_id,
          )
          if key_prefix is not None:
              filters['claimed_by_key_prefix'] = key_prefix
          job = AnalysisJob.objects.select_for_update().get(**filters)

          Lc0GameAnalysis.objects.update_or_create(
              game=job.game,
              defaults=dict(
                  white_win_prob=payload['white_win_prob'],
                  white_draw_prob=payload['white_draw_prob'],
                  white_loss_prob=payload['white_loss_prob'],
                  black_win_prob=payload['black_win_prob'],
                  black_draw_prob=payload['black_draw_prob'],
                  black_loss_prob=payload['black_loss_prob'],
                  white_blunders=payload['white_blunders'],
                  white_mistakes=payload['white_mistakes'],
                  white_inaccuracies=payload['white_inaccuracies'],
                  black_blunders=payload['black_blunders'],
                  black_mistakes=payload['black_mistakes'],
                  black_inaccuracies=payload['black_inaccuracies'],
                  engine_nodes=payload['engine_nodes'],
                  network_name=payload.get('network_name', ''),
                  analyzed_at=timezone.now(),
              ),
          )

          Lc0MoveAnalysis.objects.filter(game=job.game).delete()
          Lc0MoveAnalysis.objects.bulk_create([
              Lc0MoveAnalysis(
                  game=job.game,
                  ply=m['ply'],
                  san=m['san'],
                  fen=m['fen'],
                  wdl_win=m['wdl_win'],
                  wdl_draw=m['wdl_draw'],
                  wdl_loss=m['wdl_loss'],
                  cp_equiv=m.get('cp_equiv'),
                  best_move=m['best_move'],
                  arrow_uci=m.get('arrow_uci', ''),
                  move_win_delta=m['move_win_delta'],
                  classification=m['classification'],
              )
              for m in payload['moves']
          ])

          job.status = AnalysisJob.STATUS_COMPLETED
          job.completed_at = timezone.now()
          job.save(update_fields=['status', 'completed_at'])

  # ── Fail a job ───────────────────────────────────────────────────────────

  def fail_job(
      *,
      job_id: int,
      worker_id: str,
      key_prefix: str | None,
      error: str,
  ) -> str:
      """
      Increment retry_count. Requeue if under MAX_JOB_RETRIES, else mark
      failed. Returns 'requeued' or 'failed'.
      """
      with transaction.atomic():
          filters = dict(
              id=job_id,
              status=AnalysisJob.STATUS_RUNNING,
              worker_id=worker_id,
          )
          if key_prefix is not None:
              filters['claimed_by_key_prefix'] = key_prefix
          job = AnalysisJob.objects.select_for_update().get(**filters)

          job.retry_count += 1
          job.error_message = error[:2000]

          if job.retry_count >= _max_retries():
              job.status = AnalysisJob.STATUS_FAILED
              outcome = 'failed'
          else:
              job.status = AnalysisJob.STATUS_PENDING
              job.worker_id = None
              job.claimed_by_key_prefix = None
              job.claimed_at = None
              outcome = 'requeued'

          job.save()
          return outcome

After writing this file, run `bandit -ll analysis/services/jobs.py` and
fix any Medium/High findings.

Then refactor ingest/management/commands/run_analysis_worker.py and
run_lc0_worker.py to import and call these functions. Pass
key_prefix=None (local workers have no API key).

════════════════════════════════════════════════════════════
STEP 8 — SERIALIZERS  (api/serializers.py)
════════════════════════════════════════════════════════════

  from rest_framework import serializers

  ENGINE_CHOICES = ['stockfish', 'lc0']
  CLASSIFICATION_CHOICES = [
      'Brilliant', 'Great', 'Best', 'Excellent',
      'Inaccuracy', 'Mistake', 'Blunder',
  ]

  class CheckoutRequestSerializer(serializers.Serializer):
      engine     = serializers.ChoiceField(choices=ENGINE_CHOICES)
      batch_size = serializers.IntegerField(min_value=1, max_value=10, default=1)
      worker_id  = serializers.CharField(max_length=64)

  class JobSerializer(serializers.Serializer):
      """Outbound: what a worker receives when it checks out a job."""
      id       = serializers.IntegerField()
      game_id  = serializers.CharField(source='game.id')
      pgn      = serializers.CharField(source='game.pgn')
      engine   = serializers.CharField()
      depth    = serializers.IntegerField()   # Stockfish depth
      nodes    = serializers.IntegerField(allow_null=True)  # Lc0 nodes

  class StockfishMoveSerializer(serializers.Serializer):
      ply            = serializers.IntegerField(min_value=1)
      san            = serializers.CharField(max_length=10)
      fen            = serializers.CharField(max_length=100)
      cp_eval        = serializers.IntegerField()
      cpl            = serializers.IntegerField(min_value=0)
      best_move      = serializers.CharField(max_length=10)
      classification = serializers.ChoiceField(choices=CLASSIFICATION_CHOICES)

  class StockfishCompleteSerializer(serializers.Serializer):
      worker_id          = serializers.CharField(max_length=64)
      engine_depth       = serializers.IntegerField(min_value=1, max_value=40)
      white_accuracy     = serializers.FloatField(min_value=0, max_value=100)
      black_accuracy     = serializers.FloatField(min_value=0, max_value=100)
      white_acpl         = serializers.FloatField(min_value=0)
      black_acpl         = serializers.FloatField(min_value=0)
      white_blunders     = serializers.IntegerField(min_value=0)
      white_mistakes     = serializers.IntegerField(min_value=0)
      white_inaccuracies = serializers.IntegerField(min_value=0)
      black_blunders     = serializers.IntegerField(min_value=0)
      black_mistakes     = serializers.IntegerField(min_value=0)
      black_inaccuracies = serializers.IntegerField(min_value=0)
      moves              = StockfishMoveSerializer(many=True, max_length=500)

  class Lc0MoveSerializer(serializers.Serializer):
      ply            = serializers.IntegerField(min_value=1)
      san            = serializers.CharField(max_length=10)
      fen            = serializers.CharField(max_length=100)
      wdl_win        = serializers.IntegerField(min_value=0, max_value=1000)
      wdl_draw       = serializers.IntegerField(min_value=0, max_value=1000)
      wdl_loss       = serializers.IntegerField(min_value=0, max_value=1000)
      cp_equiv       = serializers.IntegerField(required=False, allow_null=True)
      best_move      = serializers.CharField(max_length=10)
      arrow_uci      = serializers.CharField(max_length=10, required=False, default='')
      move_win_delta = serializers.FloatField()
      classification = serializers.ChoiceField(choices=CLASSIFICATION_CHOICES)

  class Lc0CompleteSerializer(serializers.Serializer):
      worker_id          = serializers.CharField(max_length=64)
      engine_nodes       = serializers.IntegerField(min_value=1)
      network_name       = serializers.CharField(max_length=128, required=False, default='')
      white_win_prob     = serializers.FloatField(min_value=0, max_value=1)
      white_draw_prob    = serializers.FloatField(min_value=0, max_value=1)
      white_loss_prob    = serializers.FloatField(min_value=0, max_value=1)
      black_win_prob     = serializers.FloatField(min_value=0, max_value=1)
      black_draw_prob    = serializers.FloatField(min_value=0, max_value=1)
      black_loss_prob    = serializers.FloatField(min_value=0, max_value=1)
      white_blunders     = serializers.IntegerField(min_value=0)
      white_mistakes     = serializers.IntegerField(min_value=0)
      white_inaccuracies = serializers.IntegerField(min_value=0)
      black_blunders     = serializers.IntegerField(min_value=0)
      black_mistakes     = serializers.IntegerField(min_value=0)
      black_inaccuracies = serializers.IntegerField(min_value=0)
      moves              = Lc0MoveSerializer(many=True, max_length=500)

  class JobFailSerializer(serializers.Serializer):
      worker_id = serializers.CharField(max_length=64)
      error     = serializers.CharField(max_length=2000)

  class HeartbeatSerializer(serializers.Serializer):
      worker_id      = serializers.CharField(max_length=64)
      engine         = serializers.ChoiceField(choices=ENGINE_CHOICES)
      status_message = serializers.CharField(max_length=256, required=False, default='')

════════════════════════════════════════════════════════════
STEP 9 — VIEWS  (api/views.py)
════════════════════════════════════════════════════════════

Views are thin: parse → validate → call service → return response.
All business logic stays in analysis.services.jobs.

  from django.utils import timezone
  from rest_framework import status
  from rest_framework.response import Response
  from rest_framework.views import APIView
  from rest_framework_api_key.permissions import HasAPIKey
  from analysis.models import AnalysisJob, WorkerHeartbeat
  from analysis.services import jobs as job_service
  from . import serializers as sz


  def _key_prefix(request) -> str:
      """Return the non-secret 8-char prefix of the authenticated key."""
      return request.auth.prefix


  def _touch_key(request) -> None:
      """Update last_used_at on the WorkerAPIKey for every authenticated call."""
      request.auth.last_used_at = timezone.now()
      request.auth.save(update_fields=['last_used_at'])


  class HealthView(APIView):
      """Public health check — no auth, no throttle."""
      permission_classes = []

      def get(self, request):
          return Response({'status': 'ok'})


  class JobCheckoutView(APIView):
      permission_classes = [HasAPIKey]
      throttle_scope = 'checkout'

      def post(self, request):
          ser = sz.CheckoutRequestSerializer(data=request.data)
          ser.is_valid(raise_exception=True)
          d = ser.validated_data

          claimed = job_service.claim_jobs(
              engine=d['engine'],
              batch_size=d['batch_size'],
              worker_id=d['worker_id'],
              key_prefix=_key_prefix(request),
          )
          _touch_key(request)
          return Response(
              {'jobs': sz.JobSerializer(claimed, many=True).data},
              status=status.HTTP_200_OK,
          )


  class JobCompleteView(APIView):
      permission_classes = [HasAPIKey]
      throttle_scope = 'complete'

      def post(self, request, job_id):
          engine = request.data.get('engine')
          if engine == 'stockfish':
              ser = sz.StockfishCompleteSerializer(data=request.data)
          elif engine == 'lc0':
              ser = sz.Lc0CompleteSerializer(data=request.data)
          else:
              return Response(
                  {'error': 'engine must be "stockfish" or "lc0"'},
                  status=status.HTTP_400_BAD_REQUEST,
              )

          ser.is_valid(raise_exception=True)
          d = ser.validated_data

          try:
              if engine == 'stockfish':
                  job_service.complete_stockfish_job(
                      job_id=job_id,
                      worker_id=d['worker_id'],
                      key_prefix=_key_prefix(request),
                      payload=d,
                  )
              else:
                  job_service.complete_lc0_job(
                      job_id=job_id,
                      worker_id=d['worker_id'],
                      key_prefix=_key_prefix(request),
                      payload=d,
                  )
          except AnalysisJob.DoesNotExist:
              return Response(
                  {'error': 'Job not found, not running, or not owned by this worker'},
                  status=status.HTTP_404_NOT_FOUND,
              )

          _touch_key(request)
          return Response({'status': 'completed'})


  class JobFailView(APIView):
      permission_classes = [HasAPIKey]

      def post(self, request, job_id):
          ser = sz.JobFailSerializer(data=request.data)
          ser.is_valid(raise_exception=True)
          d = ser.validated_data

          try:
              outcome = job_service.fail_job(
                  job_id=job_id,
                  worker_id=d['worker_id'],
                  key_prefix=_key_prefix(request),
                  error=d['error'],
              )
          except AnalysisJob.DoesNotExist:
              return Response(
                  {'error': 'Job not found, not running, or not owned by this worker'},
                  status=status.HTTP_404_NOT_FOUND,
              )

          _touch_key(request)
          return Response({'status': outcome})


  class HeartbeatView(APIView):
      permission_classes = [HasAPIKey]
      throttle_scope = 'heartbeat'

      def post(self, request):
          ser = sz.HeartbeatSerializer(data=request.data)
          ser.is_valid(raise_exception=True)
          d = ser.validated_data

          WorkerHeartbeat.objects.update_or_create(
              worker_id=d['worker_id'],
              defaults=dict(
                  engine=d['engine'],
                  status_message=d['status_message'],
                  last_seen=timezone.now(),
              ),
          )
          _touch_key(request)
          return Response({'status': 'ok'})


  class QueueStatusView(APIView):
      permission_classes = [HasAPIKey]

      def get(self, request):
          from django.db.models import Count
          counts = (
              AnalysisJob.objects
              .values('engine', 'status')
              .annotate(count=Count('id'))
              .order_by('engine', 'status')
          )
          _touch_key(request)
          return Response({'queue': list(counts)})

After writing this file, run `bandit -ll api/views.py` and fix any
Medium/High findings.

════════════════════════════════════════════════════════════
STEP 10 — URL ROUTING  (api/urls.py + project urls.py)
════════════════════════════════════════════════════════════

Create api/urls.py:

  from django.urls import path
  from . import views

  urlpatterns = [
      path('health/',                  views.HealthView.as_view()),
      path('jobs/checkout/',           views.JobCheckoutView.as_view()),
      path('jobs/<int:job_id>/complete/', views.JobCompleteView.as_view()),
      path('jobs/<int:job_id>/fail/',     views.JobFailView.as_view()),
      path('jobs/status/',             views.QueueStatusView.as_view()),
      path('heartbeat/',               views.HeartbeatView.as_view()),
  ]

In the project's urls.py, add:

  from django.urls import include, path

  urlpatterns = [
      ...existing patterns...,
      path('api/v1/', include('api.urls')),
  ]

════════════════════════════════════════════════════════════
STEP 11 — ADMIN UI FOR KEY MANAGEMENT
════════════════════════════════════════════════════════════

This is a standard Django view (not DRF), gated by staff login,
styled with Tailwind v4 to match /admin/analysis-status/.

Create api/admin_views.py:

  from django.contrib.auth.decorators import login_required, user_passes_test
  from django.shortcuts import get_object_or_404, redirect, render
  from django.utils import timezone
  from django.views.decorators.http import require_POST
  from rest_framework_api_key.models import APIKey
  from .models import WorkerAPIKey

  _staff_required = user_passes_test(lambda u: u.is_staff, login_url='/auth/login/')

  @login_required
  @_staff_required
  def api_keys_list(request):
      keys = WorkerAPIKey.objects.select_related('created_by').order_by('-created')
      context = {'keys': keys, 'new_key': None}
      if request.htmx:
          return render(request, '_partials/admin/api_keys/list.html', context)
      return render(request, 'admin/api_keys/index.html', context)

  @login_required
  @_staff_required
  @require_POST
  def api_keys_issue(request):
      worker_name = request.POST.get('worker_name', '').strip()
      notes       = request.POST.get('notes', '').strip()
      if not worker_name:
          # Return form with error via HTMX
          return render(request, '_partials/admin/api_keys/issue_form.html',
                        {'error': 'Worker name is required.'})

      api_key, raw_key = WorkerAPIKey.objects.create_key(
          name=worker_name,
          worker_name=worker_name,
          created_by=request.user,
          notes=notes,
      )
      # raw_key is shown ONCE — render it in a modal partial
      context = {
          'raw_key': raw_key,
          'key': api_key,
      }
      return render(request, '_partials/admin/api_keys/key_created.html', context)

  @login_required
  @_staff_required
  @require_POST
  def api_keys_revoke(request, key_id):
      key = get_object_or_404(WorkerAPIKey, pk=key_id)
      key.revoked = True
      key.save(update_fields=['revoked'])
      # Return updated table row via HTMX swap
      return render(request, '_partials/admin/api_keys/table_row.html', {'key': key})

Add to api/urls.py (these are session-auth views, not DRF):

  from django.urls import path
  from . import admin_views

  # Append to urlpatterns:
  path('admin/api-keys/',                admin_views.api_keys_list,   name='api-keys-list'),
  path('admin/api-keys/issue/',          admin_views.api_keys_issue,  name='api-keys-issue'),
  path('admin/api-keys/<int:key_id>/revoke/', admin_views.api_keys_revoke, name='api-keys-revoke'),
  path('_partials/admin/api-keys/list/', admin_views.api_keys_list,   name='api-keys-list-partial'),

NOTE: The admin UI routes (/admin/api-keys/...) are NOT under /api/v1/
and ARE protected by LoginRequiredMiddleware (session auth). Only the
/api/v1/ prefix is exempted from session auth.

Templates to create (match the Tailwind v4 styling of
templates/admin/analysis_status.html exactly — same nav, same card
components, same colour palette):

  api/templates/admin/api_keys/index.html
    Full page. Table of keys with columns:
      Worker Name | Key Prefix | Created By | Created | Last Used | Status | Actions
    "Issue New Key" button triggers HTMX modal (hx-get the issue form partial,
    hx-target="#modal", hx-swap="innerHTML").
    Add "API Keys" link to the existing admin nav alongside "Analysis Status"
    and "Members".

  api/templates/_partials/admin/api_keys/list.html
    Table body only — used for HTMX refresh after issue/revoke.

  api/templates/_partials/admin/api_keys/issue_form.html
    Form partial: worker_name (required), notes (optional).
    hx-post to /admin/api-keys/issue/, hx-target="#modal".

  api/templates/_partials/admin/api_keys/key_created.html
    Shows the raw key in a styled box with a copy-to-clipboard button.
    Bold warning: "This key will not be shown again."
    "I have saved this key" button closes the modal and triggers
    hx-get="/_partials/admin/api-keys/list/" to refresh the table.

  api/templates/_partials/admin/api_keys/table_row.html
    Single <tr> for HTMX out-of-band swap after revoke.

════════════════════════════════════════════════════════════
STEP 12 — TESTS  (api/tests/)
════════════════════════════════════════════════════════════

Create api/tests/__init__.py and the following test files.
Use Django's TestCase for unit tests and TransactionTestCase only where
you need real transaction isolation (concurrency tests).

api/tests/test_auth.py
  • Missing X-Api-Key header → 403
  • Invalid key → 403
  • Revoked key → 403
  • Valid key → 200 on /api/v1/health/ (no auth) and /api/v1/jobs/status/
  • last_used_at is updated on every authenticated request

api/tests/test_checkout.py
  • Claims pending jobs in priority order (higher priority first, then FIFO)
  • Stale recovery: a job running for > STALE_JOB_TIMEOUT_MINUTES is reset
    to pending before the next checkout
  • batch_size=2 claims exactly 2 jobs
  • batch_size > pending count returns only what is available
  • Wrong engine returns empty list, not an error
  • Claimed job has correct worker_id and claimed_by_key_prefix

api/tests/test_complete.py
  • Stockfish payload writes GameAnalysis + MoveAnalysis rows
  • Lc0 payload writes Lc0GameAnalysis + Lc0MoveAnalysis rows
  • Ownership enforced: wrong worker_id → 404
  • Ownership enforced: wrong key_prefix → 404
  • Duplicate completion (job already 'completed') → 404
  • Job status set to 'completed' after successful submission

api/tests/test_fail.py
  • retry_count incremented on each failure
  • Job requeued (status='pending') when retry_count < MAX_JOB_RETRIES
  • Job marked 'failed' when retry_count reaches MAX_JOB_RETRIES
  • Ownership enforced: wrong worker_id → 404

api/tests/test_services.py
  • Unit tests for recover_stale_jobs: only resets jobs older than timeout
  • Unit tests for claim_jobs: returns correct jobs, sets all fields
  • Unit tests for fail_job: returns 'requeued' or 'failed' correctly

api/tests/test_admin_views.py
  • Non-staff user → 302 redirect on all /admin/api-keys/ routes
  • Staff user can GET /admin/api-keys/
  • Staff user can POST /admin/api-keys/issue/ → raw key in response
  • Staff user can POST /admin/api-keys/<id>/revoke/ → key.revoked=True
  • Raw key is NOT stored in the database (only the hash is)

════════════════════════════════════════════════════════════
STEP 13 — README UPDATE
════════════════════════════════════════════════════════════

Append a "## Worker API" section to README.md documenting:

  ### Authentication
  All /api/v1/ endpoints (except /api/v1/health/) require:
    X-Api-Key: <your-key>
  Keys are issued via the admin UI at /admin/api-keys/ (staff login required).

  ### Endpoints

  | Method | Path | Auth | Description |
  |--------|------|------|-------------|
  | GET  | /api/v1/health/                  | None  | Health check |
  | POST | /api/v1/jobs/checkout/           | Key   | Claim pending jobs |
  | POST | /api/v1/jobs/<id>/complete/      | Key   | Submit analysis results |
  | POST | /api/v1/jobs/<id>/fail/          | Key   | Report worker error |
  | POST | /api/v1/heartbeat/               | Key   | Worker liveness ping |
  | GET  | /api/v1/jobs/status/             | Key   | Queue counts |

  ### Checkout request
  {
    "engine": "stockfish",   // or "lc0"
    "batch_size": 1,         // 1–10
    "worker_id": "my-worker-id"
  }

  ### Checkout response
  {
    "jobs": [
      {
        "id": 42,
        "game_id": "abc123",
        "pgn": "1. e4 e5 ...",
        "engine": "stockfish",
        "depth": 20,
        "nodes": null
      }
    ]
  }
  Workers MUST honour the depth (Stockfish) and nodes (Lc0) values
  returned per job.

  ### Fault tolerance contract
  • A job not returned within STALE_JOB_TIMEOUT_MINUTES (default 15) is
    automatically requeued on the next checkout call.
  • Workers should call /fail/ on error to trigger immediate requeue.
  • Jobs are retried up to MAX_JOB_RETRIES (default 3) times before being
    marked failed.
  • /complete/ and /fail/ enforce ownership: the worker_id in the request
    body must match the worker that claimed the job.

  ### New environment variables
  STALE_JOB_TIMEOUT_MINUTES   No   15   Minutes before a running job is requeued
  MAX_JOB_RETRIES             No    3   Max attempts before a job is marked failed

════════════════════════════════════════════════════════════
STEP 14 — FINAL CHECKLIST
════════════════════════════════════════════════════════════

Before handing back, verify every item:

  [ ] `python manage.py migrate` runs cleanly (no errors)
  [ ] `python manage.py test api analysis` — all tests pass
  [ ] `bandit -ll` clean on every new/modified .py file
  [ ] /api/v1/health/ returns 200 without a key
  [ ] /api/v1/jobs/status/ returns 403 without a key
  [ ] /admin/api-keys/ returns 302 for anonymous, 200 for staff
  [ ] Issuing a key via the UI shows the raw key exactly once
  [ ] Revoking a key via the UI causes subsequent API calls to return 403
  [ ] Existing pages (/, /games/, /admin/analysis-status/) still work
  [ ] LoginRequiredMiddleware still blocks unauthenticated access to all
      non-API, non-auth routes
  [ ] No raw SQL strings anywhere in new code (ORM only)
  [ ] No API keys or secrets logged (only the 8-char prefix)
  [ ] requirements.txt updated with new packages
  [ ] README "Worker API" section added

════════════════════════════════════════════════════════════
FILE TREE OF NEW/MODIFIED FILES
════════════════════════════════════════════════════════════

New files:
  api/
  ├── __init__.py
  ├── admin_views.py
  ├── models.py              ← WorkerAPIKey
  ├── serializers.py
  ├── urls.py
  ├── views.py
  ├── migrations/
  │   └── 0001_initial.py    ← WorkerAPIKey table only
  ├── templates/
  │   ├── admin/api_keys/
  │   │   └── index.html
  │   └── _partials/admin/api_keys/
  │       ├── list.html
  │       ├── issue_form.html
  │       ├── key_created.html
  │       └── table_row.html
  └── tests/
      ├── __init__.py
      ├── test_auth.py
      ├── test_checkout.py
      ├── test_complete.py
      ├── test_fail.py
      ├── test_services.py
      └── test_admin_views.py

  analysis/services/
  ├── __init__.py
  └── jobs.py                ← extracted + shared service layer

Modified files:
  analysis/models.py         ← +claimed_by_key_prefix, +claimed_at, +nodes
  analysis/migrations/       ← new additive migration (AddField only)
  ingest/management/commands/run_analysis_worker.py  ← calls services.jobs
  ingest/management/commands/run_lc0_worker.py       ← calls services.jobs
  <project>/settings.py      ← REST_FRAMEWORK, API_KEY_CUSTOM_HEADER,
                                STALE_JOB_TIMEOUT_MINUTES, MAX_JOB_RETRIES
  <project>/urls.py          ← path('api/v1/', include('api.urls'))
  accounts/middleware.py     ← exempt /api/v1/ from session auth
  requirements.txt           ← +djangorestframework, +djangorestframework-api-key
  README.md                  ← Worker API section
