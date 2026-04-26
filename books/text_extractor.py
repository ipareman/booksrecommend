"""
Парсер EPUB и FB2 → список глав (title, html, text).

Без внешних зависимостей: только `lxml` и `beautifulsoup4`,
которые уже стоят в requirements.txt.

EPUB — это zip-архив:
  META-INF/container.xml → путь к OPF-файлу
  OPF-файл             → manifest (все файлы) + spine (порядок чтения)
  Каждый spine-item    → XHTML-файл с текстом

FB2 — это один XML-файл, иногда упакованный в .zip:
  <FictionBook>
    <description>...</description>
    <body>
      <section>
        <title>...</title>
        <p>...</p>
        <section>...вложенная...</section>
      </section>
    </body>

Разрешённые теги в выходном HTML:
  p, br, em, strong, i, b, h2, h3, h4, blockquote, ol, ul, li, hr
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Iterable

from bs4 import BeautifulSoup
from lxml import etree


ALLOWED_TAGS = {
    "p", "br", "em", "strong", "i", "b",
    "h2", "h3", "h4", "blockquote", "ol", "ul", "li", "hr",
}


@dataclass
class ExtractedChapter:
    title: str
    html: str
    text: str
    word_count: int


# ════════════════════════════════════════════════════════════════════════════
# УТИЛИТЫ ОЧИСТКИ
# ════════════════════════════════════════════════════════════════════════════

def _clean_html(raw_html: str) -> tuple[str, str]:
    """Из произвольного HTML/XHTML → (cleaned_html, plain_text).

    Удаляет всё, кроме разрешённых тегов. Атрибуты сносим полностью
    (нам не нужны class/style/id в читалке — шрифт и тема идут от темплейта).
    """
    if not raw_html:
        return "", ""

    # Чистим XML-декларацию, DOCTYPE и HTML-комментарии — BeautifulSoup их
    # иногда оставляет как текстовые узлы, попадает в выдачу.
    raw_html = re.sub(r"<\?xml[^?]*\?>", "", raw_html)
    raw_html = re.sub(r"<!DOCTYPE[^>]*>", "", raw_html, flags=re.IGNORECASE)
    raw_html = re.sub(r"<!--.*?-->", "", raw_html, flags=re.DOTALL)

    soup = BeautifulSoup(raw_html, "lxml")

    # Выкидываем служебные теги из <head> и <body>
    for bad in soup(["script", "style", "noscript", "link", "meta", "title", "head"]):
        bad.decompose()

    # Переименовываем заголовки: h1/h5/h6 → h2/h3/h4 (ограничиваем глубину)
    for tag in soup.find_all(["h1", "h5", "h6"]):
        tag.name = {"h1": "h2", "h5": "h4", "h6": "h4"}[tag.name]

    # Пробегаем по всем тегам: неразрешённые → разворачиваем, у разрешённых сносим атрибуты
    for tag in list(soup.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        else:
            tag.attrs = {}

    # Plain text — берём только из body, чтобы не попадали остатки head/title
    body = soup.body or soup
    text = body.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    # HTML без оборачивающих html/body
    html = "".join(str(c) for c in body.contents).strip()

    return html, text


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))


# ════════════════════════════════════════════════════════════════════════════
# EPUB
# ════════════════════════════════════════════════════════════════════════════

_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf":       "http://www.idpf.org/2007/opf",
    "dc":        "http://purl.org/dc/elements/1.1/",
    "xhtml":     "http://www.w3.org/1999/xhtml",
}


def _extract_epub(file_bytes: bytes) -> list[ExtractedChapter]:
    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
        # 1) Найти OPF-файл через container.xml
        try:
            container = zf.read("META-INF/container.xml")
        except KeyError:
            raise ValueError("Не найден META-INF/container.xml — это не EPUB.")

        cont_root = etree.fromstring(container)
        rootfile = cont_root.find(".//container:rootfile", _NS)
        if rootfile is None:
            raise ValueError("В container.xml нет rootfile.")
        opf_path = rootfile.get("full-path")
        if not opf_path:
            raise ValueError("В container.xml пустой full-path.")

        # 2) Распарсить OPF: manifest + spine
        opf_data = zf.read(opf_path)
        opf_root = etree.fromstring(opf_data)

        # manifest: id → href
        manifest = {}
        for item in opf_root.findall(".//opf:manifest/opf:item", _NS):
            item_id   = item.get("id")
            item_href = item.get("href")
            if item_id and item_href:
                manifest[item_id] = item_href

        # spine: порядок itemrefs
        spine_ids = []
        for ref in opf_root.findall(".//opf:spine/opf:itemref", _NS):
            idref = ref.get("idref")
            if idref and idref in manifest:
                spine_ids.append(idref)

        # Базовая директория OPF (чтобы склеить с href'ами)
        opf_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""

        chapters: list[ExtractedChapter] = []
        for sid in spine_ids:
            href = manifest[sid]
            full_path = f"{opf_dir}/{href}" if opf_dir else href
            # URL-decode (некоторые EPUB'ы кодируют пробелы как %20)
            import urllib.parse
            full_path = urllib.parse.unquote(full_path)

            try:
                raw = zf.read(full_path)
            except KeyError:
                # Файл из манифеста отсутствует — пропускаем
                continue

            try:
                raw_html = raw.decode("utf-8")
            except UnicodeDecodeError:
                raw_html = raw.decode("latin-1", errors="replace")

            # Вытащить заголовок: <title> или первый h1/h2
            title = ""
            try:
                mini = BeautifulSoup(raw_html, "lxml")
                t = mini.find(["h1", "h2", "h3"])
                if t:
                    title = t.get_text(strip=True)[:300]
                elif mini.title:
                    title = mini.title.get_text(strip=True)[:300]
            except Exception:
                pass

            html, text = _clean_html(raw_html)
            if not text.strip():
                # Пустая/служебная глава (обложка, copyright) — пропускаем
                continue

            chapters.append(ExtractedChapter(
                title=title,
                html=html,
                text=text,
                word_count=_word_count(text),
            ))

        if not chapters:
            raise ValueError("EPUB разобран, но в нём нет читаемых глав.")
        return chapters


# ════════════════════════════════════════════════════════════════════════════
# FB2
# ════════════════════════════════════════════════════════════════════════════

_FB2_NS = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}


def _fb2_section_to_html(section) -> tuple[str, str, str]:
    """Превращаем <section> FB2 в (title, html, text).

    Вложенные <section> не разворачиваем — каждый верхнеуровневый section
    становится отдельной главой; вложенные собираем плоско в ту же главу
    как подзаголовки.
    """
    title = ""
    title_el = section.find("fb:title", _FB2_NS)
    if title_el is not None:
        title = " ".join(t.strip() for t in title_el.itertext() if t.strip())[:300]

    # Собираем содержимое в подобие HTML
    parts: list[str] = []

    def walk(elem, depth: int = 0):
        tag_local = etree.QName(elem).localname

        if tag_local == "title" and depth == 0:
            # Заголовок главы уже вынесли отдельно — пропускаем
            return
        if tag_local == "title":
            level = min(4, 2 + depth)
            t = " ".join(t.strip() for t in elem.itertext() if t.strip())
            parts.append(f"<h{level}>{_escape(t)}</h{level}>")
            return
        if tag_local == "subtitle":
            t = " ".join(t.strip() for t in elem.itertext() if t.strip())
            parts.append(f"<h4>{_escape(t)}</h4>")
            return
        if tag_local == "p":
            t = _fb2_inline(elem)
            if t.strip():
                parts.append(f"<p>{t}</p>")
            return
        if tag_local == "empty-line":
            parts.append("<br>")
            return
        if tag_local == "epigraph" or tag_local == "cite":
            t = _fb2_inline(elem)
            if t.strip():
                parts.append(f"<blockquote>{t}</blockquote>")
            return
        if tag_local == "section":
            for child in elem:
                walk(child, depth + 1)
            return
        # poem, stanza → абзацы
        if tag_local in ("poem", "stanza"):
            for child in elem:
                walk(child, depth + 1)
            return
        if tag_local == "v":  # строка стиха
            t = _fb2_inline(elem)
            if t.strip():
                parts.append(f"<p>{t}</p>")
            return
        # всё остальное — только текст
        t = " ".join(x.strip() for x in elem.itertext() if x.strip())
        if t.strip():
            parts.append(f"<p>{_escape(t)}</p>")

    for child in section:
        walk(child, 0)

    html = "\n".join(parts)
    # plain
    plain = BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)
    plain = re.sub(r"\s+", " ", plain).strip()
    return title, html, plain


def _fb2_inline(elem) -> str:
    """Инлайновое преобразование: <emphasis> → <em>, <strong> → <strong>."""
    out_parts: list[str] = []
    if elem.text:
        out_parts.append(_escape(elem.text))
    for child in elem:
        local = etree.QName(child).localname
        inner = _fb2_inline(child)
        if local == "emphasis":
            out_parts.append(f"<em>{inner}</em>")
        elif local == "strong":
            out_parts.append(f"<strong>{inner}</strong>")
        else:
            out_parts.append(inner)
        if child.tail:
            out_parts.append(_escape(child.tail))
    return "".join(out_parts)


def _escape(s: str) -> str:
    if not s:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def _extract_fb2(file_bytes: bytes) -> list[ExtractedChapter]:
    # FB2 может быть обёрнут в zip
    data = file_bytes
    if file_bytes[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            inner = [n for n in zf.namelist()
                     if n.lower().endswith(".fb2") or n.lower().endswith(".xml")]
            if not inner:
                raise ValueError("В zip-архиве FB2 нет .fb2/.xml файла.")
            data = zf.read(inner[0])

    # lxml прощает BOM и неверную декларацию кодировки
    parser = etree.XMLParser(recover=True, huge_tree=True)
    try:
        root = etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"FB2 не является валидным XML: {e}")

    if root is None or etree.QName(root).localname != "FictionBook":
        raise ValueError("Корневой элемент не FictionBook — это не FB2.")

    body = root.find("fb:body", _FB2_NS)
    if body is None:
        # Некоторые FB2 используют пустой namespace
        body = root.find("body")
    if body is None:
        raise ValueError("В FB2 нет <body>.")

    chapters: list[ExtractedChapter] = []
    sections = body.findall("fb:section", _FB2_NS) or body.findall("section")

    if not sections:
        # Иногда всё содержимое лежит прямо в <body> без <section>
        title, html, text = _fb2_section_to_html(body)
        if text:
            chapters.append(ExtractedChapter(title=title or "Книга", html=html,
                                             text=text, word_count=_word_count(text)))
    else:
        for sec in sections:
            title, html, text = _fb2_section_to_html(sec)
            if not text.strip():
                continue
            chapters.append(ExtractedChapter(title=title,
                                             html=html, text=text,
                                             word_count=_word_count(text)))

    if not chapters:
        raise ValueError("FB2 разобран, но в нём нет читаемых глав.")
    return chapters


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════════════

def extract_book_text(file_bytes: bytes, fmt: str) -> list[ExtractedChapter]:
    """Извлечь список глав из EPUB или FB2.

    `fmt` ∈ {'epub', 'fb2'}. Возвращает непустой список ExtractedChapter,
    либо выбрасывает ValueError.
    """
    fmt = (fmt or "").lower()
    if fmt == "epub":
        return _extract_epub(file_bytes)
    if fmt == "fb2":
        return _extract_fb2(file_bytes)
    raise ValueError(f"Неподдерживаемый формат: {fmt}")


def detect_format(filename: str) -> str | None:
    """Угадать формат по расширению. Возвращает 'epub', 'fb2' или None."""
    name = (filename or "").lower()
    if name.endswith(".epub"):
        return "epub"
    if name.endswith(".fb2") or name.endswith(".fb2.zip"):
        return "fb2"
    return None
