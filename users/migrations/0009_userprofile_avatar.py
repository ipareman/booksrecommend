from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_rename_users_userb_user_id_bd61db_idx_users_userb_user_id_89c6e6_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="avatar",
            field=models.ImageField(blank=True, null=True, upload_to="avatars/"),
        ),
    ]
