from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0007_chatmessage_voice_message"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE chat_chatroom DROP COLUMN IF EXISTS book_id CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
