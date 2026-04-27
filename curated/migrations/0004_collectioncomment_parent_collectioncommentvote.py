# Generated manually for threaded collection comments and votes.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("curated", "0003_collectioncomment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="collectioncomment",
            name="parent",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="replies", to="curated.collectioncomment"),
        ),
        migrations.CreateModel(
            name="CollectionCommentVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.SmallIntegerField(choices=[(1, "+1"), (-1, "-1")])),
                ("comment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="curated.collectioncomment")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="collection_comment_votes", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="collectioncommentvote",
            constraint=models.UniqueConstraint(fields=("user", "comment"), name="collection_comment_vote_unique"),
        ),
    ]
