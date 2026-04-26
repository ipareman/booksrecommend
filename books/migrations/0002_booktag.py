from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="BookTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=80)),
                ("count", models.PositiveIntegerField(default=1)),
                ("book", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tags",
                    to="books.book",
                )),
            ],
            options={"ordering": ["-count"]},
        ),
        migrations.AddConstraint(
            model_name="booktag",
            constraint=models.UniqueConstraint(fields=["book", "name"], name="booktag_unique"),
        ),
    ]
