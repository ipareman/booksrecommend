# Generated manually for the tickets app.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("request", "Обращение"), ("report", "Жалоба")], db_index=True, max_length=16)),
                ("status", models.CharField(choices=[("open", "Открыт"), ("in_progress", "В работе"), ("answered", "Есть ответ"), ("closed", "Закрыт")], db_index=True, default="open", max_length=20)),
                ("priority", models.CharField(choices=[("normal", "Обычный"), ("high", "Важный")], db_index=True, default="normal", max_length=12)),
                ("subject", models.CharField(max_length=180)),
                ("body", models.TextField()),
                ("target_id", models.PositiveIntegerField(blank=True, null=True)),
                ("target_label", models.CharField(blank=True, max_length=240)),
                ("target_url", models.CharField(blank=True, max_length=500)),
                ("admin_response", models.TextField(blank=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("responded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_responses", to=settings.AUTH_USER_MODEL)),
                ("target_ct", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="contenttypes.contenttype")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tickets", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-updated_at"],
                "indexes": [
                    models.Index(fields=["kind", "status", "-updated_at"], name="tickets_tic_kind_8b0e1c_idx"),
                    models.Index(fields=["user", "-updated_at"], name="tickets_tic_user_id_4b6e8b_idx"),
                ],
            },
        ),
    ]
