from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0004_alter_booktag_id"),
    ]

    operations = [
        migrations.CreateModel(
            name="MoodTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=50, unique=True)),
                ("category", models.CharField(
                    choices=[
                        ("atmosphere", "Атмосфера"),
                        ("pace", "Темп"),
                        ("emotion", "Эмоция"),
                        ("complexity", "Сложность"),
                    ],
                    max_length=20,
                )),
                ("icon", models.CharField(blank=True, max_length=10)),
            ],
            options={
                "ordering": ["category", "name"],
            },
        ),
        migrations.CreateModel(
            name="BookMood",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("confidence", models.FloatField(default=1.0)),
                ("source", models.CharField(default="ai", max_length=20)),
                ("vote_count", models.PositiveIntegerField(default=0)),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="moods", to="books.book")),
                ("mood", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="book_moods", to="books.moodtag")),
            ],
        ),
        migrations.AddConstraint(
            model_name="bookmood",
            constraint=models.UniqueConstraint(fields=("book", "mood"), name="bookmood_unique"),
        ),
    ]
