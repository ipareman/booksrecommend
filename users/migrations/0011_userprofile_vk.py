from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0010_userprofile_avatar_gradient"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="vk_username",
            field=models.CharField(
                blank=True,
                help_text="Короткое имя VK без @, например: id123 или ivan_petrov",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="vk_user_id",
            field=models.CharField(
                blank=True,
                help_text="Заполняется автоматически после /start VK-боту",
                max_length=50,
            ),
        ),
    ]
