import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0005_moodtag_bookmood"),
    ]

    operations = [
        migrations.AddField(
            model_name="quote",
            name="is_ai_generated",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="quote",
            name="mood_tag",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="quotes",
                to="books.moodtag",
            ),
        ),
    ]
