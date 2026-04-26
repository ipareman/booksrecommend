# Создание модели BookNote — приватные заметки пользователя к выделенному
# фрагменту книги. Хранит и сам фрагмент текста, и комментарий «для себя»,
# опционально привязан к главе. Для дашборда заметок добавлен индекс
# (user, book, -created_at).
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0011_book_ai_style_profile_book_ai_themes_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BookNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("excerpt", models.TextField(help_text="Выделенный фрагмент текста.")),
                ("note", models.TextField(blank=True, help_text="Комментарий пользователя к фрагменту (опционально).")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("book", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notes", to="books.book")),
                ("chapter", models.ForeignKey(blank=True, help_text="Глава, из которой взят фрагмент (если применимо).", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="books.bookchapter")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="book_notes", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="booknote",
            index=models.Index(fields=["user", "book", "-created_at"], name="books_bookn_user_id_31d862_idx"),
        ),
    ]
