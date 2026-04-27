# Repair migration for deployments where chat.0004 was applied before
# room_type max_length changed to 16.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_ensure_club_book_thread_table"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE chat_chatroom ALTER COLUMN room_type TYPE varchar(16);",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
