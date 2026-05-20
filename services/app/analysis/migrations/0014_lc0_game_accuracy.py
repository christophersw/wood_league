"""
Title: 0014_lc0_game_accuracy.py — Per-side Lc0 game accuracy %
Description:
    Issue #164. Adds nullable ``white_accuracy`` and ``black_accuracy``
    floats to ``Lc0GameAnalysis``. Additive-only: no data destruction.
    Existing rows have NULL until the next analysis pass populates them
    from ``derivation.lc0.derive_lc0_game``.
Changelog:
    2026-05-20: Initial (#164).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0013_rebuild_analysis_tables'),
    ]

    operations = [
        migrations.AddField(
            model_name='lc0gameanalysis',
            name='black_accuracy',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='lc0gameanalysis',
            name='white_accuracy',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
