from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_alter_achievement_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="max_username",
            field=models.CharField(
                blank=True,
                help_text="Логин MAX без @, например: ivan_petrov",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="max_user_id",
            field=models.CharField(
                blank=True,
                help_text="Заполняется автоматически после /start MAX-боту",
                max_length=50,
            ),
        ),
    ]
