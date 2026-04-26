# Generated for ReadingProgress.mode

from django.db import migrations, models


def _set_default_mode(apps, schema_editor):
    """Для уже существующих прогрессов, у которых стоит current_chapter —
    считаем, что юзер читал через встроенную читалку (mode = reader);
    всех остальных оставляем на manual (default)."""
    ReadingProgress = apps.get_model("books", "ReadingProgress")
    ReadingProgress.objects.filter(current_chapter__isnull=False).update(mode="reader")


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0009_bookchapter_readingprogress_scroll_offset_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="readingprogress",
            name="mode",
            field=models.CharField(
                choices=[("manual", "Ручной ввод"), ("reader", "Синхронизация с читалкой")],
                default="manual",
                help_text="Как считать прогресс: ручной ввод или синхронизация с читалкой",
                max_length=10,
            ),
        ),
        migrations.RunPython(_set_default_mode, migrations.RunPython.noop),
    ]
