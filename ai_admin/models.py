"""
Модели админки AI: логи вызовов LLM, конфигурация, админ-чат.
"""
from django.db import models
from django.contrib.auth.models import User


class AIUsageLog(models.Model):
    """Запись о каждом вызове LLM."""

    FEATURE_CHOICES = [
        ("discovery",       "Discovery chat"),
        ("book_chat",       "Book chat"),
        ("recommendations", "Recommendations"),
        ("ai_search",       "AI search"),
        ("tag",             "Tag extraction"),
        ("mood",            "Mood classification"),
        ("quotes",          "Smart quotes"),
        ("sentiment",       "List sentiment"),
        # Фичи на основе полного текста книги (BookText/BookChapter)
        ("chapter_summary", "Chapter summary"),
        ("book_themes",     "Book themes"),
        ("book_search",     "In-book semantic search"),
        ("book_style",      "Book style profile"),
        ("other",           "Other"),
    ]
    TIER_CHOICES  = [("main", "main"), ("light", "light")]
    STATUS_CHOICES = [
        ("ok",         "OK"),
        ("error",      "Error"),
        ("rate_limit", "Rate limit"),
        ("dry_run",    "Dry run (no API call)"),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    user       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    feature    = models.CharField(max_length=32, choices=FEATURE_CHOICES, default="other", db_index=True)
    tier       = models.CharField(max_length=10, choices=TIER_CHOICES, default="main")
    model      = models.CharField(max_length=128, blank=True)

    prompt_tokens     = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens      = models.IntegerField(default=0)
    latency_ms        = models.IntegerField(default=0)

    status        = models.CharField(max_length=16, choices=STATUS_CHOICES, default="ok", db_index=True)
    error_message = models.TextField(blank=True)

    request_preview  = models.TextField(blank=True)
    response_preview = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at", "feature"]),
            models.Index(fields=["-created_at", "status"]),
        ]

    def __str__(self):
        return f"[{self.status}] {self.feature} · {self.model} · {self.total_tokens}t"


class AIConfig(models.Model):
    """Singleton — настройки AI (хранятся в БД, переопределяют settings.py)."""

    PROVIDER_CHOICES = [
        ("openrouter", "OpenRouter (default)"),
        ("aitunnel",   "AI Tunnel (aitunnel.ru)"),
        ("custom",     "Свой OpenAI-совместимый endpoint"),
    ]

    # Выбор провайдера LLM
    provider = models.CharField(
        max_length=16,
        choices=PROVIDER_CHOICES,
        default="openrouter",
        help_text="Выбор OpenAI-совместимого провайдера. Пусто = базовая настройка из settings.py.",
    )
    # Собственные креды/endpoint (используются, если provider != openrouter)
    custom_api_key  = models.CharField(max_length=256, blank=True,
                                       help_text="API-ключ для aitunnel или custom-endpoint.")
    custom_base_url = models.CharField(max_length=256, blank=True,
                                       help_text="Для provider=custom; у aitunnel используется стандартный URL.")

    model_main     = models.CharField(max_length=128, blank=True, help_text="Пусто = значение из settings.AI_MODEL_MAIN")
    model_light    = models.CharField(max_length=128, blank=True)
    model_fallback = models.CharField(max_length=128, blank=True)

    enable_discovery       = models.BooleanField(default=True)
    enable_book_chat       = models.BooleanField(default=True)
    enable_recommendations = models.BooleanField(default=True)
    enable_ai_search       = models.BooleanField(default=True)
    enable_tag             = models.BooleanField(default=True)
    enable_mood            = models.BooleanField(default=True)
    enable_quotes          = models.BooleanField(default=True)
    enable_sentiment       = models.BooleanField(default=True)
    # Фичи, работающие с полным текстом книги
    enable_chapter_summary = models.BooleanField(default=True)
    enable_book_themes     = models.BooleanField(default=True)
    enable_book_search     = models.BooleanField(default=True)
    enable_book_style      = models.BooleanField(default=True)

    # Dry-run: LLM-вызовы возвращают фейковый ответ, в API не ходят.
    # Удобно при массовом импорте, чтобы не «случайно» сжечь бюджет на токены.
    dry_run_mode = models.BooleanField(
        default=False,
        help_text="Сухой режим: LLM-вызовы логируются, но реального запроса к API не делают. "
                  "Возвращается фейковый ответ. Включите перед массовыми импортами, чтобы не палить токены.",
    )

    # Сайтовые настройки (живут тут, чтобы не плодить отдельный singleton).
    require_email_verification = models.BooleanField(
        default=True,
        help_text="Если выключено — регистрация активирует аккаунт сразу, без письма-подтверждения.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI configuration"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "AIConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def feature_enabled(self, feature: str) -> bool:
        return bool(getattr(self, f"enable_{feature}", True))

    # Карта «провайдер → базовый URL» (для провайдеров, чей URL фиксирован)
    PROVIDER_BASE_URLS = {
        "aitunnel": "https://api.aitunnel.ru/v1/",
    }

    def resolve_endpoint(self) -> tuple[str, str]:
        """
        Вернуть (api_key, base_url) с учётом выбранного провайдера.
        Если поля пустые, используются settings.ANTHROPIC_API_KEY / BASE_URL (OpenRouter).
        """
        from django.conf import settings
        default_key  = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
        default_base = getattr(settings, "ANTHROPIC_BASE_URL", "") or ""

        if self.provider == "aitunnel":
            return (
                (self.custom_api_key or getattr(settings, "AITUNNEL_API_KEY", "") or default_key),
                self.PROVIDER_BASE_URLS["aitunnel"],
            )
        if self.provider == "custom":
            return (
                (self.custom_api_key or default_key),
                (self.custom_base_url or default_base),
            )
        # openrouter / fallback
        return (default_key, default_base)


