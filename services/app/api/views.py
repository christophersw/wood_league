"""Views for the Analysis Worker API.

Provides endpoints for workers to checkout jobs, report completion,
report failures, send heartbeats, and query queue status.
"""
from django.db.models import Count
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from api.authentication import HasWorkerAPIKey

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

    def get(self, request):  # pylint: disable=unused-argument
        """Return health status."""
        return Response({'status': 'ok'})


class JobCheckoutView(APIView):
    """Checkout available analysis jobs."""

    permission_classes = [HasWorkerAPIKey]
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

    permission_classes = [HasWorkerAPIKey]
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

    permission_classes = [HasWorkerAPIKey]

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


class HeartbeatView(APIView):
    """Worker heartbeat status update."""

    permission_classes = [HasWorkerAPIKey]
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
                last_seen=timezone.now(),
            ),
        )
        _touch_key(request)
        return Response({'status': 'ok'})


class QueueStatusView(APIView):
    """Query the status of the analysis job queue."""

    permission_classes = [HasWorkerAPIKey]

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
