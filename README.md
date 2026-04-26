# Строка

Каталог книг с рекомендательной системой, отслеживанием цен и Telegram-уведомлениями.

## Стек

- **Backend:** Django 5, PostgreSQL, Redis
- **Очереди:** Celery + Celery Beat
- **Фронтенд:** HTMX + Alpine.js (без сборщиков)
- **AI:** Anthropic Claude API (Haiku)
- **Уведомления:** Telegram Bot API

---

## Быстрый старт (Docker)

```bash
git clone <repo>
cd bookopolis

cp .env .env.local   # отредактируйте переменные (см. раздел «Переменные окружения»)

docker-compose up --build
```

После запуска в отдельном терминале:

```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py collectstatic --noinput
```

Сайт доступен на `http://localhost:8000`.

---

## Запуск без Docker

### Требования

- Python 3.12+
- PostgreSQL 14+
- Redis 7+

### Установка

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env .env.local
# Отредактируйте .env.local (см. раздел ниже)

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Запуск Celery (нужен для AI-рекомендаций, уведомлений, парсинга цен)

```bash
# Worker — обрабатывает задачи
celery -A config worker -l info

# Beat — запускает периодические задачи (алерты цен в 09:00)
celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## Переменные окружения

Скопируйте `.env` и заполните нужные поля. Обязательные помечены `*`.

| Переменная | Описание |
|---|---|
| `SECRET_KEY` * | Секретный ключ Django. Сгенерировать: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DEBUG` | `True` для разработки, `False` для продакшна |
| `ALLOWED_HOSTS` | Домены через запятую: `localhost,127.0.0.1,yourdomain.com` |
| `DB_NAME` | Имя базы данных PostgreSQL |
| `DB_USER` | Пользователь PostgreSQL |
| `DB_PASSWORD` | Пароль PostgreSQL |
| `DB_HOST` | Хост БД (`db` для Docker, `localhost` для локального запуска) |
| `DB_PORT` | Порт БД (обычно `5432`) |
| `REDIS_URL` | URL Redis (`redis://localhost:6379/0`) |
| `SITE_URL` | Публичный адрес сайта (нужен для ссылок в уведомлениях) |
| `ANTHROPIC_API_KEY` | Ключ Anthropic API — нужен для AI-рекомендаций и автотегирования |
| `TELEGRAM_BOT_TOKEN` | Токен бота — получить у [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_BOT_USERNAME` | Имя бота без `@` |
| `RECAPTCHA_PUBLIC_KEY` | Публичный ключ Google reCAPTCHA v2 |
| `RECAPTCHA_PRIVATE_KEY` | Приватный ключ Google reCAPTCHA v2 |
| `MEDIA_ROOT` | Путь для загруженных файлов (обложки книг) |

---

## Архитектура

```
bookopolis/
├── books/          — каталог, модели книг, рекомендации, цены
├── users/          — профили, списки, AI-рекомендации
├── reviews/        — отзывы и их модерация
├── search/         — полнотекстовый поиск (FTS PostgreSQL)
├── notifications/  — Telegram-уведомления
├── core/           — главная страница, базовые шаблоны
└── config/         — настройки, Celery, URL-конфиги
```

### Ключевые модели

**`Book`** — книга с авторами, жанрами, издателем, серией, языком. Хранит `avg_rating`, `avg_price` (денормализованные для производительности).

**`UserList`** — пользовательский список книг. Поле `sentiment_tag` (`positive` / `negative` / `neutral` / `wishlist`) определяется автоматически через Claude при создании и влияет на качество рекомендаций. Поле `is_public` открывает список на странице публичных подборок.

**`ReadingProgress`** — текущая страница пользователя в книге. Уникальная пара `(user, book)`.

**`Quote`** — цитата из книги с номером страницы.

**`PriceAlert`** — порог цены для Telegram-уведомления. Срабатывает один раз (`triggered_at` сбрасывается при обновлении порога).

**`BookStore`** / **`BookPrice`** — связь книги с магазином, история цен.

**`BookTag`** — тег книги извлечённый Claude из отзывов и описаний. Хранит счётчик упоминаний.

---

## Рекомендательная система

Работает на трёх уровнях.

### 1. Похожие книги (`similar_books`)

Показываются на странице каждой книги. Скоринг кандидатов:

- `+4` за каждого совпавшего автора
- `+3 × IDF` за каждый совпавший жанр (редкий жанр ценнее массового)
- `+2` если та же серия
- `+1` если год публикации ±5 лет
- `+0.5 × avg_rating` бонус за качество

IDF-веса кешируются в Redis на 1 час и инвалидируются при добавлении книги.

### 2. «Также читают» (`also_read`)

Item-based коллаборативная фильтрация: находим пользователей у которых эта книга есть в **положительных** списках, смотрим какие ещё книги они добавляли. Книги из списков с тегом `negative` в расчёт не берутся.

### 3. Персональные рекомендации (`recommended_for_user`)

Строим профиль вкуса из жанров и авторов книг пользователя, взвешенный по:
- `sentiment_tag` списка (`positive: 1.0`, `wishlist: 0.6`, `neutral: 0.4`, `negative: -0.5`)
- рейтингу отзыва пользователя на эту книгу

Применяем TF-IDF чтобы редкие жанры давали более точные попадания.

### 4. AI-рекомендации

Двухэтапный pipeline:
1. Алгоритмический скоринг даёт 50 кандидатов
2. Claude (Haiku) переранжирует их с учётом контекста пользователя и описаний книг

Используется `tool_use` с принудительной схемой — JSON гарантирован API. Кандидаты передаются по порядковому индексу (не `pk`) — галлюцинации по ID физически невозможны. Результат кешируется в Redis на 24 часа.

**Требует:** `ANTHROPIC_API_KEY` + запущенный Celery worker.

---

## Автотегирование через AI

При каждом действии Claude вызывается автоматически — пользователь ничего не делает вручную.

**Теги книг** — при создании книги с описанием Celery запускает задачу `extract_tags_from_description`. Claude извлекает 3 характерные черты (атмосфера, темп, стиль, тема) и добавляет их в `BookTag`. Дополняет теги из отзывов читателей.

**Тег списка** — при создании нового списка Celery запускает `classify_list_sentiment`. Claude читает название и возвращает одно слово: `positive` / `negative` / `wishlist` / `neutral`. Стоит доли цента (max_tokens=10).

---

## Парсинг цен

Цены по магазинам парсятся через Celery-задачу `scrape_book_prices`. Запускается по запросу пользователя (кнопка на странице книги, защищена reCAPTCHA).

Для каждого магазина задаётся CSS-селектор цены в админ-панели. Результаты сохраняются в историю `BookPrice` и показываются на графике.

**Алерт цены** — пользователь может установить порог на странице книги. Celery Beat проверяет все активные алерты ежедневно в 09:00 и шлёт Telegram-сообщение при срабатывании.

---

## Telegram-бот

Бот позволяет пользователям привязать аккаунт и получать уведомления.

```bash
# Запуск бота (отдельный процесс)
python telegram_bot.py
```

Команды бота:
- `/start` — привязать аккаунт сайта (логин + пароль)
- `/stop` — отвязать аккаунт
- `/me` — показать текущий аккаунт

Уведомления:
- Новая книга от автора на которого подписан
- Цена книги упала ниже установленного порога

---

## Администрирование

Панель администратора доступна на `/users/admin-panel/` для `is_staff` пользователей (не Django admin).

Возможности:
- Управление книгами: добавление, редактирование, копирование
- Управление пользователями: блокировка/разблокировка
- Управление магазинами и CSS-селекторами цен
- Модерация отзывов
- Статистика: количество книг, пользователей, отзывов, поисковых запросов

Стандартный Django admin доступен на `/admin/` — только для `is_superuser`.

---

## Первичное наполнение каталога

После создания суперпользователя откройте `/users/admin-panel/` и добавьте книги через форму. Поддерживается:

- Загрузка обложки
- Выбор существующих авторов/жанров или создание новых прямо в форме
- Копирование книги (`⧉ Копировать` на странице книги) — удобно для книг одного автора или серии

---

## Миграции

При обновлении проекта всегда запускайте миграции:

```bash
python manage.py migrate
# или в Docker:
docker-compose exec web python manage.py migrate
```

История миграций:
| Миграция | Содержание |
|---|---|
| `books/0001_initial` | Базовые модели: Book, Author, Genre, Publisher, Series, Language, UserList, Store, BookStore, BookPrice |
| `books/0002_booktag` | Модель BookTag (теги из отзывов) |
| `books/0003_improvements` | ReadingProgress, Quote, PriceAlert; поля `sentiment_tag` и `is_public` в UserList |
| `users/0001_initial` | UserProfile, AuthorSubscription |
| `users/0002_userprofile_onboarding` | Поле `onboarding_done` в UserProfile |
| `reviews/0001_initial` | Модель Review |
| `reviews/0002_review_extracted_tag` | Поле `extracted_tag` в Review |
| `search/0001_initial` | SearchHistory |
| `search/0002_books_fts_index` | FTS-индекс PostgreSQL для поиска |

---

## Известные ограничения

**Celery Beat и периодические задачи.** Расписание хранится в БД (`django_celery_beat`). При первом запуске Beat нужно применить миграции. Задачи из `CELERY_BEAT_SCHEDULE` в `settings.py` применяются автоматически.

**reCAPTCHA.** Если `RECAPTCHA_PUBLIC_KEY` не задан — кнопка запроса цен работает без капчи. Для продакшна обязательно задать оба ключа.

**AI-функции без ключа.** Если `ANTHROPIC_API_KEY` не задан — все AI-функции молча пропускаются (логируется предупреждение). Сайт работает полностью без ключа, просто без AI-тегов и рекомендаций.

**Telegram без бота.** Если `TELEGRAM_BOT_TOKEN` не задан — уведомления пропускаются. Парсинг цен и все остальные функции работают в штатном режиме.
