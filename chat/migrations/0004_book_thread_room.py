# Generated manually for club book discussion threads.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clubs", "0002_private_club_features"),
        ("chat", "0003_chatmessagereaction"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chatroom",
            name="room_type",
            field=models.CharField(choices=[("dm", "Личные сообщения"), ("club", "Клубный чат"), ("club_thread", "Обсуждение книги в клубе")], default="dm", max_length=16),
        ),
        migrations.CreateModel(
            name="ClubBookThread",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("club_book", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="thread_link", to="clubs.clubbook")),
                ("room", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="club_book_thread", to="chat.chatroom")),
            ],
        ),
    ]
