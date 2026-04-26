from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="moderationlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("review_approve",    "Отзыв одобрен"),
                    ("review_reject",     "Отзыв отклонён"),
                    ("critique_approve",  "Рецензия одобрена"),
                    ("critique_reject",   "Рецензия отклонена"),
                    ("user_block",        "Пользователь заблокирован"),
                    ("user_unblock",      "Пользователь разблокирован"),
                    ("user_notify",       "Отправлено уведомление пользователю"),
                    ("store_save",        "Магазин сохранён"),
                    ("store_delete",      "Магазин удалён"),
                    ("book_delete",       "Книга удалена"),
                    ("other",             "Иное"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
