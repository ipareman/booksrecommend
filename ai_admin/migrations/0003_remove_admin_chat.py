from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_admin", "0002_aiconfig_provider_endpoint"),
    ]

    operations = [
        migrations.DeleteModel(name="AIAdminChatMessage"),
        migrations.DeleteModel(name="AIAdminChat"),
        migrations.AlterField(
            model_name="aiusagelog",
            name="feature",
            field=models.CharField(
                choices=[
                    ("discovery",       "Discovery chat"),
                    ("book_chat",       "Book chat"),
                    ("recommendations", "Recommendations"),
                    ("ai_search",       "AI search"),
                    ("tag",             "Tag extraction"),
                    ("mood",            "Mood classification"),
                    ("quotes",          "Smart quotes"),
                    ("sentiment",       "List sentiment"),
                    ("other",           "Other"),
                ],
                db_index=True,
                default="other",
                max_length=32,
            ),
        ),
    ]
