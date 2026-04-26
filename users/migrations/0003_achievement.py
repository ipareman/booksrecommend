from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("users", "0002_userprofile_onboarding"),
    ]

    operations = [
        migrations.CreateModel(
            name="Achievement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("achievement_type", models.CharField(
                    max_length=30,
                    choices=[
                        ("books_10", "Библиофил: 10 книг в списках"),
                        ("books_50", "Книжный червь: 50 книг в списках"),
                        ("reviews_5", "Критик: 5 отзывов"),
                        ("reviews_20", "Литературовед: 20 отзывов"),
                        ("pages_1000", "Марафонец: 1 000 страниц"),
                        ("pages_5000", "Книжный титан: 5 000 страниц"),
                        ("lists_3", "Коллекционер: 3 списка"),
                        ("subscriptions_5", "Фанат: 5 подписок на авторов"),
                    ],
                )),
                ("earned_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="achievements",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=["user", "achievement_type"],
                        name="achievement_unique",
                    )
                ],
            },
        ),
    ]
