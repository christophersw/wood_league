"""
Title: 0011_lc0_wdl_calibration.py — Add Lc0 WDL calibration columns
Description:
    Adds WDL calibration metadata columns to Lc0GameAnalysis and Lc0MoveAnalysis
    as required by issue #159 (D3).

    Lc0GameAnalysis gains three new nullable columns:
        draw_rate_reference  — population draw-rate used to rescale WDL triples
        wdl_calibration_elo  — Elo at which draw_rate_reference was looked up
        contempt             — Lc0 contempt setting at time of analysis

    Lc0MoveAnalysis gains seven new nullable columns (rescaled WDL, mu, deltas):
        wdl_win_adj / wdl_draw_adj / wdl_loss_adj
        wdl_mu / delta_mu / delta_d
        base_severity  — replaces the old classification label for Lc0 moves
        draw_character — optional draw-character annotation (NULL for most moves)

    The old `classification` column (NULL-able, no data for Lc0 beyond legacy
    placeholder values) is dropped.  Existing rows will have NULL for all new
    columns, which is safe because all new fields are NULL-able.

Changelog:
    2026-05-19 (#159/D3): Initial migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add WDL calibration columns to Lc0 analysis tables; drop old classification."""

    dependencies = [
        ("analysis", "0010_recurringanalysisschedule_and_more"),
    ]

    operations = [
        # ── Lc0GameAnalysis: calibration metadata ────────────────────────────
        migrations.AddField(
            model_name="lc0gameanalysis",
            name="draw_rate_reference",
            field=models.FloatField(
                blank=True,
                help_text="Population draw-rate used to rescale WDL triples (0.001–0.999).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="lc0gameanalysis",
            name="wdl_calibration_elo",
            field=models.IntegerField(
                blank=True,
                help_text="Elo at which draw_rate_reference was looked up.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="lc0gameanalysis",
            name="contempt",
            field=models.IntegerField(
                blank=True,
                help_text="Lc0 contempt setting at time of analysis (signed integer; 0 = neutral).",
                null=True,
            ),
        ),
        # ── Lc0MoveAnalysis: rescaled WDL triple ─────────────────────────────
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="wdl_win_adj",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="wdl_draw_adj",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="wdl_loss_adj",
            field=models.IntegerField(blank=True, null=True),
        ),
        # ── Lc0MoveAnalysis: expected-score and delta metrics ─────────────────
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="wdl_mu",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="delta_mu",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="delta_d",
            field=models.FloatField(blank=True, null=True),
        ),
        # ── Lc0MoveAnalysis: severity labels (replace classification) ─────────
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="base_severity",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="draw_character",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        # Drop the old classification column (nullable; no meaningful Lc0 data)
        migrations.RemoveField(
            model_name="lc0moveanalysis",
            name="classification",
        ),
    ]
