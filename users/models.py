from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    user            = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar          = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio             = models.TextField(blank=True)
    telegram_username = models.CharField(
        max_length=100, blank=True,
        help_text="Логин Telegram без @, например: ivan_petrov"
    )
    telegram_chat_id  = models.CharField(
        max_length=50, blank=True,
        help_text="Заполняется автоматически после /start боту"
    )
    max_username      = models.CharField(
        max_length=100, blank=True,
        help_text="Логин MAX без @, например: ivan_petrov"
    )
    max_user_id       = models.CharField(
        max_length=50, blank=True,
        help_text="Заполняется автоматически после /start MAX-боту"
    )
    email_verified  = models.BooleanField(default=False)
    is_blocked      = models.BooleanField(default=False)
    blocked_until   = models.DateTimeField(null=True, blank=True)

    # Онбординг: показать модал при первом входе
    onboarding_done = models.BooleanField(default=False)

    # Предпочтения (онбординг + редактируются в профиле)
    favorite_genres  = models.ManyToManyField("books.Genre",  blank=True,
                                               related_name="fans")
    favorite_authors = models.ManyToManyField("books.Author", blank=True,
                                               related_name="fans")

    def __str__(self):
        return f"Profile: {self.user.username}"

    @property
    def is_currently_blocked(self):
        if not self.is_blocked:
            return False
        if self.blocked_until is None:
            return True
        return timezone.now() < self.blocked_until


class UserBlockHistory(models.Model):
    """История блокировок пользователей администраторами.

    Одна запись = один эпизод блокировки. Если `unblocked_at` пустое —
    блокировка активна (или истекла по `blocked_until`).
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="block_history",
        help_text="Кого заблокировали",
    )
    blocked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="block_actions_performed",
        help_text="Администратор, наложивший блокировку",
    )
    reason        = models.TextField(blank=True, help_text="Причина блокировки")
    blocked_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    blocked_until = models.DateTimeField(null=True, blank=True,
                                         help_text="Когда блокировка истекает (пусто = бессрочно)")

    unblocked_at   = models.DateTimeField(null=True, blank=True,
                                          help_text="Когда был разблокирован досрочно")
    unblocked_by   = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="unblock_actions_performed",
    )
    unblock_reason = models.TextField(blank=True, help_text="Причина досрочной разблокировки")

    class Meta:
        ordering = ["-blocked_at"]
        indexes = [
            models.Index(fields=["user", "-blocked_at"]),
            models.Index(fields=["-blocked_at"]),
        ]

    def __str__(self):
        suffix = "активна" if self.unblocked_at is None else "снята"
        return f"Блок {self.user.username} от {self.blocked_at:%d.%m.%Y} ({suffix})"

    @property
    def is_active(self) -> bool:
        """True, если эта запись описывает активную блокировку прямо сейчас."""
        if self.unblocked_at is not None:
            return False
        if self.blocked_until and timezone.now() >= self.blocked_until:
            return False
        return True


class AuthorSubscription(models.Model):
    user   = models.ForeignKey(User, on_delete=models.CASCADE, related_name="author_subscriptions")
    author = models.ForeignKey("books.Author", on_delete=models.CASCADE, related_name="subscribers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "author"], name="author_sub_unique")
        ]

    def __str__(self):
        return f"{self.user.username} → {self.author.name}"


class Achievement(models.Model):
    """Достижение пользователя (геймификация)."""

    TYPES = [
        ("books_10",       "Библиофил: 10 книг в списках"),
        ("books_50",       "Книжный червь: 50 книг в списках"),
        ("reviews_5",      "Критик: 5 отзывов"),
        ("reviews_20",     "Литературовед: 20 отзывов"),
        ("pages_1000",     "Марафонец: 1 000 страниц"),
        ("pages_5000",     "Книжный титан: 5 000 страниц"),
        ("lists_3",        "Коллекционер: 3 списка"),
        ("subscriptions_5","Фанат: 5 подписок на авторов"),
    ]

    ICONS = {
        "books_10": "📚", "books_50": "📖",
        "reviews_5": "✍️", "reviews_20": "🎓",
        "pages_1000": "🏃", "pages_5000": "🏆",
        "lists_3": "📂", "subscriptions_5": "⭐",
    }

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="achievements")
    achievement_type = models.CharField(max_length=30, choices=TYPES)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "achievement_type"],
                                    name="achievement_unique")
        ]

    def __str__(self):
        return f"{self.user.username}: {self.get_achievement_type_display()}"

    @property
    def icon(self):
        return self.ICONS.get(self.achievement_type, "🏅")


def check_achievements(user):
    """Проверить и выдать новые достижения. Вызывать после значимых действий."""
    from books.models import UserList, ReadingProgress
    from reviews.models import Review

    earned = set(user.achievements.values_list("achievement_type", flat=True))
    new = []

    book_count = (
        UserList.objects.filter(user=user)
        .values("books").distinct().count()
    )
    review_count = Review.objects.filter(user=user, status=Review.APPROVED).count()
    pages_read = (
        ReadingProgress.objects.filter(user=user)
        .aggregate(total=models.Sum("current_page"))["total"] or 0
    )
    list_count = UserList.objects.filter(user=user).count()
    sub_count = AuthorSubscription.objects.filter(user=user).count()

    checks = [
        ("books_10",        book_count >= 10),
        ("books_50",        book_count >= 50),
        ("reviews_5",       review_count >= 5),
        ("reviews_20",      review_count >= 20),
        ("pages_1000",      pages_read >= 1000),
        ("pages_5000",      pages_read >= 5000),
        ("lists_3",         list_count >= 3),
        ("subscriptions_5", sub_count >= 5),
    ]

    for atype, condition in checks:
        if atype not in earned and condition:
            Achievement.objects.create(user=user, achievement_type=atype)
            new.append(atype)

    return new


def get_achievements_progress(user):
    """Вернуть список всех достижений с прогрессом и глобальной статистикой.

    Каждый элемент:
      {type, name, icon, earned, earned_at, current, target, percent, global_percent}
    """
    from books.models import UserList, ReadingProgress
    from reviews.models import Review

    # Текущие значения пользователя
    book_count = (
        UserList.objects.filter(user=user)
        .values("books").distinct().count()
    )
    review_count = Review.objects.filter(user=user, status=Review.APPROVED).count()
    pages_read = (
        ReadingProgress.objects.filter(user=user)
        .aggregate(total=models.Sum("current_page"))["total"] or 0
    )
    list_count = UserList.objects.filter(user=user).count()
    sub_count = AuthorSubscription.objects.filter(user=user).count()

    targets = {
        "books_10":        (book_count,    10),
        "books_50":        (book_count,    50),
        "reviews_5":       (review_count,  5),
        "reviews_20":      (review_count,  20),
        "pages_1000":      (pages_read,    1000),
        "pages_5000":      (pages_read,    5000),
        "lists_3":         (list_count,    3),
        "subscriptions_5": (sub_count,     5),
    }

    # Заработанные этим пользователем (с датой)
    user_earned = {
        a.achievement_type: a.earned_at
        for a in user.achievements.all()
    }

    # Глобальная статистика: сколько пользователей получили каждое достижение
    total_users = max(User.objects.count(), 1)
    global_counts = dict(
        Achievement.objects.values_list("achievement_type")
        .annotate(c=models.Count("user", distinct=True))
        .values_list("achievement_type", "c")
    )

    result = []
    for atype, label in Achievement.TYPES:
        current, target = targets[atype]
        earned = atype in user_earned
        percent = 100 if earned else min(100, int(current * 100 / target)) if target else 0
        global_count = global_counts.get(atype, 0)
        global_percent = round(global_count * 100 / total_users, 1)
        result.append({
            "type":           atype,
            "name":           label,
            "icon":           Achievement.ICONS.get(atype, "🏅"),
            "earned":         earned,
            "earned_at":      user_earned.get(atype),
            "current":        min(current, target),
            "target":         target,
            "percent":        percent,
            "global_percent": global_percent,
        })
    return result


@receiver(post_save, sender=User)
def create_user_defaults(sender, instance, created, **kwargs):
    if not created:
        return
    UserProfile.objects.get_or_create(user=instance)
    from books.models import UserList
    UserList.objects.get_or_create(
        user=instance,
        name="Избранное",
        defaults={"is_default": True, "sentiment_tag": "positive"},
    )


@receiver(post_save, sender="books.UserList")
def classify_new_list(sender, instance, created, **kwargs):
    """Classify sentiment of new list via Claude."""
    if not created or instance.is_default:
        return
    from users.tasks import classify_list_sentiment
    classify_list_sentiment.delay(instance.pk)
