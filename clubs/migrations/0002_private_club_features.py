# Generated manually for club voting, polls and invite links.

import secrets

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_invite_tokens(apps, schema_editor):
    BookClub = apps.get_model("clubs", "BookClub")
    for club in BookClub.objects.filter(models.Q(invite_token="") | models.Q(invite_token__isnull=True)):
        club.invite_token = secrets.token_urlsafe(16)
        club.save(update_fields=["invite_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("clubs", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="bookclub",
            name="invite_token",
            field=models.CharField(blank=True, db_index=True, max_length=40, null=True, unique=True),
        ),
        migrations.RunPython(backfill_invite_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="bookclub",
            name="invite_token",
            field=models.CharField(blank=True, db_index=True, max_length=40, unique=True),
        ),
        migrations.CreateModel(
            name="ClubPoll",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=240)),
                ("is_closed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("club", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="polls", to="clubs.bookclub")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="club_polls_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ClubPollOption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.CharField(max_length=160)),
                ("order", models.PositiveIntegerField(default=0)),
                ("poll", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="options", to="clubs.clubpoll")),
            ],
            options={"ordering": ["order", "id"]},
        ),
        migrations.CreateModel(
            name="ClubBookVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("club", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="book_votes", to="clubs.bookclub")),
                ("club_book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="clubs.clubbook")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="club_book_votes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ClubPollVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("option", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="clubs.clubpolloption")),
                ("poll", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="clubs.clubpoll")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="club_poll_votes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="clubbookvote",
            constraint=models.UniqueConstraint(fields=("club", "user"), name="club_one_vote_per_user"),
        ),
        migrations.AddConstraint(
            model_name="clubbookvote",
            constraint=models.UniqueConstraint(fields=("club_book", "user"), name="club_book_vote_unique"),
        ),
        migrations.AddConstraint(
            model_name="clubpollvote",
            constraint=models.UniqueConstraint(fields=("poll", "user"), name="club_poll_one_vote_per_user"),
        ),
        migrations.AddConstraint(
            model_name="clubpollvote",
            constraint=models.UniqueConstraint(fields=("option", "user"), name="club_poll_option_vote_unique"),
        ),
    ]
