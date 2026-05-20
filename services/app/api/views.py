"""
Title: views.py — Analysis Worker API endpoints
Description:
    REST API views for Stockfish and Lc0 workers to checkout analysis jobs,
    report job completion with move analysis results, report job failures,
    send periodic heartbeats, and query queue status. All endpoints require
    API key authentication.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-08: Added JobSubmitView for RunPod dispatcher integration
    2026-05-10: Removed dispatch_mode kwarg from claim_jobs call in JobCheckoutView
    2026-05-17 (#128): HeartbeatView.post persists batch_total, batch_processed, session_started_at
"""
from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from api.authentication import HasWorkerAPIKey

from analysis.models import AnalysisJob, NetworkCalibration, WorkerHeartbeat
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

    permission_classes: list[type] = []

    def get(self, request):  # pylint: disable=unused-argument
        """Return health status."""
        return Response({'status': 'ok'})


class JobCheckoutView(APIView):
    """Checkout available analysis jobs."""

    permission_classes: list[type] = [HasWorkerAPIKey]
    throttle_scope = 'checkout'

    def post(self, request):
        """Process job checkout request."""
        ser = sz.CheckoutRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        try:
            claimed = job_service.claim_jobs(
                engine=d['engine'],
                batch_size=d['batch_size'],
                worker_id=d['worker_id'],
                key_prefix=_key_prefix(request),
                game_id=d.get('game_id'),
                network_name=d.get('network_name', ''),
            )
        except job_service.NeedsCalibration as exc:
            return Response(
                {
                    'error': 'NEEDS_CALIBRATION',
                    'network_name': exc.network_name,
                    'settings_hash': exc.settings_hash,
                    'sampler_settings': exc.sampler_settings,
                    'sampler_version': exc.sampler_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except job_service.JobCheckoutDenied as exc:
            return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
        _touch_key(request)
        return Response(
            {'jobs': sz.JobSerializer(claimed, many=True).data},
            status=status.HTTP_200_OK,
        )


class JobCompleteView(APIView):
    """Report completion of an analysis job."""

    permission_classes: list[type] = [HasWorkerAPIKey]
    throttle_scope = 'complete'

    def post(self, request, job_id):
        """Process job completion request."""
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
    """Report failure of an analysis job."""

    permission_classes: list[type] = [HasWorkerAPIKey]

    def post(self, request, job_id):
        """Process job failure request."""
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


class JobSubmitView(APIView):
    """Record that a RunPod job has been submitted."""

    permission_classes: list[type] = [HasWorkerAPIKey]

    def post(self, request, job_id):
        """Process RunPod job submission record.

        Parameters:
            request: DRF request with runpod_job_id in body.
            job_id: Primary key of the AnalysisJob to mark submitted.

        Returns:
            Response with status='submitted' on success, or 404 if the job
            is not found or not in pending state.
        """
        ser = sz.JobSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            job_service.submit_job(
                job_id=job_id,
                runpod_job_id=ser.validated_data['runpod_job_id'],
            )
        except AnalysisJob.DoesNotExist:
            return Response(
                {'error': 'Job not found or not in pending state'},
                status=status.HTTP_404_NOT_FOUND,
            )
        _touch_key(request)
        return Response({'status': 'submitted'})


class HeartbeatView(APIView):
    """Worker heartbeat status update."""

    permission_classes: list[type] = [HasWorkerAPIKey]
    throttle_scope = 'heartbeat'

    def post(self, request):
        """Process heartbeat update."""
        ser = sz.HeartbeatSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        WorkerHeartbeat.objects.update_or_create(
            worker_id=d['worker_id'],
            defaults=dict(
                engine=d['engine'],
                status_message=d['status_message'],
                batch_total=d['batch_total'],
                batch_processed=d['batch_processed'],
                session_started_at=d['session_started_at'],
                last_seen=timezone.now(),
            ),
        )
        _touch_key(request)
        return Response({'status': 'ok'})


class QueueStatusView(APIView):
    """Query the status of the analysis job queue."""

    permission_classes: list[type] = [HasWorkerAPIKey]

    def get(self, request):  # pylint: disable=unused-argument
        """Return queue statistics by engine and status."""
        counts = (
            AnalysisJob.objects
            .values('engine', 'status')
            .annotate(count=Count('id'))
            .order_by('engine', 'status')
        )
        _touch_key(request)
        return Response({'queue': list(counts)})


class NetworkCalibrationView(APIView):
    """POST /api/v1/network_calibrations/ — record an lc0 draw-rate measurement.

    Phase A of issue #161. The endpoint is idempotent on
    ``(network_name, settings_hash)``: the first writer creates the row and
    receives 201; later writers with the same key receive 200 and the row is
    untouched. This lets multiple workers race the same calibration without
    corrupting state — the loser simply re-fetches the canonical value on
    its next checkout.
    """

    permission_classes: list[type] = [HasWorkerAPIKey]
    throttle_scope = "complete"

    def post(self, request):
        """Validate the payload and upsert a NetworkCalibration row.

        Returns:
            Response: 201 + ``{"created": True, ...}`` on first write;
                200 + ``{"created": False, ...}`` when the key already exists;
                400 with field errors on validation failure.
        """
        ser = sz.NetworkCalibrationSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        row, created = NetworkCalibration.objects.get_or_create(
            network_name=d["network_name"],
            settings_hash=d["settings_hash"],
            defaults=dict(
                draw_rate_reference=d["draw_rate_reference"],
                sample_size=d["sample_size"],
                sem=d["sem"],
                sampler_version=d["sampler_version"],
                submitted_by_worker_id=d["worker_id"],
            ),
        )
        _touch_key(request)
        body = {
            "created": created,
            "network_name": row.network_name,
            "settings_hash": row.settings_hash,
            "draw_rate_reference": row.draw_rate_reference,
            "sample_size": row.sample_size,
            "sem": row.sem,
            "sampler_version": row.sampler_version,
            "measured_at": row.measured_at.isoformat() if row.measured_at else None,
            "submitted_by_worker_id": row.submitted_by_worker_id,
        }
        return Response(
            body,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
