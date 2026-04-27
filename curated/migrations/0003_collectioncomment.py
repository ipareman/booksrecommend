# Generated manually for collection comments.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("curated", "0002_collectionlike"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CollectionComment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("collection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comments", to="curated.collection")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="collection_comments", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(fields=["collection", "created_at"], name="curated_col_collect_f521c3_idx"),
                ],
            },
        ),
    ]
