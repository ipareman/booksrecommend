from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="extracted_tag",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Тег, извлечённый Claude из этого отзыва",
                max_length=80,
            ),
        ),
    ]
