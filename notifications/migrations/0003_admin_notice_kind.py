from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_notificationsetting"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("new_message",        "Новое сообщение"),
                    ("new_book_by_author", "Новая книга у автора"),
                    ("friend_request",     "Заявка в друзья"),
                    ("friend_accepted",    "Заявка принята"),
                    ("book_recommended",   "Рекомендация книги"),
                    ("review_moderated",   "Отзыв/рецензия: модерация"),
                    ("critique_comment",   "Комментарий к рецензии"),
                    ("critique_reply",     "Ответ на комментарий"),
                    ("admin_notice",       "Уведомление от администрации"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
