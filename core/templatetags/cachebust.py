"""
Кеш-бастинг для статики. Использование в шаблоне:

    {% load cachebust %}
    <link rel="stylesheet" href="{% cachebust 'css/main.css' %}">

Тег возвращает URL вида `/static/css/main.css?v=<mtime>` — при изменении файла
mtime меняется, браузер обязан перезапросить файл. В проде, если используется
ManifestStaticFilesStorage, hash уже в имени — тег просто отдаст `{% static %}`
без query-string.
"""

from pathlib import Path

from django import template
from django.contrib.staticfiles.finders import find
from django.contrib.staticfiles.storage import staticfiles_storage

register = template.Library()


@register.simple_tag
def cachebust(path: str) -> str:
    """{% static path %} + ?v=<mtime>, где mtime — время модификации файла.

    Молча падает в обычный {% static %}, если файл не найден (например, в проде
    за CDN или при использовании ManifestStorage — там имя уже содержит хеш).
    """
    url = staticfiles_storage.url(path)
    # Если в storage уже hashed-имя (ManifestStaticFilesStorage), ?v не нужен.
    if "?" in url or "." in Path(url).name.rsplit(".", 1)[0]:
        # второй случай: имя содержит точку в «стебле» — признак хеш-суффикса
        # (e.g. main.1a2b3c.css) — тоже пропускаем.
        pass
    found = find(path)
    if not found:
        return url
    try:
        mtime = int(Path(found).stat().st_mtime)
    except OSError:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={mtime}"
