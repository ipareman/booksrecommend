from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_admin", "0005_aiconfig_dry_run_mode_alter_aiusagelog_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiconfig",
            name="require_email_verification",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Если выключено — регистрация активирует аккаунт сразу, "
                    "без письма-подтверждения."
                ),
            ),
        ),
    ]
