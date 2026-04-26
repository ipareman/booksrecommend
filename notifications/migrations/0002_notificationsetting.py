"""Матрица настроек рассылки: события × каналы (TG/MAX/email)."""

from django.db import migrations, models


EVENT_CHOICES = [
    ("new_book",          "Новая книга у подписного автора"),
    ("price_alert",       "Алерт о снижении цены"),
    ("review_approved",   "Отзыв одобрен"),
    ("review_rejected",   "Отзыв отклонён"),
    ("critique_approved", "Рецензия одобрена"),
    ("critique_rejected", "Рецензия отклонена"),
    ("weekly_digest",     "Еженедельный дайджест"),
]


def seed_settings(apps, schema_editor):
    NotificationSetting = apps.get_model("notifications", "NotificationSetting")
    for event, _label in EVENT_CHOICES:
        NotificationSetting.objects.get_or_create(
            event=event,
            defaults={
                "channel_telegram": True,
                "channel_max": True,
                "channel_email": True,
            },
        )


def unseed_settings(apps, schema_editor):
    NotificationSetting = apps.get_model("notifications", "NotificationSetting")
    NotificationSetting.objects.filter(event__in=[e for e, _ in EVENT_CHOICES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("event", models.CharField(max_length=32, unique=True,
                                           choices=EVENT_CHOICES)),
                ("channel_telegram", models.BooleanField(default=True)),
                ("channel_max",      models.BooleanField(default=True)),
                ("channel_email",    models.BooleanField(default=True)),
                ("updated_at",       models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["event"],
                "verbose_name": "Настройка рассылки",
                "verbose_name_plural": "Настройки рассылок",
            },
        ),
        migrations.RunPython(seed_settings, reverse_code=unseed_settings),
    ]
