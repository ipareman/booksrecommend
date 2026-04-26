from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_achievement"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="email_verified",
            field=models.BooleanField(default=False),
        ),
    ]
