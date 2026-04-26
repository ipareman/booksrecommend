# ChatMessageReaction — emoji-реакция на сообщение.
# Один пользователь × emoji × сообщение — уникальный ключ (toggle on/off).
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_chatmessage_attached_book_alter_chatmessage_body"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatMessageReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("emoji", models.CharField(max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reactions", to="chat.chatmessage")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="chatmessagereaction",
            index=models.Index(fields=["message", "emoji"], name="chat_chatme_message_145bc2_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="chatmessagereaction",
            unique_together={("message", "user", "emoji")},
        ),
    ]
