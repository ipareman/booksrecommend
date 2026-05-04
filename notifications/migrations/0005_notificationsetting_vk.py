from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_mentioned_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationsetting",
            name="channel_vk",
            field=models.BooleanField(default=True),
        ),
    ]
