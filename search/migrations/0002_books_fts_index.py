from django.db import migrations


class Migration(migrations.Migration):
    """
    Добавляем GIN-индекс для Full Text Search по книгам.
    Конфигурация 'russian' должна быть доступна в PostgreSQL.

    atomic=False обязателен: CREATE INDEX CONCURRENTLY не может выполняться
    внутри транзакции, которую Django создаёт для миграций по умолчанию.
    """

    atomic = False  # ← вот и весь фикс

    dependencies = [
        ("search", "0001_initial"),
        ("books", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS books_fts_ru_idx
                ON books_book
                USING gin(
                    to_tsvector('russian',
                        coalesce(title, '') || ' ' || coalesce(description, '')
                    )
                );
            """,
            reverse_sql="DROP INDEX IF EXISTS books_fts_ru_idx;",
        ),
    ]
