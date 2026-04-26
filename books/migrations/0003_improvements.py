from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0002_booktag"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── UserList: sentiment_tag + is_public ──────────────────────────────
        migrations.AddField(
            model_name="userlist",
            name="sentiment_tag",
            field=models.CharField(
                max_length=20,
                default="neutral",
                db_index=True,
                choices=[
                    ("positive", "Нравится"),
                    ("negative", "Не нравится"),
                    ("neutral",  "Нейтральный"),
                    ("wishlist", "Хочу прочитать"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="userlist",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
        # ── ReadingProgress ──────────────────────────────────────────────────
        migrations.CreateModel(
            name="ReadingProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("current_page", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="reading_progress", to="books.book")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="reading_progress",
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.AddConstraint(
            model_name="readingprogress",
            constraint=models.UniqueConstraint(
                fields=["user", "book"], name="readingprogress_unique"
            ),
        ),
        # ── Quote ────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Quote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("text",        models.TextField()),
                ("page_number", models.PositiveIntegerField(null=True, blank=True)),
                ("created_at",  models.DateTimeField(auto_now_add=True)),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="quotes", to="books.book")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="quotes",
                                           to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        # ── PriceAlert ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name="PriceAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("threshold",    models.DecimalField(max_digits=10, decimal_places=2)),
                ("created_at",   models.DateTimeField(auto_now_add=True)),
                ("triggered_at", models.DateTimeField(null=True, blank=True)),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="price_alerts", to="books.book")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="price_alerts",
                                           to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="pricealert",
            constraint=models.UniqueConstraint(
                fields=["user", "book"], name="pricealert_unique"
            ),
        ),
    ]
