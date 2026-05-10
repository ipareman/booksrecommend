# AI Context — Проект «Строка» (Bookopolis)

> **Назначение файла:** единый источник контекста для всех AI-агентов и LLM, работающих с кодовой базой.  
> **Правило:** перед любыми правками прочитай этот файл. Если ты изменил модели, URL, зависимости или дизайн — обнови соответствующий раздел ниже.

---

## 1. Обзор проекта

**«Строка»** — каталог книг с рекомендательной системой, отслеживанием цен, Telegram/MAX/VK-уведомлениями, встроенной читалкой (EPUB/FB2), AI-чатом с книгой и социальными фичами (клубы, рецензии, лента активности).

- **Язык интерфейса:** русский
- **Код:** Python + Django шаблоны (русский / английский docstrings)
- **Django settings:** `config.settings`
- **WSGI:** `config.wsgi`
- **ASGI:** `config.asgi`

---

## 2. Полное описание системы и функционала

### 2.1 Главная страница (Home)
- **Популярные книги** — сортировка по количеству рецензий
- **Новинки** — последние по году публикации
- **Книга недели** — книга с наибольшим числом добавлений в списки за последние 7 дней (fallback — самая рейтинговая)
- **Случайные цитаты** — минимум 40 символов, с обложками книг
- **Свежие рецензии (Critiques)** — одобренные, с обложкой, автором, книгой
- **Свежие отзывы (Reviews)** — одобренные, минимум 30 символов
- **Подборки (Collections)** — публичные, с превью 4 книг
- **Книжные клубы (Clubs)** — публичные, с текущей книгой и числом участников
- **Книжные серии (Series)** — случайные серии с ≥2 книгами и обложками
- **Лента активности (Ticker)** — события друзей (рецензии, вступление в клубы, дружба) + общие события
- **Персональные рекомендации** — для авторизованных пользователей (алгоритмические + AI)
- **Discovery Chat** — AI-диалог для поиска книг, история сообщений на главной
- **Поисковая история** — последние 15 уникальных запросов пользователя
- **Онбординг-модал** — для новых пользователей (выбор жанров, авторов, книг-эталонов)

### 2.2 Каталог книг (/books/)
- **Текстовый поиск** — по названию, автору, жанру, описанию, ISBN
- **Фильтры:** жанры (множественный выбор), авторы, языки, год (диапазон), страницы (диапазон), цена (диапазон), минимальный рейтинг, mood-теги
- **Пресеты:** Новинки, Популярные, Топ-рейтинг, Классика, До 300 ₽
- **Сортировка:** по рейтингу, числу рецензий, году, цене
- **Пагинация**

### 2.3 Страница книги
- **Основная информация** — обложка, авторы, жанры, издательство, год, страницы, язык, ISBN, описание
- **Рейтинг** — денормализованный `avg_rating` + `rating_count`
- **Mood-теги** — атмосфера, темп, эмоции, сложность (с голосованием пользователей)
- **Похожие книги** — по жанрам/авторам
- **«Также читают»** — пользователи с этой книгой в списках
- **Отзывы (Reviews)** — 1-5 звёзд, текст, модерация (pending/approved/rejected), лайки «Полезно», извлечённые AI-теги
- **Рецензии (Critiques)** — расширенные обзоры с критериями (1-5), обложкой рецензии, HTML/Markdown редактор, модерация, лайки, комментарии с replies и голосованием (+1/-1)
- **Цитаты (Quotes)** — добавление, удаление, AI-генерация умных цитат
- **Приватные заметки (Notes)** — к выделенным фрагментам текста, группировка по книге
- **Списки пользователя** — добавление/удаление книги в списки (Любимые, Хочу прочитать, и т.д.)
- **Ссылки на магазины** — с текущими ценами, обновление цен по запросу
- **График цен** — история изменения цен
- **Алерты на цену** — уведомление при снижении ниже порога
- **Прогресс чтения** — текущая страница/глава
- **Прогноз времени чтения** — на основе истории скорости пользователя
- **Группы изданий (Edition Groups)** — объединение разных изданий одного произведения

### 2.4 Встроенная читалка
- **Загрузка полного текста** — EPUB/FB2 (только staff или пользователи с книгой в списке)
- **Чтение по главам** — навигация, прогресс
- **Сохранение прогресса** — страница, глава, scroll offset, режим (manual/reader)
- **Семантический поиск по главам** — AI-поиск по содержанию книги
- **AI-саммари глав** — автоматическое summarization
- **AI-выделение цитат** — извлечение ключевых цитат из текста
- **AI-темы** — анализ тематики книги
- **AI-стиль** — профиль стиля автора для рекомендаций

### 2.5 AI Chat с книгой (/ai-chat/)
- **Персональный чат** с AI о конкретной книге
- **История сообщений** — сохраняется между сессиями
- **Асинхронная обработка** — Celery task, polling статуса
- **Очистка истории**

### 2.6 AI Discovery Chat
- **Диалоговый поиск книг** — пользователь описывает пожелания, AI рекомендует книги из каталога
- **Follow-up вопросы** — уточняющие вопросы AI
- **История рекомендаций** — сохраняется, можно сохранить как список
- **Цены на рекомендованные книги** — подтягиваются автоматически

### 2.7 Профиль пользователя (/users/profile/)
- **Списки книг** — создание, удаление, управление
- **Экспорт списков** — в CSV/JSON
- **Импорт библиотеки** — импорт списков книг
- **История поиска**
- **Рецензии и отзывы** пользователя
- **AI-рекомендации** — с объяснением почему (reason bullets)
- **Обычные рекомендации** — с диагностикой почему пусто
- **Подписки на авторов** — с уведомлениями о новых книгах
- **Статистика:** прочитано книг, страниц, топ-3 жанра, средний рейтинг
- **Достижения (Achievements)** — система ачивок с прогрессом
- **Приватные заметки** — с группировкой по книге
- **Понравившиеся подборки**

### 2.8 Аккаунт и настройки
- **Регистрация** — username, password, email, согласие на обработку данных, reCAPTCHA v2
- **Email-верификация** — через Resend (можно отключить в AI Admin)
- **Вход/Выход** — с блокировкой заблокированных пользователей
- **Сброс пароля** — стандартный Django flow
- **Настройки профиля** — аватар (8 градиентов), био, Telegram, MAX (партнёрский сервис), VK, контакты
- **Онбординг** — 3 шага: жанры → авторы → книги-эталоны (cold-start для рекомендаций)

### 2.9 Социальные функции (/social/)
- **Друзья** — заявки, принятие, удаление, список друзей, входящие/исходящие заявки
- **Рекомендации книг друзьям** — отправка книги другу с персональным сообщением
- **Лента активности (Activity Feed)** — события: рецензии, отзывы, вступление в клубы, новые дружбы, рекомендации книг
- **Публичные профили** — профиль пользователя с активностью, статистикой, списками, отзывами
- **Leaderboard** — рейтинг пользователей по активности

### 2.10 Книжные клубы (/clubs/)
- **Создание клубов** — название, описание, приватность (public/private), max участников
- **Роли** — owner, admin, member
- **Управление участниками** — приглашения, удаление, роли
- **Книги клуба** — расписание чтения (start/end даты), текущая книга, голосование за книги
- **Опросы (Polls)** — создание опросов, голосование, результаты
- **Обсуждения книг** — thread-чат для каждой книги клуба
- **Чат клуба** — real-time через WebSocket (Django Channels)
- **Присоединение** — public клубы без заявки, private — с одобрением

### 2.11 Подборки (/collections/)
- **Курируемые подборки** — создание, редактирование, публикация
- **Поиск по подборкам** — по названию, описанию, автору, книгам
- **Лайки** — пользователи ставят ♥ подборкам
- **Комментарии** — вложенные (replies), голосование (+1/-1), модерация

### 2.12 Тикеты и жалобы (/tickets/)
- **Обращения пользователей** — subject, body, приоритет
- **Жалобы (Reports)** — на книги, отзывы, рецензии, комментарии подборок
- **Ответы staff** — thread переписки внутри тикета
- **Статусы** — open, in_progress, closed
- **Фильтры и сортировка** — по типу, статусу, приоритету, дате

### 2.13 Уведомления (/notifications/)
- **Inbox-уведомления** — дружба, рецензии, клубы, тикеты, комментарии
- **Фильтр** — Все / Непрочитанные
- **Бейдж в навигации** — polling каждые 10 секунд (HTMX)
- **Массовая отметка прочитанным**
- **Redirect** — клик по уведомлению → переход на целевую страницу + пометка прочитанным

### 2.14 Чат (/chat/)
- **DM (direct messages)** — между двумя пользователями, real-time через WebSocket
- **Клубные чаты** — общий чат клуба
- **Thread-чаты** — обсуждение конкретной книги в клубе
- **Реакции на сообщения** — эмодзи-реакции
- **Список чатов** — сортировка по последнему сообщению, счётчик непрочитанных

### 2.15 Поиск (/search/)
- **Текстовый поиск** — по книгам, авторам, жанрам
- **Автокомплит** — подсказки при вводе
- **AI-поиск** — семантический поиск через LLM
- **История поиска** — сохранение запросов пользователя

### 2.16 Цены и магазины
- **Парсинг цен** — BeautifulSoup + requests по CSS-селекторам
- **История цен** — график динамики цены
- **Ссылки на магазины** — BookStore с product URL
- **Алерты на цену** — уведомление пользователя при снижении цены
- **Telegram/MAX/VK-уведомления** — отправка алертов и других событий через ботов

### 2.17 Публичный API (/api/v1/)
- **REST API** — книги, авторы (реализовано на Django REST Framework)
- **API Keys** — управление ключами, лимиты запросов
- **Пагинация** — page, page_size (max 100)
- **Аутентификация** — Bearer token / X-API-Key header
- **Swagger UI** — интерактивная документация на `/api/v1/swagger/`
- **ReDoc** — альтернативная документация на `/api/v1/redoc/`
- **OpenAPI Schema** — JSON схема на `/api/v1/schema/`
- **Endpoints**:
  - `GET /api/v1/books/` — список и поиск книг (параметры: q, ordering, page, page_size)
  - `GET /api/v1/books/{id}/` — детальная информация о книге
  - `GET /api/v1/authors/` — список и поиск авторов (параметры: q, page, page_size)
  - `GET /api/v1/authors/{id}/` — автор с его книгами (до 50)

### 2.18 Админ-панель пользователей (/users/admin-panel/)
- **Управление пользователями** — список, блокировка/разблокировка
- **История блокировок** — кто, когда, причина, до когда
- **Уведомления пользователям** — отправка сообщений от имени админа
- **Управление магазинами** — добавление, удаление
- **Управление уведомлениями** — массовые включение/выключение
- **Графики и аналитика** — демо графиков
- **Тесты** — страница запуска тестов (`/users/admin-panel/tests/`), возможность запускать отдельные тесты

### 2.19 AI Admin (/ai-admin/)
- **Настройки AI** — модель (OpenRouter), температура, max tokens
- **Email верификация** — включение/отключение обязательной верификации
- **Промпты** — настройка системных промптов для разных AI-фич

### 2.20 Дизайн и UX
- **Стиль «печатная машинка»** — шрифт Mltsvfont, монохромная палитра, линии вместо карточек
- **Тёмная тема** — CSS custom properties, переключение
- **Анимации** — entrance анимации для навигации и карточек
- **Reduced motion** — `@media (prefers-reduced-motion: reduce)`
- **Демо-страницы** — `/design-demos/`, `/typewriter-home-demo/`, `/typewriter-community-demo/`

### 2.21 Технические фичи
- **Celery tasks** — фоновая обработка: парсинг цен, AI-рекомендации, AI-чат, рассылки
- **Django Channels** — real-time чат, WebSocket
- **Кеширование** — Redis, кеш AI-рекомендаций
- **Rate limiting** — на критичных endpoint (AI-рекомендации, 3 запроса/5 мин)
- **Блокировка пользователей** — soft block с возможностью разблокировки
- **Тестирование** — pytest с pytest-django, покрытие кода через pytest-cov, запуск тестов через админ-панель

---

## 3. Стек технологий

| Слой | Технология |
|------|------------|
| Backend | Django 5.0.x, Python 3.12+ |
| REST API | Django REST Framework 3.15.1, drf-spectacular 0.27.2 |
| БД | PostgreSQL 14+ |
| Кеш / брокер | Redis 7 |
| Очереди | Celery 5.3.6 + django-celery-beat |
| Realtime | Django Channels + Daphne + channels-redis |
| Фронтенд | HTMX 1.17+, Alpine.js (inline), vanilla JS |
| Стили | Кастомный CSS, **без Bootstrap/Tailwind** |
| Тестирование | pytest 8.1.1, pytest-django 4.8.0, pytest-cov 5.0.0 |
| AI / LLM | OpenRouter API (OpenAI-совместимый endpoint) |
| Парсинг | BeautifulSoup4 + requests |
| Уведомления | Telegram Bot API, MAX Bot API, VK Bot API, Resend (email) |
| Изображения | Pillow |
| reCAPTCHA | Google reCAPTCHA v2 |

---

## 4. Архитектура URL

Корневой роутер: `config/urls.py`

```
/                     → core.urls        (home, community, design-демо)
/books/               → books.urls       (каталог, книга, цены, читалка, цитаты, заметки)
/users/               → users.urls       (регистрация, профиль, списки, импорт, leaderboard, admin-panel)
/search/              → search.urls      (поиск, автокомплит, AI-поиск)
/reviews/             → reviews.urls     (отзывы, рецензии, комментарии, модерация)
/tickets/             → tickets.urls
/social/              → social.urls
/collections/         → curated.urls
/graph/               → graph.urls
/ai-chat/             → ai_chat.urls
/clubs/               → clubs.urls
/chat/                → chat.urls
/ai-admin/            → ai_admin.urls
/api-dashboard/        → public_api.dashboard_urls
/api/v1/              → public_api.urls
/notifications/       → notifications.urls
/analytics/           → analytics.urls
/admin/               → Django Admin
```

### 4.1 books.urls — ключевые маршруты

```
/books/                                    catalog
/books/<pk>/                               book_detail
/books/toggle-list/                        toggle_list
/books/<pk>/request-price/                 request_price
/books/<pk>/price-status/                  price_status
/books/<pk>/price-chart/                   price_chart_data
/books/<pk>/price-alert/save/              price_alert_save
/books/<pk>/price-alert/delete/            price_alert_delete
/books/<book_id>/store-link/save/          store_link_save
/books/<book_id>/store-link/<store_id>/delete/  store_link_delete
/books/<pk>/progress/                      reading_progress_save
/books/<pk>/text/upload/                   book_text_upload
/books/<pk>/text/delete/                   book_text_delete
/books/<pk>/read/                          book_read
/books/<pk>/read/<chapter_order>/          book_read_chapter
/books/<pk>/read/progress/                 book_read_progress
/books/<pk>/quotes/                        quotes_partial
/books/<pk>/quotes/add/                     quote_add
/books/<pk>/quotes/<quote_pk>/delete/      quote_delete
/books/<pk>/notes/add/                     note_add
/books/<pk>/notes/list/                    note_list_for_book
/books/notes/<note_id>/delete/             note_delete
/books/<pk>/ai/summaries/                  book_ai_summaries
/books/<pk>/ai/quotes-extract/             book_ai_quotes_extract
/books/<pk>/ai/themes/                     book_ai_themes
/books/<pk>/ai/style/                      book_ai_style
/books/<pk>/chapter-search/                book_chapter_search
/books/add/                                book_add
/books/<pk>/edit/                          book_edit
/books/admin/delete/<pk>/                admin_delete_book
/books/admin/partial/                      admin_books_partial
/books/add/author/                        author_create_inline
/books/add/genre/                          genre_create_inline
/books/add/publisher/                     publisher_create_inline
/books/add/series/                         series_create_inline
/books/isbn-lookup/                        isbn_lookup
/books/<pk>/edition-data/                  edition_data
/books/editions/                          editions_list
/books/editions/create/                    edition_create
/books/editions/<pk>/edit/               edition_edit
/books/editions/<pk>/add-book/             edition_add_book
/books/editions/<pk>/remove-book/<book_id>/ edition_remove_book
/books/editions/<pk>/delete/              edition_delete
/books/editions/search-books/             edition_search_books
/books/authors/<pk>/                       author_detail
/books/authors/<pk>/edit/                  author_edit
/books/authors/<pk>/subscribe/            author_subscribe
/books/publishers/<pk>/                    publisher_detail
/books/publishers/<pk>/edit/              publisher_edit
/books/series/<pk>/                        series_detail
/books/<pk>/mood/<mood_id>/vote/          vote_mood
```

### 4.2 users.urls — ключевые маршруты

```
/users/register/                           register
/users/login/                              user_login
/users/logout/                             user_logout
/users/password-reset/ ...               стандартные Django auth views
/users/verify-email/<uidb64>/<token>/     verify_email
/users/profile/                            profile
/users/settings/                           account_settings
/users/telegram/save/                    save_telegram
/users/max/save/                          save_max
/users/vk/save/                           save_vk
/users/contacts/save/                    save_contacts
/users/lists/create/                       create_list
/users/lists/<list_id>/delete/           delete_list
/users/lists/export/                       export_lists
/users/import/                            import_library_view
/users/import/status/                     import_status
/users/onboarding/                         onboarding
/users/taste-data/                         taste_data
/users/ai-recs/refresh/                  ai_recs_refresh
/users/ai-recs/status/                    ai_recs_status
/users/admin-panel/                        admin_panel
/users/admin-panel/users/partial/          admin_users_partial
/users/admin-panel/users/<id>/block/      admin_block_user
/users/admin-panel/users/<id>/unblock/    admin_unblock_user
/users/admin-panel/users/<id>/card/       admin_user_card
/users/admin-panel/users/<id>/block-history/ admin_user_block_history
/users/admin-panel/users/<id>/notify-form/ admin_notify_form
/users/admin-panel/users/<id>/notify/     admin_send_notification
/users/admin-panel/stores/save/          admin_store_save
/users/admin-panel/stores/<id>/delete/   admin_store_delete
/users/admin-panel/notifications/toggle/   admin_notif_toggle
/users/admin-panel/charts-demo/          admin_charts_demo
/users/leaderboard/                          leaderboard
/users/<username>/activity/               user_activity_public
/users/<username>/                        user_profile_public
```

### 4.3 search.urls

```
/search/               search
/search/autocomplete/  search_autocomplete
/search/ai/            ai_search
```

### 4.4 reviews.urls

```
/reviews/<book_id>/create/          review_create
/reviews/<book_id>/page/              reviews_page
/reviews/<review_id>/moderate/        review_moderate
/reviews/<review_id>/delete/          review_delete
/reviews/<review_id>/like/            review_like
/reviews/critiques/<book_id>/create/ critique_create
/reviews/critiques/<pk>/             critique_detail
/reviews/critiques/<pk>/edit/         critique_edit
/reviews/critiques/<pk>/moderate/     critique_moderate
/reviews/critiques/<pk>/delete/      critique_delete
/reviews/critiques/<pk>/like/        critique_like
/reviews/critiques/<book_id>/page/    critiques_page
/reviews/critiques/<critique_id>/comments/      critique_comment_create
/reviews/critiques/comments/<pk>/edit/          critique_comment_edit
/reviews/critiques/comments/<pk>/delete/       critique_comment_delete
/reviews/critiques/comments/<pk>/vote/         critique_comment_vote
/reviews/critiques/<critique_id>/comments/page/ critique_comments_page
```

---

## 5. Ключевые модели

### 5.1 books/models.py

- **Genre** — жанр книги (`name`, unique)
- **Author** — автор (`name`, `bio`, `birth_year`)
- **Publisher** — издательство (`name`, `description`, `founded_year`, `country`, `city`, `website`)
- **Series** — книжная серия (`name`)
- **BookEdition** — группа изданий одного произведения (`name`)
- **Language** — язык (`name`, unique)
- **Book** — книга:
  - `title`, `isbn` (unique, nullable), `description`, `publication_year`, `pages`
  - `avg_rating` (денормализованный), `rating_count`
  - `cover_image`, `created_at`, `avg_price`, `price_last_requested`
  - `ai_themes` (JSON — темы из полного текста), `ai_style_profile` (JSON — стиль для рекомендаций)
  - FK: `publisher`, `series` (+ `series_order`), `edition_group`, `language`
  - M2M: `authors`, `genres`
- **UserList** — пользовательский список книг:
  - `user`, `name`, `is_default`, `is_public`
  - `sentiment_tag`: `positive` / `negative` / `neutral` / `wishlist`
  - M2M: `books`
  - Unique: `(user, name)`
- **Store** — онлайн-магазин (`name`, `base_url`, `icon`, `price_selector`, `is_active`)
- **BookStore** — связь книги и магазина (`book`, `store`, `product_url`, `current_price`, `in_stock`, `last_checked`)
- **BookPrice** — история цен (`book_store`, `price`, `created_at`)
- **BookTag** — AI-тег книги (`book`, `name`, `count`)
- **ReadingProgress** — прогресс чтения:
  - `user`, `book`, `current_page`, `current_chapter`, `scroll_offset`, `mode` (manual / reader), `updated_at`
- **BookText** — загруженный полный текст (EPUB/FB2):
  - `book` (OneToOne), `source_file`, `source_format`, `word_count`, `char_count`, `extract_status` (pending / ok / error)
- **BookChapter** — глава книги:
  - `book_text`, `order`, `title`, `html` (очищенный), `text` (plain), `word_count`, `summary`, `summary_status`
- **Quote** — цитата (`user`, `book`, `text`, `page_number`, `is_ai_generated`, `mood_tag`, `chapter`)
- **BookNote** — приватная заметка (`user`, `book`, `chapter`, `excerpt`, `note`, `created_at`, `updated_at`)
- **PriceAlert** — алерт на цену (`user`, `book`, `threshold`, `created_at`, `triggered_at`)
- **MoodTag** — тег настроения (`name`, `category`: atmosphere/pace/emotion/complexity, `icon`)
- **BookMood** — связь книги и mood (`book`, `mood`, `confidence`, `source`, `vote_count`)

### 5.2 users/models.py

- **UserProfile** — профиль пользователя:
  - `user` (OneToOne), `avatar`, `avatar_gradient` (8 вариантов), `bio`
  - `telegram_username`, `telegram_chat_id`, `max_username`, `max_user_id`, `vk_username`, `vk_user_id`
  - `email_verified`, `is_blocked`, `blocked_until`, `onboarding_done`
  - M2M: `favorite_genres`, `favorite_authors`
- **UserBlockHistory** — история блокировок:
  - `user`, `blocked_by`, `reason`, `blocked_at`, `blocked_until`, `unblocked_at`, `unblocked_by`, `unblock_reason`
- **AuthorSubscription** — подписка на автора (`user`, `author`)
- **Achievement** — достижение (`user`, `achievement_type`, `earned_at`)

### 5.3 reviews/models.py

- **Review** — отзыв (`user`, `book`, `rating` 1-5, `text`, `status`: pending/approved/rejected, `extracted_tag`)
- **ReviewLike** — лайк отзыва (`user`, `review`)
- **Critique** — расширенная рецензия (`user`, `book`, `title`, `body` (HTML), `body_source` (markdown), `body_format`, `final_rating`, `cover_image`, `status`, `extracted_tag`)
- **CritiqueCriterion** — критерий рецензии (`critique`, `name`, `rating` 1-5)
- **CritiqueComment** — комментарий к рецензии (`critique`, `user`, `parent`, `text`)
- **CritiqueCommentVote** — голос за комментарий (`user`, `comment`, `value` +1/-1)
- **CritiqueLike** — лайк рецензии (`user`, `critique`)

### 5.4 search/models.py

- **SearchHistory** — история поиска (`user` nullable, `query`, `results_count`, `created_at`)

---

## 6. Зависимости (requirements.txt)

```
Django>=5.0.3,<5.1
psycopg2-binary==2.9.9
celery==5.3.6
redis==5.0.4
django-celery-beat==2.6.0
Pillow==10.3.0
python-dotenv==1.0.1
django-htmx==1.17.3
django-widget-tweaks==1.5.0
beautifulsoup4==4.12.3
requests==2.31.0
lxml==5.2.1
markdown==3.7
openai>=1.0.0
whitenoise>=6.6.0
channels>=4.0.0
channels-redis>=4.2.0
daphne>=4.0.0
resend==2.4.0
```

---

## 7. Стиль кода

### Python
- Type hints везде, где применимо (`def func(param: int) -> str`)
- Docstrings на русском или английском — сохраняй существующий язык
- Django views: используй `@login_required`, `@require_GET` / `@require_POST`
- Celery-задачи: используй `bind=True`, `max_retries`, `soft_time_limit`, `time_limit`
- Импорты группируй: stdlib → Django → third-party → local

### Django
- **Шаблоны:** `core/templates/` — базовые, `app/templates/` — специфичные
- **HTMX:** partial-шаблоны начинаются с `_` (например, `books/_store_links.html`)
- **URL names:** lowercase_with_underscores
- **Модели:** `related_name` обязателен на FK/M2M; `db_index` на часто фильтруемых полях; `UniqueConstraint` в `Meta`

### JavaScript / Фронтенд
- Alpine.js — inline в шаблонах (`x-data`, `x-show`, `x-cloak`)
- HTMX — атрибуты на элементах (`hx-get`, `hx-target`, `hx-swap`)
- Vanilla JS для сложной логики; избегай jQuery

---

## 8. Стиль дизайна «печатная машинка» (Typewriter)

Проект использует **уникальный визуальный стиль «печатная машинка»**. При любых изменениях UI (новые страницы, компоненты, partials) агент обязан сохранять этот стиль.

### Шрифт
- **Основной:** `Mltsvfont` (monospace), загружается через `@font-face` из `core/static/fonts/`
- **Fallback:** `monospace`

### Цветовая палитра (светлая тема)
```css
--paper: #fafaf7;
--ink: #292920;
--muted: #8b8a83;
--soft: #c3c2bb;
--line: rgba(41, 41, 32, .32);
--line-strong: rgba(41, 41, 32, .78);
--cover: #9d9d99;
--cover-light: #d8d4c9;
```

### Цветовая палитра (тёмная тема)
```css
--paper: #20201d;
--ink: #ecebe4;
--muted: #b8b6ad;
--soft: #6d6a60;
--line: rgba(236, 235, 228, .25);
--line-strong: rgba(236, 235, 228, .62);
--cover: #5c5b55;
--cover-light: #33332f;
```

### Фон
- Текстурированный фон `paper-soft.jpg` с полупрозрачным оверлеем
- `background: linear-gradient(...), url("../img/design/paper-soft.jpg") center / cover fixed`

### Принципы компоновки
- **Нет скруглений** (`border-radius: 0` — дефолт)
- **Нет теней** — глубина создаётся через линии и отступы
- **Границы:** `border-bottom: 1px solid var(--line)` вместо карточек
- **Ссылки и кнопки:** `border-bottom: 1px solid transparent` → `currentColor` при hover
- **Сетки:** CSS Grid (`repeat()`, `minmax()`), не Bootstrap
- **Обложки книг:** `aspect-ratio: 2 / 3`, `object-fit: cover`, бордер `1px solid var(--line)`
- **Модальные окна:** `border: 1px solid var(--line-strong)`, фон с paper-texture
- **Страница книги (`/books/<pk>/`):** сохраняет функциональные формы/HTMX/Alpine, но визуально держится на линиях, прямых углах и монохромных текстовых маркерах вместо цветных emoji.
- **Граф связей (`/graph/<pk>/`):** D3-граф использует те же CSS-переменные, прямые углы, приглушённые цветные связи/легенду и текстовые карточки без теней, blur и броских relation-акцентов. Легенда работает как фильтр: отключение типа связи скрывает соответствующие линии и книги, которые больше не достижимы от центральной книги.
- **AI-generated marker:** для явно сгенерированного AI-контента допустима тонкая градиентная рамка с умеренным `border-radius` как осознанное исключение; пример — `/ai-generated-demo/`.

### Ключевые CSS-файлы
- `core/static/css/typewriter_home_demo.css` — базовый стиль (шрифт, цвета, layout)
- `core/static/css/typewriter_integrated.css` — интеграция с остальными страницами (навигация, читалка, поиск, футер)
- `core/static/css/ai_generated_demo.css` — демо маркировки AI-сгенерированного контента
- `core/static/css/main.css` — общие утилиты

### Анимации
- **Вход элементов:** `cubic-bezier(.2, .72, .18, 1)`
- **Ключевые кадры:** `navEnterLeft`, `navEnterRight`, `navLogoDrop`, `communityTitleAssemble`, `communityCardAssemble`, `communityLineAssemble`
- **Продолжительность:** 0.46–0.58s
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` — отключить анимации

---

## 9. Правила для AI-агентов

1. **Перед правками** прочитай этот файл (`AI_CONTEXT.md`). Он содержит контекст, которого нет в отдельных файлах.
2. **Если ты изменил:**
   - **Модели** (добавил/удалил поле, FK, M2M) → обнови раздел **5**
   - **URL** (новый маршрут, переименование) → обнови раздел **4**
   - **Зависимости** (новый пакет в `requirements.txt`) → обнови раздел **6**
   - **Дизайн** (новые CSS-переменные, компоненты) → обнови раздел **8**
3. **При создании новых страниц/шаблонов:**
   - Используй переменные `--paper`, `--ink`, `--muted`, `--line`
   - Шрифт: `font-family: "Mltsvfont", monospace;`
   - Не используй Bootstrap, Tailwind, скругления, тени
   - HTMX partials: префикс `_` в имени шаблона
4. **При работе с Celery-задачами:** добавляй `bind=True`, `max_retries`, `soft_time_limit`, `time_limit`
5. **При работе с моделями:** добавляй `related_name`, `db_index`, `UniqueConstraint` в `Meta.constraints`
6. **Язык интерфейса:** русский. Docstrings — русский или английский, сохраняй существующий стиль.

---

*Последнее обновление: 2026-04-30*

