from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0003_discoverychatmessage_books_meta"),
    ]

    operations = [
        migrations.AddField(
            model_name="discoverychatmessage",
            name="followup_options",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="discoverychatmessage",
            name="disliked_book_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
