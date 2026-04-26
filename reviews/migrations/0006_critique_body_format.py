from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0005_critique_critiquecomment_critiquecommentvote_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="critique",
            name="body_source",
            field=models.TextField(
                blank=True, default="",
                help_text="Исходник в формате markdown (если формат — markdown)",
            ),
        ),
        migrations.AddField(
            model_name="critique",
            name="body_format",
            field=models.CharField(
                choices=[("html", "Rich (CKEditor)"), ("markdown", "Markdown")],
                default="html",
                help_text="В каком редакторе автор писал рецензию",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="critique",
            name="body",
            field=models.TextField(
                help_text="Отрендеренный HTML (санитайзится перед сохранением)",
            ),
        ),
    ]
