from django.db import migrations, models
import users.models
import random


GRADIENTS = [
    "orchid",
    "ember",
    "lagoon",
    "moss",
    "dawn",
    "ink",
    "berry",
    "gold",
]


def assign_gradients(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    for profile in UserProfile.objects.all().only("pk", "avatar_gradient"):
        profile.avatar_gradient = random.choice(GRADIENTS)
        profile.save(update_fields=["avatar_gradient"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_userprofile_avatar"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="avatar_gradient",
            field=models.CharField(
                choices=[
                    ("orchid", "Орхидея"),
                    ("ember", "Искра"),
                    ("lagoon", "Лагуна"),
                    ("moss", "Мох"),
                    ("dawn", "Рассвет"),
                    ("ink", "Чернила"),
                    ("berry", "Ягоды"),
                    ("gold", "Золото"),
                ],
                default=users.models.random_avatar_gradient,
                max_length=20,
            ),
        ),
        migrations.RunPython(assign_gradients, migrations.RunPython.noop),
    ]
