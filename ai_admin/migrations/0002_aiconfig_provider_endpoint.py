"""Добавляет провайдера LLM (OpenRouter / AI Tunnel / custom) + поля для
кастомных кредов/endpoint в singleton AIConfig."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_admin", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiconfig",
            name="provider",
            field=models.CharField(
                max_length=16,
                default="openrouter",
                choices=[
                    ("openrouter", "OpenRouter (default)"),
                    ("aitunnel",   "AI Tunnel (aitunnel.ru)"),
                    ("custom",     "Свой OpenAI-совместимый endpoint"),
                ],
                help_text="Выбор OpenAI-совместимого провайдера. Пусто = базовая настройка из settings.py.",
            ),
        ),
        migrations.AddField(
            model_name="aiconfig",
            name="custom_api_key",
            field=models.CharField(
                max_length=256,
                blank=True,
                default="",
                help_text="API-ключ для aitunnel или custom-endpoint.",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="aiconfig",
            name="custom_base_url",
            field=models.CharField(
                max_length=256,
                blank=True,
                default="",
                help_text="Для provider=custom; у aitunnel используется стандартный URL.",
            ),
            preserve_default=False,
        ),
    ]
