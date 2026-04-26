from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
        ("books", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="onboarding_done",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="favorite_genres",
            field=models.ManyToManyField(
                blank=True,
                related_name="fans",
                to="books.genre",
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="favorite_authors",
            field=models.ManyToManyField(
                blank=True,
                related_name="fans",
                to="books.author",
            ),
        ),
    ]
