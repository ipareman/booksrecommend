"""
Начальная миграция analytics:
- StoreClick (клики по ссылкам магазинов)
- ModerationLog (журнал действий админов)
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("books", "0008_bookedition_book_edition_group"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StoreClick",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("session_key", models.CharField(blank=True, db_index=True, max_length=40,
                                                 help_text="Для дедупликации кликов анонимов в пределах сессии.")),
                ("referer", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("book",  models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name="store_clicks", to="books.book")),
                ("store", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name="clicks",       to="books.store")),
                ("user",  models.ForeignKey(blank=True, null=True,
                                            on_delete=django.db.models.deletion.SET_NULL,
                                            related_name="store_clicks",
                                            to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="storeclick",
            index=models.Index(fields=["-created_at", "store"], name="analytics_s_created_st_idx"),
        ),
        migrations.AddIndex(
            model_name="storeclick",
            index=models.Index(fields=["-created_at", "book"], name="analytics_s_created_bk_idx"),
        ),

        migrations.CreateModel(
            name="ModerationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("action",      models.CharField(
                    max_length=32, db_index=True,
                    choices=[
                        ("review_approve",    "Отзыв одобрен"),
                        ("review_reject",     "Отзыв отклонён"),
                        ("critique_approve",  "Рецензия одобрена"),
                        ("critique_reject",   "Рецензия отклонена"),
                        ("user_block",        "Пользователь заблокирован"),
                        ("user_unblock",      "Пользователь разблокирован"),
                        ("store_save",        "Магазин сохранён"),
                        ("store_delete",      "Магазин удалён"),
                        ("book_delete",       "Книга удалена"),
                        ("other",             "Иное"),
                    ],
                )),
                ("target_type", models.CharField(blank=True, max_length=32,
                                                 help_text="Название модели цели (review / critique / user / store / book).")),
                ("target_id",   models.IntegerField(blank=True, null=True)),
                ("target_repr", models.CharField(blank=True, max_length=250,
                                                 help_text="Человекочитаемое представление цели на момент действия.")),
                ("note",        models.CharField(blank=True, max_length=500,
                                                 help_text="Комментарий (причина отклонения и т.п.).")),
                ("created_at",  models.DateTimeField(auto_now_add=True, db_index=True)),
                ("moderator",   models.ForeignKey(null=True,
                                                  on_delete=django.db.models.deletion.SET_NULL,
                                                  related_name="+",
                                                  to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="moderationlog",
            index=models.Index(fields=["-created_at", "action"], name="analytics_m_created_ac_idx"),
        ),
    ]
