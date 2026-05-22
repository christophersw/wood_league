# Generated for issue #197 — retire legacy SF arrow_score_* (sigmoid Win%) columns.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0002_add_arrow_cp'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='moveanalysis',
            name='arrow_score_1',
        ),
        migrations.RemoveField(
            model_name='moveanalysis',
            name='arrow_score_2',
        ),
        migrations.RemoveField(
            model_name='moveanalysis',
            name='arrow_score_3',
        ),
    ]
