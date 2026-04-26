# Notifications — первая миграция.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("new_message",        "Новое сообщение"),
                            ("new_book_by_author", "Новая книга у автора"),
                            ("friend_request",     "Заявка в друзья"),
                            ("friend_accepted",    "Заявка принята"),
                            ("book_recommended",   "Рекомендация книги"),
                            ("review_moderated",   "Отзыв/рецензия: модерация"),
                            ("critique_comment",   "Комментарий к рецензии"),
                            ("critique_reply",     "Ответ на комментарий"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("target_id", models.PositiveIntegerField(blank=True, null=True)),
                ("text",  models.CharField(blank=True, max_length=300)),
                ("url",   models.CharField(blank=True, max_length=500)),
                ("extra", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("read_at",    models.DateTimeField(blank=True, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notifications_authored",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "target_ct",
                    models.ForeignKey(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
                "indexes": [
                    models.Index(fields=["user", "read_at", "-updated_at"], name="notificatio_user_id_0d11d6_idx"),
                    models.Index(fields=["user", "kind"],                   name="notificatio_user_id_7b7033_idx"),
                ],
            },
        ),
    ]
