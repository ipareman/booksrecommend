import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

_DEV_SECRET_FALLBACK = "dev-secret-change-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", _DEV_SECRET_FALLBACK)
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,5.10.213.39").split(",")

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# Когда сайт работает за nginx с TLS-терминацией:
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True") == "True"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "True") == "True"
    CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "True") == "True"
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    USE_X_FORWARDED_HOST = True

# Защита от запуска в продакшене с дефолтным SECRET_KEY.
if not DEBUG and SECRET_KEY == _DEV_SECRET_FALLBACK:
    raise RuntimeError(
        "SECRET_KEY is not set. Define the SECRET_KEY environment variable "
        "before running with DEBUG=False."
    )

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "django_htmx",
    "widget_tweaks",
    "django_celery_beat",

    "core",
    "books.apps.BooksConfig",
    "users",
    "search",
    "reviews",
    "tickets",
    "notifications",
    "social",
    "curated",
    "graph",
    "ai_chat",
    "clubs",
    "chat",
    "ai_admin",
    "analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "core" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.globals",
                "social.context_processors.social_counts",
                "notifications.context_processors.notifications_counts",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(os.getenv("REDIS_HOST", "redis"), 6379)],
        },
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "bookopolis"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# Кеш: Redis если доступен, иначе LocMemCache (работает всегда)
_REDIS_CACHE_URL = os.getenv("REDIS_CACHE_URL", "")
_USE_REDIS_CACHE = False
if _REDIS_CACHE_URL:
    try:
        import redis as _redis_client
        _r = _redis_client.Redis.from_url(_REDIS_CACHE_URL, socket_connect_timeout=1)
        _r.ping()
        _r.close()
        _USE_REDIS_CACHE = True
    except Exception:
        pass

if _USE_REDIS_CACHE:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _REDIS_CACHE_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/users/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "core" / "static"]
WHITENOISE_USE_FINDERS = True  # отдаёт из STATICFILES_DIRS без collectstatic
if DEBUG:
    WHITENOISE_AUTOREFRESH = True
    WHITENOISE_MAX_AGE = 0

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / os.getenv("MEDIA_ROOT", "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = not _USE_REDIS_CACHE  # без Redis задачи выполняются синхронно
CELERY_TIMEZONE = "Europe/Moscow"

BOOKS_PER_PAGE = 20

# Заголовки для HTTP-запросов при парсинге цен
SCRAPER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
SCRAPER_TIMEOUT = 15

SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")

# Telegram Bot
TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "")  # без @

# MAX Bot (https://dev.max.ru/)
MAX_BOT_TOKEN    = os.getenv("MAX_BOT_TOKEN", "")
MAX_BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "")  # без @

# Google reCAPTCHA v2.
# Поддерживаем оба набора имён (SITE/SECRET — стандарт Google, PUBLIC/PRIVATE — историческое).
# Любое из имён в .env заполнит обе переменные, чтобы старый и новый код работали одинаково.
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY") or os.getenv("RECAPTCHA_PUBLIC_KEY", "")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY") or os.getenv("RECAPTCHA_PRIVATE_KEY", "")
RECAPTCHA_PUBLIC_KEY = RECAPTCHA_SITE_KEY    # alias для обратной совместимости
RECAPTCHA_PRIVATE_KEY = RECAPTCHA_SECRET_KEY  # alias для обратной совместимости

# LLM API (OpenRouter, OpenAI-совместимый endpoint)
# Поддерживает старые имена ANTHROPIC_* для обратной совместимости
ANTHROPIC_API_KEY  = os.getenv("OPENROUTER_API_KEY") or os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("OPENROUTER_BASE_URL") or os.getenv(
    "ANTHROPIC_BASE_URL", "https://openrouter.ai/api/v1"
)

# Модели OpenRouter (free-tier)
AI_MODEL_MAIN     = os.getenv("AI_MODEL_MAIN",     "minimax/minimax-m2.5:free")                 # чат, рекомендации, function calling (провайдер MiniMax, 196k)
AI_MODEL_LIGHT    = os.getenv("AI_MODEL_LIGHT",    "google/gemma-4-26b-a4b-it:free")            # цитаты, теги, sentiment (MoE)
AI_MODEL_FALLBACK = os.getenv("AI_MODEL_FALLBACK", "openrouter/free")                           # авто-роутер OR при rate-limit
AI_MODEL_FALLBACK2 = os.getenv("AI_MODEL_FALLBACK2", "google/gemma-4-31b-it:free")              # второй резерв (другой провайдер)

# Опциональные заголовки для статистики OpenRouter
AI_HTTP_REFERER = os.getenv("AI_HTTP_REFERER", SITE_URL)
AI_APP_TITLE    = os.getenv("AI_APP_TITLE",    "Stroka")

# Таймаут HTTP-запроса к LLM-провайдеру (секунды). Сужает потенциально
# 10-минутное ожидание SDK, чтобы не висеть в ASGI-потоках при дисконнекте.
AI_HTTP_TIMEOUT = float(os.getenv("AI_HTTP_TIMEOUT", "45"))

# Google Books API (опционально, без ключа — 1000 запросов/день)
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "")

# Кэш AI-рекомендаций (секунды)
AI_RECS_CACHE_TTL = 60 * 60 * 24  # 24 часа

# Email (для уведомлений)
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@stroka.local")

# Celery Beat: периодические задачи
from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    # Проверка алертов цен каждый день в 09:00
    "check-price-alerts-daily": {
        "task":     "books.tasks.check_price_alerts",
        "schedule": crontab(hour=9, minute=0),
    },
    # Еженедельный дайджест AI-рекомендаций в Telegram (понедельник, 10:00)
    "weekly-recommendations-digest": {
        "task":     "users.tasks.send_weekly_digest",
        "schedule": crontab(hour=10, minute=0, day_of_week=1),
    },
    # Аналитика: пересборка дашборда раз в час, 5-я минута
    "analytics-refresh-dashboard": {
        "task":     "analytics.refresh_dashboard_cache",
        "schedule": crontab(minute=5),
    },
}


RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
