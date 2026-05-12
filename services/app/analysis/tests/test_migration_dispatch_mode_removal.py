"""
Title: test_migration_dispatch_mode_removal.py — Migration data-preservation test
Description: Asserts that analysis migration 0006 (which drops the
    ``dispatch_mode`` column from ``AnalysisJob``) does not lose row data.
    Walks the test database back to 0005, inserts a known number of rows
    with ``dispatch_mode`` set, migrates forward to 0006, and verifies the
    row count is unchanged. After running, the database is migrated to the
    latest leaf so subsequent tests see the current schema.
Changelog:
    2026-05-11: Initial — issue #16.
"""
import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class DispatchModeRemovalPreservesRowsTests(TransactionTestCase):
    """Migration 0006 must drop ``dispatch_mode`` without losing any rows."""

    def _migrate(self, targets):
        """Run MigrationExecutor.migrate against a fresh executor each call.

        Args:
            targets: List of ``(app_label, migration_name)`` tuples passed to
                MigrationExecutor.migrate.

        Returns:
            MigrationExecutor: The executor after migration completes (useful
                for retrieving the historical project state).
        """
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        executor.loader.build_graph()
        return executor

    def test_remove_dispatch_mode_preserves_row_count(self):
        """Row count is identical before and after the dispatch_mode drop.

        Migrates the schema back to analysis 0005 (where ``dispatch_mode``
        still exists), inserts a known set of rows using the historical
        model, then migrates forward to 0006 and asserts the row count is
        unchanged.
        """
        pre_state = ("analysis", "0005_analysisjob_last_error_analysisjob_last_error_at")
        post_state = ("analysis", "0006_remove_analysisjob_analysis_jo_status_0bfd78_idx_and_more")

        executor = self._migrate([pre_state])
        historical_apps = executor.loader.project_state([pre_state]).apps
        HistoricalGame = historical_apps.get_model("games", "Game")
        HistoricalAnalysisJob = historical_apps.get_model("analysis", "AnalysisJob")

        # Confirm we are in the pre-migration world: the column still exists.
        self.assertIn(
            "dispatch_mode",
            {f.name for f in HistoricalAnalysisJob._meta.get_fields()},
            "Test setup error: dispatch_mode missing at migration 0005",
        )

        row_count = 5
        for index in range(row_count):
            game = HistoricalGame.objects.create(
                id=f"mig-{uuid.uuid4().hex[:8]}-{index}",
                played_at=timezone.now(),
                time_control="600",
                pgn="*",
            )
            HistoricalAnalysisJob.objects.create(
                game=game,
                engine="stockfish",
                status="pending",
                depth=20,
                # Alternate the soon-to-be-dropped column so we know data was
                # actually present prior to the migration.
                dispatch_mode="runpod" if index % 2 == 0 else "pull",
            )

        pre_count = HistoricalAnalysisJob.objects.count()
        self.assertEqual(pre_count, row_count)

        # Apply 0006 — drops the dispatch_mode column.
        self._migrate([post_state])
        post_apps = MigrationExecutor(connection).loader.project_state(
            [post_state]
        ).apps
        AnalysisJobAfter = post_apps.get_model("analysis", "AnalysisJob")

        self.assertNotIn(
            "dispatch_mode",
            {f.name for f in AnalysisJobAfter._meta.get_fields()},
            "Migration 0006 did not actually drop dispatch_mode",
        )

        post_count = AnalysisJobAfter.objects.count()
        self.assertEqual(
            post_count, pre_count,
            f"Row count changed across dispatch_mode drop: "
            f"{pre_count} before, {post_count} after",
        )

    def tearDown(self):
        """Roll the schema forward to the leaf migrations so later tests see the current schema."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)
        super().tearDown()
