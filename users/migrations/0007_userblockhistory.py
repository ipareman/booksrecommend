from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_userprofile_max"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserBlockHistory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField(blank=True, help_text="Причина блокировки")),
                ("blocked_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("blocked_until", models.DateTimeField(blank=True, help_text="Когда блокировка истекает (пусто = бессрочно)", null=True)),
                ("unblocked_at", models.DateTimeField(blank=True, help_text="Когда был разблокирован досрочно", null=True)),
                ("unblock_reason", models.TextField(blank=True, help_text="Причина досрочной разблокировки")),
                ("blocked_by", models.ForeignKey(
                    blank=True, help_text="Администратор, наложивший блокировку",
                    null=True, on_delete=models.deletion.SET_NULL,
                    related_name="block_actions_performed",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("unblocked_by", models.ForeignKey(
                    blank=True, null=True, on_delete=models.deletion.SET_NULL,
                    related_name="unblock_actions_performed",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    help_text="Кого заблокировали",
                    on_delete=models.deletion.CASCADE,
                    related_name="block_history",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-blocked_at"],
            },
        ),
        migrations.AddIndex(
            model_name="userblockhistory",
            index=models.Index(fields=["user", "-blocked_at"], name="users_userb_user_id_bd61db_idx"),
        ),
        migrations.AddIndex(
            model_name="userblockhistory",
            index=models.Index(fields=["-blocked_at"], name="users_userb_blocked_76826b_idx"),
        ),
    ]
