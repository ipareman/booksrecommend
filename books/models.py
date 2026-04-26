from django.contrib.auth.models import User
from django.db import models


class Genre(models.Model):
    """Жанр книги (детектив, фэнтези и т.д.)."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Author(models.Model):
    """Автор книги с краткой биографией и годом рождения."""

    name = models.CharField(max_length=250)
    bio = models.TextField(blank=True)
    birth_year = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Publisher(models.Model):
    """Издательство, выпускающее книги."""

    name = models.CharField(max_length=250, unique=True)

    def __str__(self) -> str:
        return self.name


class Series(models.Model):
    """Книжная серия, к которой может относиться книга."""

    name = models.CharField(max_length=250)

    def __str__(self) -> str:
        return self.name


class BookEdition(models.Model):
    """Группа изданий одного произведения: объединяет разные `Book`
    (с разными издателями/ISBN/обложками), относящиеся к одной книге."""

    name = models.CharField(
        max_length=250,
        help_text="Каноническое название произведения (для админа)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Language(models.Model):
    """Язык оригинала или издания книги."""

    name = models.CharField(max_length=100, unique=True)

    def __str__(self) -> str:
        return self.name


class Book(models.Model):
    """Книга в каталоге с денормализованными полями рейтинга и цены."""

    title = models.CharField(max_length=250, db_index=True)
    isbn = models.CharField(max_length=20, unique=True, blank=True, null=True)
    description = models.TextField(blank=True)
    publication_year = models.IntegerField(db_index=True, null=True, blank=True)
    pages = models.PositiveIntegerField(null=True, blank=True)
    avg_rating = models.FloatField(default=0.0, db_index=True)
    rating_count = models.PositiveIntegerField(default=0)
    cover_image = models.ImageField(upload_to="covers/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    avg_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_last_requested = models.DateTimeField(null=True, blank=True)

    # AI-извлечено из полного текста книги (BookText):
    ai_themes = models.JSONField(
        default=list, blank=True,
        help_text="Список тем/мотивов книги, извлечённых AI из полного текста.",
    )
    ai_style_profile = models.JSONField(
        default=dict, blank=True,
        help_text="Профиль стиля (тон, темп, POV...) из первых глав — для spoiler-safe рекомендаций.",
    )

    authors = models.ManyToManyField(Author, blank=True, related_name="books")
    genres = models.ManyToManyField(Genre, blank=True, related_name="books")
    publisher = models.ForeignKey(
        Publisher,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="books",
    )
    series = models.ForeignKey(
        Series,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="books",
    )
    series_order = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Порядковый номер книги в серии",
    )
    edition_group = models.ForeignKey(
        "BookEdition",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="books",
        help_text="Группа изданий этой книги (разные издатели)",
    )
    language = models.ForeignKey(
        Language,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="books",
    )

    class Meta:
        ordering = ["-avg_rating"]

    def __str__(self) -> str:
        return self.title

    @property
    def stars_display(self) -> str:
        """Представление среднего рейтинга в виде пятизвёздочной строки."""
        r = round(self.avg_rating)
        return "★" * r + "☆" * (5 - r)


class UserList(models.Model):
    SENTIMENT_CHOICES = [
        ("positive", "Нравится"),
        ("negative", "Не нравится"),
        ("neutral", "Нейтральный"),
        ("wishlist", "Хочу прочитать"),
    ]
    """
    Пользовательский список книг.

    sentiment_tag задаёт эмоциональную окраску списка
    и влияет на качество персональных рекомендаций.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="book_lists")
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    sentiment_tag = models.CharField(
        max_length=20,
        default="neutral",
        choices=SENTIMENT_CHOICES,
        db_index=True,
    )
    books = models.ManyToManyField(Book, blank=True, related_name="in_lists")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="userlist_unique_name")
        ]

    def __str__(self) -> str:
        return f"{self.user.username} / {self.name}"


class Store(models.Model):
    """Онлайн-магазин, из которого парсятся цены на книги."""

    name = models.CharField(max_length=250)
    base_url = models.URLField()
    icon = models.CharField(max_length=10, blank=True)
    price_selector = models.CharField(
        max_length=500,
        blank=True,
        help_text="CSS-селектор цены (например: .price)",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class BookStore(models.Model):
    """Связь книги с магазином и текущей ценой в этом магазине."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="store_links")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="book_links")
    product_url = models.URLField(max_length=500)
    current_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    in_stock = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "store"], name="bookstore_unique")
        ]

    def __str__(self) -> str:
        return f"{self.book.title} @ {self.store.name}"


class BookPrice(models.Model):
    """История цен: одна запись = одна проверка цены в одном магазине."""
    book_store = models.ForeignKey(BookStore, on_delete=models.CASCADE, related_name="price_history")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.price} ({self.book_store}) от: {self.created_at}"


class BookTag(models.Model):
    """
    Тег книги, извлечённый Claude из одобренных отзывов.
    Глобальный пул: одно слово/фраза может встречаться у разных книг.
    count — сколько отзывов дали этот тег для этой книги.
    """
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=80)
    count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-count"]
        constraints = [
            models.UniqueConstraint(fields=["book", "name"], name="booktag_unique")
        ]

    def __str__(self):
        return f"{self.name} ({self.book.title}, ×{self.count})"


class ReadingProgress(models.Model):
    """Прогресс чтения: текущая страница пользователя в книге.

    `current_chapter` и `scroll_offset` заполняются встроенной читалкой
    (когда у книги есть загруженный полный текст). `current_page` остаётся
    для ручного ввода и обратной совместимости.

    `mode` определяет, как считается `percent()`:
      - "manual" — по current_page / book.pages;
      - "reader" — по current_chapter + scroll_offset.
    """

    MODE_MANUAL = "manual"
    MODE_READER = "reader"
    MODE_CHOICES = [
        (MODE_MANUAL, "Ручной ввод"),
        (MODE_READER, "Синхронизация с читалкой"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reading_progress")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reading_progress")
    current_page = models.PositiveIntegerField(default=0)
    # Для встроенной читалки:
    current_chapter = models.ForeignKey(
        "BookChapter", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    scroll_offset = models.FloatField(
        default=0.0,
        help_text="0.0-1.0 — относительная позиция скролла внутри текущей главы",
    )
    mode = models.CharField(
        max_length=10,
        choices=MODE_CHOICES,
        default=MODE_MANUAL,
        help_text="Как считать прогресс: ручной ввод или синхронизация с читалкой",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="readingprogress_unique")
        ]

    def percent(self):
        # Режим «читалка» — считаем по главам, если есть загруженный текст
        if self.mode == self.MODE_READER:
            text = getattr(self.book, "text", None)
            if text and self.current_chapter_id:
                total = text.chapters.count()
                if total > 0:
                    done = self.current_chapter.order + self.scroll_offset
                    return min(100, max(0, int(done / total * 100)))
            return 0
        # Режим «ручной» — по страницам
        if self.book.pages and self.book.pages > 0:
            return min(100, round(self.current_page / self.book.pages * 100))
        return 0

    def __str__(self):
        return f"{self.user.username} — {self.book.title}: {self.current_page}"


# ═══════════════════════════════════════════════════════════════════════════════
# ПОЛНЫЙ ТЕКСТ КНИГИ (EPUB / FB2) — для встроенной читалки и AI-фич
# ═══════════════════════════════════════════════════════════════════════════════

class BookText(models.Model):
    """Загруженный полный текст одной книги (EPUB или FB2).

    Файл сохраняется как есть. При успешной загрузке парсер заполняет
    `BookChapter` записи (очищенный HTML и plain text для AI).
    """

    FORMAT_EPUB = "epub"
    FORMAT_FB2  = "fb2"
    FORMAT_CHOICES = [
        (FORMAT_EPUB, "EPUB"),
        (FORMAT_FB2,  "FB2"),
    ]

    STATUS_PENDING = "pending"
    STATUS_OK      = "ok"
    STATUS_ERROR   = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "В обработке"),
        (STATUS_OK,      "Извлечено"),
        (STATUS_ERROR,   "Ошибка парсинга"),
    ]

    book = models.OneToOneField(
        Book, on_delete=models.CASCADE, related_name="text",
    )
    source_file   = models.FileField(upload_to="book_texts/")
    source_format = models.CharField(max_length=10, choices=FORMAT_CHOICES)

    word_count = models.PositiveIntegerField(default=0)
    char_count = models.PositiveIntegerField(default=0)

    extract_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    extract_error  = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Полный текст книги"

    def __str__(self):
        return f"Текст: {self.book.title} ({self.source_format}, {self.word_count} слов)"

    @property
    def is_ready(self) -> bool:
        return self.extract_status == self.STATUS_OK and self.chapters.exists()

    # Средняя скорость чтения — 250 слов/мин для художественной прозы
    READING_WPM = 250

    @property
    def estimated_minutes(self) -> int:
        """Оценка времени чтения всей книги в минутах (по словам)."""
        if not self.word_count:
            return 0
        return max(1, round(self.word_count / self.READING_WPM))

    @property
    def estimated_pages_equivalent(self) -> int:
        """Эквивалент страниц (~275 слов на стандартную страницу)."""
        if not self.word_count:
            return 0
        return max(1, round(self.word_count / 275))

    def humanize_reading_time(self) -> str:
        """Человекочитаемая длительность, напр. '4 ч 20 мин'."""
        minutes = self.estimated_minutes
        if minutes <= 0:
            return ""
        hours, mins = divmod(minutes, 60)
        if hours >= 1 and mins:
            return f"{hours} ч {mins} мин"
        if hours >= 1:
            return f"{hours} ч"
        return f"{mins} мин"


class BookChapter(models.Model):
    """Одна глава книги в виде чистого HTML и plain-текста.

    HTML — уже очищенный (допустимы только простые теги: p, br, em, strong, h2–h4, blockquote, ol, ul, li).
    Plain-text — для AI-поиска, цитат, чата с книгой.
    """

    SUMMARY_PENDING = "pending"
    SUMMARY_OK      = "ok"
    SUMMARY_ERROR   = "error"
    SUMMARY_CHOICES = [
        (SUMMARY_PENDING, "В очереди"),
        (SUMMARY_OK,      "Готово"),
        (SUMMARY_ERROR,   "Ошибка"),
    ]

    book_text = models.ForeignKey(BookText, on_delete=models.CASCADE, related_name="chapters")
    order = models.PositiveIntegerField(db_index=True,
                                        help_text="Порядковый номер главы (0-based).")
    title = models.CharField(max_length=300, blank=True)
    html  = models.TextField(help_text="Очищенный HTML главы для рендера в читалке.")
    text  = models.TextField(help_text="Plain text главы для AI.")
    word_count = models.PositiveIntegerField(default=0)

    # AI-саммари главы (для TOC-tooltip и чата со ссылками на главы)
    summary = models.TextField(
        blank=True,
        help_text="Краткое AI-содержание главы (1-2 предложения, без спойлеров финала).",
    )
    summary_status = models.CharField(
        max_length=10, choices=SUMMARY_CHOICES, default=SUMMARY_PENDING,
    )

    class Meta:
        ordering = ["order"]
        indexes = [
            models.Index(fields=["book_text", "order"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["book_text", "order"],
                                    name="bookchapter_order_unique"),
        ]

    def __str__(self):
        label = self.title or f"Глава {self.order + 1}"
        return label[:80]


class Quote(models.Model):
    """Цитата из книги, сохранённая пользователем или сгенерированная AI."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="quotes")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="quotes")
    text = models.TextField()
    page_number = models.PositiveIntegerField(null=True, blank=True)
    is_ai_generated = models.BooleanField(default=False)
    mood_tag = models.ForeignKey(
        "MoodTag", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quotes",
    )
    # Привязка к главе (для AI-цитат из полного текста и fair-use highlight-цитат)
    chapter = models.ForeignKey(
        "BookChapter", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
        help_text="Глава, из которой взята цитата (если применимо).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"«{self.text[:40]}» — {self.user.username}"


class BookNote(models.Model):
    """
    Приватная заметка пользователя к выделенному фрагменту книги.
    В отличие от Quote (публичная цитата) — не показывается другим юзерам,
    хранит и сам фрагмент текста, и комментарий пользователя «для себя».
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="book_notes")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="notes")
    chapter = models.ForeignKey(
        "BookChapter", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
        help_text="Глава, из которой взят фрагмент (если применимо).",
    )
    excerpt = models.TextField(help_text="Выделенный фрагмент текста.")
    note = models.TextField(
        blank=True,
        help_text="Комментарий пользователя к фрагменту (опционально).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "book", "-created_at"]),
        ]

    def __str__(self):
        return f"note «{self.excerpt[:40]}» — {self.user.username}"


class PriceAlert(models.Model):
    """Уведомление когда цена книги упадёт ниже порога."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="price_alerts")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="price_alerts")
    threshold = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    triggered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="pricealert_unique")
        ]

    def __str__(self):
        return f"{self.user.username} alert {self.book.title} < {self.threshold}₽"


class MoodTag(models.Model):
    """Структурированный тег настроения/атмосферы книги."""
    CATEGORY_CHOICES = [
        ("atmosphere", "Атмосфера"),
        ("pace", "Темп"),
        ("emotion", "Эмоция"),
        ("complexity", "Сложность"),
    ]
    name = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    icon = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.icon} {self.name}" if self.icon else self.name


class BookMood(models.Model):
    """Связь книги с mood-тегом (AI-классификация + пользовательские голоса)."""
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="moods")
    mood = models.ForeignKey(MoodTag, on_delete=models.CASCADE, related_name="book_moods")
    confidence = models.FloatField(default=1.0)
    source = models.CharField(max_length=20, default="ai")  # ai / user_vote
    vote_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["book", "mood"], name="bookmood_unique")
        ]

    def __str__(self):
        return f"{self.book.title} — {self.mood.name}"
