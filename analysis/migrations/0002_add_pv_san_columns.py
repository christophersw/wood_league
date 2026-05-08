"""
Title: 0002_add_pv_san_columns.py — Add pv_san continuation columns to move tables
Description:
    Adds pv_san_1, pv_san_2, pv_san_3 nullable Text columns to both move_analysis
    and lc0_move_analysis tables. These store the principal variation continuations
    from Stockfish and Lc0 analysis respectively.

Changelog:
    2026-05-05 (#1): Add pv_san_1/2/3 columns to keep schema in sync with RunPod workers
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="moveanalysis",
            name="pv_san_1",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="moveanalysis",
            name="pv_san_2",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="moveanalysis",
            name="pv_san_3",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="pv_san_1",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="pv_san_2",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lc0moveanalysis",
            name="pv_san_3",
            field=models.TextField(blank=True, null=True),
        ),
    ]
