# REFACTOR AUDIT — Проект «Строка» (Bookopolis)

**Дата аудита:** 2026-03-25
**Просканировано файлов:** ~82 (37 Python-модулей + 5 конфиг/инфра-файлов + 40 HTML-шаблонов)
**Стек:** Django 5.0.4, PostgreSQL 16, Celery 5.3.6, Redis 7, HTMX, BeautifulSoup4, Anthropic API

---

## Оглавление

1. [Критические баги (runtime crashes)](#1-критические-баги-runtime-crashes)
2. [Безопасность](#2-безопасность)
3. [Архитектура](#3-архитектура)
4. [Модели и база данных](#4-модели-и-база-данных)
5. [Celery и асинхронность](#5-celery-и-асинхронность)
6. [Docker и инфраструктура](#6-docker-и-инфраструктура)
7. [BeautifulSoup / парсинг](#7-beautifulsoup--парсинг)
8. [Качество кода](#8-качество-кода)
9. [Порядок рефакторинга](#9-порядок-рефакторинга)

---

## 1. Критические баги (runtime crashes)

### 1.1 🔴 `_render_store_links` использует неопределённую переменную `request`

**Файл:** `books/views.py:509-518`
**Категория:** баг / runtime crash
**Серьёзность:** 🔴 критично

Функция `_render_store_links` вызывает `render(request, ...)`, но `request` не передаётся как аргумент и не доступен в scope. Любое сохранение или удаление ссылки на магазин вызовет `NameError`.

```python
# СЕЙЧАС (строка 509):
def _render_store_links(book):
    ...
    return render(request, "books/_store_links.html", {...})  # request не определён!

# ИСПРАВЛЕНИЕ:
def _render_store_links(request, book):
    ...
    return render(request, "books/_store_links.html", {...})
```

Также нужно обновить все вызовы: `store_link_save` (строка 500) и `store_link_delete` (строка 507).

---

### 1.2 🔴 `_render_lists_panel` передаёт `None` как request

**Файл:** `users/views.py:39-41`
**Категория:** баг / runtime crash
**Серьёзность:** 🔴 критично

```python
# СЕЙЧАС:
def _render_lists_panel(user):
    lists = UserList.objects.filter(user=user).prefetch_related("books__authors")
    return render(None, "users/_lists_panel.html", {"lists": lists})

# ИСПРАВЛЕНИЕ:
def _render_lists_panel(request, user):
    lists = UserList.objects.filter(user=user).prefetch_related("books__authors")
    return render(request, "users/_lists_panel.html", {"lists": lists})
```

Все вызовы `_render_lists_panel` (строки в `create_list`, `delete_list`, `toggle_list_public`) должны передавать `request`.

---

### 1.3 🔴 Несовпадение имён настроек reCAPTCHA

**Файл:** `config/settings.py:103-104`, `core/templatetags/recaptcha_tags.py:9`, `.env`
**Категория:** баг / функциональность не работает
**Серьёзность:** 🔴 критично

В `settings.py` определены:
```python
RECAPTCHA_PUBLIC_KEY = os.getenv("RECAPTCHA_PUBLIC_KEY", "")
RECAPTCHA_PRIVATE_KEY = os.getenv("RECAPTCHA_PRIVATE_KEY", "")
```

В `.env` определены другие имена:
```
RECAPTCHA_SITE_KEY=
RECAPTCHA_SECRET_KEY=
```

В `recaptcha_tags.py` используется третье имя:
```python
site_key = getattr(settings, "RECAPTCHA_SITE_KEY", "")  # Никогда не определено!
```

Результат: reCAPTCHA никогда не загружается даже при настроенных ключах.

**Исправление:** привести все имена к единому стандарту:
```python
# settings.py:
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "")

# recaptcha_tags.py:
site_key = getattr(settings, "RECAPTCHA_SITE_KEY", "")

# views.py (price_captcha):
"recaptcha_site_key": settings.RECAPTCHA_SITE_KEY,
```

---

## 2. Безопасность

### 2.1 🔴 Токен Telegram выводится в stdout/логи

**Файл:** `config/settings.py:101`
**Категория:** безопасность
**Серьёзность:** 🔴 критично

```python
# СЕЙЧАС:
print(f'tg: {TELEGRAM_BOT_TOKEN}')

# ИСПРАВЛЕНИЕ: удалить строку полностью
```

**Файл:** `bot.py:106`
```python
# СЕЙЧАС:
logger.warning(f'my-token: {TOKEN}')

# ИСПРАВЛЕНИЕ: удалить или заменить на:
logger.info("Bot token configured: %s", "yes" if TOKEN else "no")
```

---

### 2.2 🔴 Небезопасный дефолтный SECRET_KEY

**Файл:** `config/settings.py:8`
**Категория:** безопасность
**Серьёзность:** 🔴 критично

```python
# СЕЙЧАС:
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")

# ИСПРАВЛЕНИЕ — падать при отсутствии ключа в production:
SECRET_KEY = os.environ["SECRET_KEY"]  # Упадёт при старте, если не задан
```

---

### 2.3 🔴 Отсутствуют настройки HTTPS-безопасности

**Файл:** `config/settings.py`
**Категория:** безопасность
**Серьёзность:** 🔴 критично

Не установлены ключевые настройки для production:

```python
# Добавить в settings.py (под условием not DEBUG):
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

---

### 2.4 🟡 `price_status` доступен без аутентификации

**Файл:** `books/views.py:384-399`
**Категория:** безопасность
**Серьёзность:** 🟡 важно

View `price_status` не защищён декоратором `@login_required`. Хотя утечка информации минимальна, это нарушает консистентность: `request_price` требует авторизации, а проверка статуса — нет.

```python
# ИСПРАВЛЕНИЕ:
@login_required
@require_GET
def price_status(request, pk):
    ...
```

---

### 2.5 🟡 `mark_safe` с переменными в шаблонном теге

**Файл:** `core/templatetags/recaptcha_tags.py:13-16`
**Категория:** безопасность / XSS
**Серьёзность:** 🟡 важно

```python
# СЕЙЧАС:
return mark_safe(
    f'<div class="g-recaptcha" data-sitekey="{site_key}" ...'
)

# ИСПРАВЛЕНИЕ — экранировать переменную:
from django.utils.html import escape
return mark_safe(
    f'<div class="g-recaptcha" data-sitekey="{escape(site_key)}" ...'
)
```

---

### 2.6 🟡 Хардкод production IP в ALLOWED_HOSTS

**Файл:** `config/settings.py:10`
**Категория:** безопасность
**Серьёзность:** 🟡 важно

```python
# СЕЙЧАС:
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,5.10.213.39").split(",")

# ИСПРАВЛЕНИЕ — IP только через .env:
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
```

---

### 2.7 🟡 Telegram-бот принимает пароли в открытом чате

**Файл:** `telegram_bot.py:73-98`
**Категория:** безопасность
**Серьёзность:** 🟡 важно

Бот на aiogram просит пользователя ввести пароль через Telegram-чат. Даже с удалением сообщения (`await message.delete()`) — пароль уже на серверах Telegram и может остаться в логах.

**Альтернатива:** использовать OAuth-ссылку или привязку через username (как в `bot.py`).

---

### 2.8 🟡 `staff_required` не использует `@wraps`

**Файл:** `books/views.py:27-33`, `users/views.py:30-35`
**Категория:** безопасность / качество
**Серьёзность:** 🟡 важно

Без `@wraps` теряются `__name__`, `__doc__`, `__module__` обёрнутой функции, что ломает отладку и introspection Django.

```python
# ИСПРАВЛЕНИЕ:
from functools import wraps

def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped
```

---

## 3. Архитектура

### 3.1 🟡 Дублирование views для автора

**Файл:** `books/views.py:464-484` и `books/author_views.py:14-110`
**Категория:** архитектура / дублирование
**Серьёзность:** 🟡 важно

Два полных набора views для автора:
- `views.py` содержит `author_detail` (строка 464) и `toggle_subscribe_author` (строка 472)
- `author_views.py` содержит свой `author_detail` (строка 14) и `toggle_author_subscription` (строка 96)

Логика фильтрации в `author_views.py` дублирует `_filter_books` из `views.py`, но реализована заново.

**Исправление:** оставить одну реализацию (в `author_views.py`), удалить дубли из `views.py`, переиспользовать `_filter_books`.

---

### 3.2 🟡 Дублирование `staff_required` декоратора

**Файл:** `books/views.py:27-33` и `users/views.py:30-35`
**Категория:** архитектура / дублирование
**Серьёзность:** 🟡 важно

Идентичный декоратор определён в двух файлах.

**Исправление:** вынести в `core/decorators.py` и импортировать:
```python
# core/decorators.py
from functools import wraps
from django.core.exceptions import PermissionDenied

def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped
```

---

### 3.3 🟡 Fat views — отсутствие сервисного слоя

**Файл:** `books/views.py` (786 строк), `users/views.py` (~280 строк)
**Категория:** архитектура
**Серьёзность:** 🟡 важно

Бизнес-логика (фильтрация, создание книг, управление списками, рекомендации) находится непосредственно во views.

**Исправление:** выделить сервисный слой:
```
books/
  services/
    catalog.py      # filter_books(), get_book_context()
    price.py        # request_price(), get_price_status()
    book_crud.py    # create_book(), edit_book()
```

---

### 3.4 🟡 Два Telegram-бота с разными подходами

**Файл:** `bot.py` (requests + polling) и `telegram_bot.py` (aiogram + FSM)
**Категория:** архитектура / дублирование
**Серьёзность:** 🟡 важно

Оба бота делают одно и то же — привязка Telegram к аккаунту, но разными способами. `telegram_bot.py` зависит от `aiogram`, которого нет в `requirements.txt`.

**Исправление:** оставить один бот (`bot.py` проще и не требует зависимостей), удалить `telegram_bot.py`.

---

### 3.5 🟢 `_book_of_the_week` использует `created_at` списка вместо даты добавления книги

**Файл:** `core/views.py:10-24`
**Категория:** архитектура / логическая ошибка
**Серьёзность:** 🟢 улучшение

```python
# СЕЙЧАС (строка 16):
Book.objects.filter(in_lists__created_at__gte=week_ago)
```

`in_lists__created_at` — это дата создания *списка*, а не дата *добавления книги* в список. M2M-таблица `UserList.books` не имеет промежуточной модели с `created_at`.

**Исправление:** использовать промежуточную модель (`through`) с полем `added_at`, или считать по другому критерию (например, по количеству отзывов за неделю).

---

## 4. Модели и база данных

### 4.1 🟡 Отсутствие `unique=True` на `Author.name`

**Файл:** `books/models.py:20`
**Категория:** целостность данных
**Серьёзность:** 🟡 важно

Можно создать несколько авторов с одинаковым именем. `get_or_create` в `_inline_create` зависит от поля `name`, но без unique constraint возможны гонки.

```python
# ИСПРАВЛЕНИЕ:
class Author(models.Model):
    name = models.CharField(max_length=250, unique=True)
```

---

### 4.2 🟡 Отсутствие `unique=True` на `Series.name`

**Файл:** `books/models.py:43`
**Категория:** целостность данных
**Серьёзность:** 🟡 важно

Аналогично Author — серии могут дублироваться.

```python
# ИСПРАВЛЕНИЕ:
class Series(models.Model):
    name = models.CharField(max_length=250, unique=True)
```

---

### 4.3 🟡 N+1 запросы в Django Admin

**Файл:** `books/admin.py:13-15`
**Категория:** производительность
**Серьёзность:** 🟡 важно

```python
# СЕЙЧАС:
def get_authors(self, obj):
    return ", ".join(a.name for a in obj.authors.all())  # N+1!

# ИСПРАВЛЕНИЕ — добавить prefetch:
class BookAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("authors")
```

---

### 4.4 🟡 `Review.save()` пересчитывает рейтинг при каждом сохранении

**Файл:** `reviews/models.py:29-35`
**Категория:** производительность
**Серьёзность:** 🟡 важно

Каждый вызов `review.save()` (включая обновление `extracted_tag`) запускает агрегатный запрос `Avg + Count` по всем одобренным отзывам книги.

```python
# СЕЙЧАС:
def save(self, *args, **kwargs):
    super().save(*args, **kwargs)
    _recalc(self.book)

# ИСПРАВЛЕНИЕ — пересчитывать только при изменении рейтинга/статуса:
def save(self, *args, **kwargs):
    update_fields = kwargs.get("update_fields")
    super().save(*args, **kwargs)
    if update_fields is None or "rating" in update_fields or "status" in update_fields:
        _recalc(self.book)
```

---

### 4.5 🟡 `select_related()` без аргументов

**Файл:** `books/recommendations.py:202`
**Категория:** производительность
**Серьёзность:** 🟡 важно

```python
# СЕЙЧАС:
Book.objects.filter(in_lists__user=user).select_related()  # Загружает ВСЕ FK

# ИСПРАВЛЕНИЕ:
Book.objects.filter(in_lists__user=user).select_related("publisher", "language")
```

---

### 4.6 🟡 `book_detail` загружает ВСЕ авторов/жанры/серии для каждого пользователя

**Файл:** `books/views.py:178-183`
**Категория:** производительность
**Серьёзность:** 🟡 важно

Строки 178-183 в `_get_book_detail_context` загружают `all_authors`, `all_genres`, `all_languages`, `all_publishers`, `all_series` — эти данные нужны только staff для формы редактирования, но загружаются для каждого посетителя.

```python
# ИСПРАВЛЕНИЕ:
if request.user.is_staff:
    ctx.update({
        "all_authors": Author.objects.order_by("name"),
        "all_genres": Genre.objects.order_by("name"),
        ...
    })
```

---

### 4.7 🟢 Отсутствие индекса на `BookTag.name`

**Файл:** `books/models.py:204`
**Категория:** производительность
**Серьёзность:** 🟢 улучшение

`BookTag.name` используется в `filter(name__iexact=...)` при каждом извлечении тега.

```python
# ИСПРАВЛЕНИЕ:
name = models.CharField(max_length=80, db_index=True)
```

---

### 4.8 🟢 Отсутствие индекса на `PriceAlert.triggered_at`

**Файл:** `books/models.py:260`
**Категория:** производительность
**Серьёзность:** 🟢 улучшение

`check_price_alerts` фильтрует по `triggered_at__isnull=True`.

```python
# ИСПРАВЛЕНИЕ:
triggered_at = models.DateTimeField(null=True, blank=True, db_index=True)
```

---

### 4.9 🟢 Отсутствие пагинации для цитат

**Файл:** `books/views.py:757-761`
**Категория:** производительность
**Серьёзность:** 🟢 улучшение

`quotes_partial` и `quote_add` загружают все цитаты книги без лимита. При большом количестве цитат — проблема.

```python
# ИСПРАВЛЕНИЕ:
quotes = Quote.objects.filter(book=book).select_related("user")[:50]
```

---

## 5. Celery и асинхронность

### 5.1 🟡 Большинство задач без retry-политики

**Категория:** надёжность
**Серьёзность:** 🟡 важно

| Задача | Файл | retry | time_limit |
|--------|-------|-------|------------|
| `scrape_book_prices` | `books/tasks.py:26` | max_retries=2 | ❌ |
| `extract_tags_from_description` | `books/tasks.py:97` | ❌ | ❌ |
| `check_price_alerts` | `books/tasks.py:146` | ❌ | ❌ |
| `extract_tag_for_review` | `reviews/tasks.py:8` | ❌ | ❌ |
| `notify_book_added` | `notifications/tasks.py:8` | ❌ | ❌ |
| `classify_list_sentiment` | `users/tasks.py:36` | ❌ | ❌ |
| `generate_ai_recommendations_task` | `users/tasks.py:8` | max_retries=1 | ❌ |

**Исправление — добавить ко всем задачам:**
```python
@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=120,
    time_limit=180,
)
def my_task(self, ...):
    try:
        ...
    except Exception as exc:
        raise self.retry(exc=exc)
```

---

### 5.2 🟡 Нет `soft_time_limit` на задачах с HTTP-запросами

**Файл:** `books/tasks.py:26` (`scrape_book_prices`), `books/tasks.py:97` (`extract_tags_from_description`)
**Категория:** надёжность
**Серьёзность:** 🟡 важно

`scrape_book_prices` делает N HTTP-запросов последовательно (по одному на каждый магазин). При зависшем соединении задача может заблокировать воркер навсегда.

```python
# ИСПРАВЛЕНИЕ:
@shared_task(bind=True, max_retries=2, default_retry_delay=30,
             soft_time_limit=120, time_limit=180)
def scrape_book_prices(self, book_id: int):
    ...
```

---

### 5.3 🟡 Отсутствие сервиса celery-beat в docker-compose

**Файл:** `docker-compose.yml`
**Категория:** инфраструктура
**Серьёзность:** 🟡 важно

`settings.py` определяет `CELERY_BEAT_SCHEDULE` с задачей `check-price-alerts-daily`, но в `docker-compose.yml` нет сервиса `celery-beat`. Периодические задачи не будут выполняться.

```yaml
# ИСПРАВЛЕНИЕ — добавить:
  celery-beat:
    build: .
    restart: unless-stopped
    command: celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes: [.:/app]
    env_file: .env
    depends_on: [web, redis]
```

---

## 6. Docker и инфраструктура

### 6.1 🔴 Отсутствует `.dockerignore`

**Файл:** корень проекта
**Категория:** инфраструктура / безопасность
**Серьёзность:** 🔴 критично

Без `.dockerignore` команда `COPY . .` в Dockerfile копирует в образ: `venv/` (~200+ МБ), `.git/`, `.env` (с секретами), `config.zip`, `.idea/`.

```
# Создать .dockerignore:
venv/
.venv/
.git/
.gitignore
.idea/
.env
*.zip
__pycache__/
*.pyc
media/
staticfiles/
```

---

### 6.2 🔴 `runserver` используется в production docker-compose

**Файл:** `docker-compose.yml:18`
**Категория:** инфраструктура / безопасность
**Серьёзность:** 🔴 критично

`runserver` — отладочный сервер Django, не предназначенный для production. Он однопоточный, медленный и не защищён от многих атак.

```yaml
# ИСПРАВЛЕНИЕ:
command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3

# Также добавить в requirements.txt:
gunicorn==22.0.0
```

---

### 6.3 🟡 Хардкод учётных данных в docker-compose

**Файл:** `docker-compose.yml:5-7`
**Категория:** безопасность / инфраструктура
**Серьёзность:** 🟡 важно

```yaml
# СЕЙЧАС:
environment:
  POSTGRES_DB: bookopolis
  POSTGRES_USER: postgres
  POSTGRES_PASSWORD: postgres

# ИСПРАВЛЕНИЕ — использовать .env:
env_file: .env
```

---

### 6.4 🟡 Отсутствие healthcheck для redis и celery

**Файл:** `docker-compose.yml`
**Категория:** инфраструктура
**Серьёзность:** 🟡 важно

```yaml
# ИСПРАВЛЕНИЕ для redis:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
```

---

### 6.5 🟡 Celery-воркер не имеет доступа к media

**Файл:** `docker-compose.yml:24-28`
**Категория:** инфраструктура
**Серьёзность:** 🟡 важно

Сервис `celery` не монтирует `media_data` volume, хотя задачи могут работать с обложками книг.

```yaml
# ИСПРАВЛЕНИЕ:
  celery:
    volumes: [.:/app, media_data:/app/media]
```

---

### 6.6 🟢 `config.zip` в корне проекта

**Файл:** `config.zip` (271 КБ)
**Категория:** инфраструктура
**Серьёзность:** 🟢 улучшение

Архив попадает в Docker-образ и Git-историю. Если содержит чувствительные данные — риск безопасности.

**Исправление:** удалить из репозитория, добавить `*.zip` в `.gitignore`.

---

## 7. BeautifulSoup / парсинг

### 7.1 🟡 Нет retry-логики при парсинге

**Файл:** `books/tasks.py:59-88`
**Категория:** надёжность
**Серьёзность:** 🟡 важно

При неудачном HTTP-запросе к магазину ошибка логируется, но повторная попытка не делается. Весь task имеет retry, но при частичном сбое (один магазин из пяти недоступен) — retry не происходит.

```python
# ИСПРАВЛЕНИЕ — retry на уровне отдельного запроса:
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
session.mount("https://", HTTPAdapter(
    max_retries=Retry(total=2, backoff_factor=1)
))
```

---

### 7.2 🟡 Одиночный CSS-селектор — хрупкий подход

**Файл:** `books/models.py:154-157` (Store.price_selector) и `books/tasks.py:56-64`
**Категория:** надёжность
**Серьёзность:** 🟡 важно

Если магазин обновляет вёрстку — парсинг полностью ломается. Нет fallback-селекторов.

```python
# ИСПРАВЛЕНИЕ — поддержка нескольких селекторов через запятую:
selectors = link.store.price_selector.split("|")
el = None
for sel in selectors:
    el = soup.select_one(sel.strip())
    if el:
        break
```

---

### 7.3 🟢 Парсинг не проверяет Content-Type ответа

**Файл:** `books/tasks.py:60-63`
**Категория:** надёжность
**Серьёзность:** 🟢 улучшение

Если сервер вернёт JSON или redirect вместо HTML — `BeautifulSoup` отработает без ошибки, но результат будет некорректным.

```python
# ИСПРАВЛЕНИЕ:
resp = requests.get(link.product_url, headers=headers, timeout=settings.SCRAPER_TIMEOUT)
resp.raise_for_status()
if "text/html" not in resp.headers.get("content-type", ""):
    logger.warning("Unexpected content-type for %s", link.product_url)
    continue
```

---

## 8. Качество кода

### 8.1 🟡 Дублированный импорт

**Файл:** `books/author_views.py:10-11`
**Категория:** читаемость
**Серьёзность:** 🟢 улучшение

```python
from users.models import AuthorSubscription
from users.models import AuthorSubscription  # Дубль — удалить
```

---

### 8.2 🟡 Файл `books/views.py` — 786 строк

**Файл:** `books/views.py`
**Категория:** читаемость / поддерживаемость
**Серьёзность:** 🟡 важно

Один файл содержит: каталог, детальную страницу книги, управление списками, цены, магазины, админ-операции, CRUD книг, прогресс чтения, цитаты, алерты цен. Следует разделить по доменам:

```
books/views/
    __init__.py
    catalog.py        # catalog, book_detail
    lists.py          # toggle_list
    prices.py         # request_price, price_status, price_chart_data, price_alert_*
    stores.py         # store_link_save, store_link_delete
    admin.py          # admin_delete_book, admin_books_partial, book_add, book_edit
    quotes.py         # quote_add, quote_delete, quotes_partial
    progress.py       # reading_progress_save
```

---

### 8.3 🟡 Магические числа без именованных констант

**Файл:** множество файлов
**Категория:** читаемость
**Серьёзность:** 🟡 важно

| Значение | Файл:строка | Описание |
|----------|-------------|----------|
| `[:200]` | `books/views.py:289` | Лимит авторов в каталоге |
| `[:50]` | `users/views.py:212, books/views.py:535` | Лимит элементов в админке |
| `[:30]` | `search/views.py:23` | Лимит результатов поиска |
| `[:40]` | `users/views.py:99` | Топ авторов для онбординга |
| `[:8]` | `users/views.py:203` | Популярные запросы |
| `0.05` | `search/views.py:52` | Порог FTS rank |
| `999999` | `books/views.py:727` | Fallback max pages |
| `[:20]` | `books/ai_recommendations.py:56,66` | Лимит книг/отзывов для AI |

**Исправление:** вынести в константы:
```python
# books/constants.py
CATALOG_AUTHORS_LIMIT = 200
ADMIN_LIST_LIMIT = 50
SEARCH_RESULTS_LIMIT = 30
FTS_RANK_THRESHOLD = 0.05
```

---

### 8.4 🟢 `UserList` docstring расположен после определения атрибута класса

**Файл:** `books/models.py:112-123`
**Категория:** читаемость
**Серьёзность:** 🟢 улучшение

```python
# СЕЙЧАС:
class UserList(models.Model):
    SENTIMENT_CHOICES = [...]
    """
    Пользовательский список книг.
    """

# ИСПРАВЛЕНИЕ:
class UserList(models.Model):
    """
    Пользовательский список книг.
    """
    SENTIMENT_CHOICES = [...]
```

---

### 8.5 🟢 Отсутствие type hints в большинстве view-функций

**Файл:** `books/views.py`, `users/views.py`, `core/views.py`
**Категория:** читаемость
**Серьёзность:** 🟢 улучшение

Views, helper-функции и Celery-задачи в основном не имеют аннотаций типов. Это затрудняет IDE-анализ и рефакторинг.

```python
# Пример — сейчас:
def _filter_books(params, base_qs=None):

# С аннотациями:
from django.db.models import QuerySet
from django.http import QueryDict

def _filter_books(params: QueryDict, base_qs: QuerySet | None = None) -> tuple[QuerySet, dict]:
```

---

### 8.6 🟢 `telegram_bot.py` зависит от `aiogram`, которого нет в requirements.txt

**Файл:** `telegram_bot.py:17-20`, `requirements.txt`
**Категория:** качество / воспроизводимость
**Серьёзность:** 🟢 улучшение

```python
from aiogram import Bot, Dispatcher, types, F  # aiogram не установлен
```

**Исправление:** либо добавить `aiogram>=3.0` в requirements.txt, либо удалить `telegram_bot.py` (см. п. 3.4).

---

### 8.7 🟢 Дублирование кода онбординга

**Файл:** `users/views.py:82-103` и `core/views.py:31-42`
**Категория:** архитектура / дублирование
**Серьёзность:** 🟢 улучшение

Контекст для онбординга (жанры + топ-авторы) формируется и в `onboarding` view, и в `home` view.

```python
# ИСПРАВЛЕНИЕ — вынести в хелпер:
# core/helpers.py
def get_onboarding_context():
    return {
        "onboarding_genres": Genre.objects.order_by("name"),
        "onboarding_authors": (
            Author.objects
            .annotate(book_count=Count("books"))
            .filter(book_count__gt=0)
            .order_by("-book_count")[:40]
        ),
    }
```

---

## 9. Порядок рефакторинга

Проблемы отсортированы от изолированных (безопасно исправлять в первую очередь) к затрагивающим несколько файлов.

### Этап 1 — Немедленные исправления (изолированные, минимальный риск)

| # | Проблема | Файл(ы) | Сложность |
|---|----------|---------|-----------|
| 1 | Удалить `print(f'tg: {TELEGRAM_BOT_TOKEN}')` | `settings.py:101` | 1 мин |
| 2 | Удалить `logger.warning(f'my-token: {TOKEN}')` | `bot.py:106` | 1 мин |
| 3 | Исправить имена reCAPTCHA настроек | `settings.py`, `.env`, `recaptcha_tags.py` | 5 мин |
| 4 | Удалить дублированный импорт | `author_views.py:11` | 1 мин |
| 5 | Создать `.dockerignore` | корень | 2 мин |
| 6 | Удалить `config.zip` из репозитория | корень | 1 мин |
| 7 | Исправить `UserList` docstring | `books/models.py:112` | 1 мин |

### Этап 2 — Исправление багов (runtime crashes)

| # | Проблема | Файл(ы) | Сложность |
|---|----------|---------|-----------|
| 8 | Передать `request` в `_render_store_links` | `books/views.py:500,507,509` | 5 мин |
| 9 | Передать `request` в `_render_lists_panel` | `users/views.py:39,create_list,delete_list,toggle_list_public` | 5 мин |

### Этап 3 — Безопасность

| # | Проблема | Файл(ы) | Сложность |
|---|----------|---------|-----------|
| 10 | Убрать дефолтный SECRET_KEY | `settings.py:8` | 5 мин |
| 11 | Добавить HTTPS-настройки | `settings.py` | 5 мин |
| 12 | Добавить `@login_required` на `price_status` | `books/views.py:384` | 1 мин |
| 13 | Экранировать `site_key` в `recaptcha_tags.py` | `core/templatetags/recaptcha_tags.py:13` | 2 мин |
| 14 | Убрать хардкод IP из ALLOWED_HOSTS | `settings.py:10` | 1 мин |
| 15 | Добавить `@wraps` в `staff_required` | `books/views.py:27`, `users/views.py:30` | 2 мин |
| 16 | Перенести DB credentials в .env для docker-compose | `docker-compose.yml` | 5 мин |

### Этап 4 — Производительность и надёжность

| # | Проблема | Файл(ы) | Сложность |
|---|----------|---------|-----------|
| 17 | Добавить `prefetch_related` в `BookAdmin` | `books/admin.py` | 2 мин |
| 18 | Оптимизировать `Review.save()` | `reviews/models.py:29` | 5 мин |
| 19 | Исправить `select_related()` без аргументов | `books/recommendations.py:202` | 1 мин |
| 20 | Ограничить контекст `book_detail` для staff | `books/views.py:178` | 5 мин |
| 21 | Добавить `db_index` на `BookTag.name` и `PriceAlert.triggered_at` | `books/models.py` | 5 мин + миграция |
| 22 | Добавить пагинацию цитат | `books/views.py:757` | 5 мин |
| 23 | Добавить `unique=True` на `Author.name` и `Series.name` | `books/models.py:20,43` | 5 мин + миграция |

### Этап 5 — Celery и инфраструктура

| # | Проблема | Файл(ы) | Сложность |
|---|----------|---------|-----------|
| 24 | Добавить retry/time_limit ко всем задачам | `books/tasks.py`, `reviews/tasks.py`, `notifications/tasks.py`, `users/tasks.py` | 30 мин |
| 25 | Добавить сервис celery-beat | `docker-compose.yml` | 5 мин |
| 26 | Заменить `runserver` на gunicorn | `docker-compose.yml`, `requirements.txt` | 10 мин |
| 27 | Добавить healthchecks для redis и celery | `docker-compose.yml` | 5 мин |
| 28 | Добавить `media_data` volume для celery | `docker-compose.yml` | 1 мин |
| 29 | Добавить retry-логику для парсинга | `books/tasks.py:55` | 15 мин |

### Этап 6 — Архитектурный рефакторинг (затрагивает несколько файлов)

| # | Проблема | Файл(ы) | Сложность |
|---|----------|---------|-----------|
| 30 | Вынести `staff_required` в `core/decorators.py` | `core/`, `books/views.py`, `users/views.py` | 10 мин |
| 31 | Удалить дублирующие views автора из `views.py` | `books/views.py`, `books/urls.py` | 15 мин |
| 32 | Удалить `telegram_bot.py` или `bot.py` | корень, `requirements.txt` | 10 мин |
| 33 | Вынести магические числа в константы | множество файлов | 20 мин |
| 34 | Разделить `books/views.py` на модули | `books/views/`, `books/urls.py` | 1 час |
| 35 | Создать сервисный слой | `books/services/`, `users/services/` | 2-4 часа |
| 36 | Добавить промежуточную модель для M2M UserList-Book | `books/models.py`, `core/views.py` | 1-2 часа + миграция |

---

## Сводка

| Серьёзность | Количество |
|-------------|-----------|
| 🔴 Критично | 8 |
| 🟡 Важно | 19 |
| 🟢 Улучшение | 9 |
| **Итого** | **36** |

Этапы 1-3 можно завершить за 1-2 часа и они устранят все критические и security-проблемы.
Этапы 4-5 займут ещё 2-3 часа и значительно повысят надёжность.
Этап 6 — архитектурный рефакторинг на 1-2 дня.
