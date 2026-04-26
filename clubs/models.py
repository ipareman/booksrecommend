import secrets

from django.conf import settings
from django.db import models
from django.db.models import Count
from django.utils import timezone


class BookClub(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="clubs/", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="clubs_created",
    )
    is_public = models.BooleanField(default=True)
    max_members = models.PositiveIntegerField(default=50)
    invite_token = models.CharField(max_length=40, unique=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def member_count(self):
        return self.memberships.count()

    def ensure_invite_token(self, *, commit: bool = True):
        if not self.invite_token:
            self.invite_token = secrets.token_urlsafe(16)
            if commit:
                self.save(update_fields=["invite_token"])
        return self.invite_token

    def rotate_invite_token(self):
        self.invite_token = secrets.token_urlsafe(16)
        self.save(update_fields=["invite_token"])
        return self.invite_token

    def can_access(self, user) -> bool:
        if self.is_public:
            return True
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return self.memberships.filter(user=user).exists()

    def can_manage(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return self.memberships.filter(
            user=user, role__in=("owner", "admin")
        ).exists()

    def active_next_poll(self):
        return self.polls.filter(is_closed=False).order_by("-created_at").first()

    def active_meeting_book(self):
        today = timezone.localdate()
        return (
            self.club_books.filter(start_date__isnull=False, end_date__isnull=False)
            .filter(start_date__lte=today, end_date__gte=today)
            .select_related("book")
            .order_by("start_date")
            .first()
        )

    def vote_summary(self):
        return (
            self.club_books.filter(is_current=False)
            .select_related("book")
            .annotate(votes_count=Count("votes"))
            .order_by("-votes_count", "order", "book__title")
        )

    def save(self, *args, **kwargs):
        if not self.invite_token:
            self.invite_token = secrets.token_urlsafe(16)
        super().save(*args, **kwargs)


class ClubMembership(models.Model):
    ROLE_CHOICES = [
        ("owner", "Владелец"),
        ("admin", "Администратор"),
        ("member", "Участник"),
    ]
    club = models.ForeignKey(
        BookClub, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_memberships",
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("club", "user")

    def __str__(self):
        return f"{self.user} in {self.club} ({self.role})"


class ClubBook(models.Model):
    club = models.ForeignKey(
        BookClub, on_delete=models.CASCADE, related_name="club_books"
    )
    book = models.ForeignKey(
        "books.Book", on_delete=models.CASCADE, related_name="in_clubs"
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("club", "book")
        ordering = ["order"]

    def __str__(self):
        return f"{self.club.name}: {self.book.title}"

    def is_active_now(self):
        today = timezone.localdate()
        if self.start_date and self.end_date:
            return self.start_date <= today <= self.end_date
        return False

    def voting_badge(self):
        total = getattr(self, "votes_count", None)
        if total is None:
            total = self.votes.count()
        if total == 1:
            return "1 голос"
        if 2 <= total <= 4:
            return f"{total} голоса"
        return f"{total} голосов"


class ClubBookVote(models.Model):
    club = models.ForeignKey(
        BookClub, on_delete=models.CASCADE, related_name="book_votes"
    )
    club_book = models.ForeignKey(
        ClubBook, on_delete=models.CASCADE, related_name="votes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_book_votes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["club", "user"], name="club_one_vote_per_user"),
            models.UniqueConstraint(fields=["club_book", "user"], name="club_book_vote_unique"),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.club_id = self.club_book.club_id
        super().save(*args, **kwargs)


class ClubPoll(models.Model):
    club = models.ForeignKey(
        BookClub, on_delete=models.CASCADE, related_name="polls"
    )
    question = models.CharField(max_length=240)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_polls_created",
    )
    is_closed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.question

    def total_votes(self):
        return self.votes.count()

    def can_manage(self, user) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self.created_by_id == user.pk:
            return True
        return self.club.can_manage(user)


class ClubPollOption(models.Model):
    poll = models.ForeignKey(
        ClubPoll, on_delete=models.CASCADE, related_name="options"
    )
    text = models.CharField(max_length=160)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class ClubPollVote(models.Model):
    poll = models.ForeignKey(
        ClubPoll, on_delete=models.CASCADE, related_name="votes"
    )
    option = models.ForeignKey(
        ClubPollOption, on_delete=models.CASCADE, related_name="votes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_poll_votes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["poll", "user"], name="club_poll_one_vote_per_user"),
            models.UniqueConstraint(fields=["option", "user"], name="club_poll_option_vote_unique"),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.poll_id = self.option.poll_id
        super().save(*args, **kwargs)
