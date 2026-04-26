from django.db import migrations


class Migration(migrations.Migration):
    """
    Подключаем расширение pg_trgm и создаём GIN-индексы
    для нечёткого поиска по названиям книг и именам авторов.
    """

    atomic = False

    dependencies = [
        ("search", "0002_books_fts_index"),
        ("books", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS books_title_trgm_idx
                ON books_book
                USING gin(title gin_trgm_ops);
            """,
            reverse_sql="DROP INDEX IF EXISTS books_title_trgm_idx;",
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS books_author_name_trgm_idx
                ON books_author
                USING gin(name gin_trgm_ops);
            """,
            reverse_sql="DROP INDEX IF EXISTS books_author_name_trgm_idx;",
        ),
    ]
