from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0006_repair_room_type_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="voice_message",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="voice_messages/",
                help_text="Голосовое сообщение (WebM/OGG аудио)",
            ),
        ),
    ]
