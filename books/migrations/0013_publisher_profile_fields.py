from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0012_booknote"),
    ]

    operations = [
        migrations.AddField(
            model_name="publisher",
            name="city",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="publisher",
            name="country",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="publisher",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="publisher",
            name="founded_year",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="publisher",
            name="website",
            field=models.URLField(blank=True),
        ),
        migrations.AlterModelOptions(
            name="publisher",
            options={"ordering": ["name"]},
        ),
    ]
