"""
Единая обёртка над OpenAI-совместимым клиентом OpenRouter.
Автоматически пробует основную модель, при ошибках 429 / провайдерских сбоях
переключается на fallback-модели. Логирует каждый вызов в AIUsageLog.
"""

import json
import logging
import time
from types import SimpleNamespace
from django.conf import settings
from openai import OpenAI, APIStatusError, APIConnectionError, APITimeoutError

logger = logging.getLogger(__name__)


# ── DRY-RUN: фейковый ответ LLM без реального API-звонка ────────────────────

def _build_dry_run_response(kwargs: dict):
    """Возвращает объект, структурно похожий на OpenAI response.

    Поддерживает: `.choices[0].message.content`, `.choices[0].message.tool_calls`,
    `.usage.{prompt,completion,total}_tokens`. Если у запроса есть `tools` —
    делаем фейковый tool-call с пустыми аргументами для выбранного tool_choice.
    """
    tools = kwargs.get("tools") or []
    tool_choice = kwargs.get("tool_choice")

    tool_calls = None
    content = "[dry-run] Фейковый ответ. Включите AIConfig.dry_run_mode=False, чтобы получить настоящий ответ."

    # Если был явный tool_choice, собираем структурно валидный tool-call
    target_name = None
    if isinstance(tool_choice, dict):
        target_name = (tool_choice.get("function") or {}).get("name")
    if target_name:
        # Собираем фейковые пустые аргументы под схему tool
        fake_args = _empty_args_for_tool(tools, target_name)
        tool_calls = [SimpleNamespace(
            id="dry-run",
            type="function",
            function=SimpleNamespace(
                name=target_name,
                arguments=json.dumps(fake_args, ensure_ascii=False),
            ),
        )]
        content = None

    message = SimpleNamespace(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop", index=0)
    usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    return SimpleNamespace(choices=[choice], usage=usage, model="dry-run")


def _empty_args_for_tool(tools: list, target_name: str) -> dict:
    """Возвращает пустой dict, соответствующий JSONSchema.required переданного tool."""
    for t in tools or []:
        fn = t.get("function") or {}
        if fn.get("name") != target_name:
            continue
        params = fn.get("parameters") or {}
        return _empty_from_schema(params)
    return {}


def _empty_from_schema(schema: dict):
    """Рекурсивный дефолт по типу JSONSchema (для dry-run)."""
    t = (schema or {}).get("type")
    if t == "object":
        result = {}
        props = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name in props:
                result[name] = _empty_from_schema(props[name])
        return result
    if t == "array":
        return []
    if t == "string":
        return ""
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    return None


def _dry_run_enabled() -> bool:
    try:
        from ai_admin.models import AIConfig
        return bool(AIConfig.get().dry_run_mode)
    except Exception:
        return False


def _client() -> OpenAI:
    """
    Строит OpenAI-совместимого клиента.
    Provider / creds / base_url берём из AIConfig (выбор в админке),
    с откатом к settings.ANTHROPIC_* (OpenRouter по умолчанию).

    Явный `timeout` важен: без него SDK ждёт сеть 10 минут, в ASGI-режиме
    это приводит к Daphne-предупреждениям «Application instance took too
    long to shut down» при дисконнектах клиента.
    У нас есть собственный fallback-цикл по моделям, поэтому внутренние
    ретраи SDK отключены (`max_retries=0`).
    """
    api_key  = settings.ANTHROPIC_API_KEY
    base_url = settings.ANTHROPIC_BASE_URL
    try:
        from ai_admin.models import AIConfig
        api_key, base_url = AIConfig.get().resolve_endpoint()
    except Exception as exc:
        logger.warning("AIConfig.resolve_endpoint() failed, using settings defaults: %s", exc)

    http_timeout = float(getattr(settings, "AI_HTTP_TIMEOUT", 45.0))
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=http_timeout,
        max_retries=0,
    )


def _extra_headers() -> dict:
    # Эти заголовки нужны только OpenRouter (показываются в их дашборде).
    # Для aitunnel / custom endpoint шлём пусто, чтобы не мутить логи.
    provider = "openrouter"
    try:
        from ai_admin.models import AIConfig
        provider = AIConfig.get().provider or "openrouter"
    except Exception:
        pass
    if provider != "openrouter":
        return {}
    return {
        "HTTP-Referer": getattr(settings, "AI_HTTP_REFERER", ""),
        "X-Title":      getattr(settings, "AI_APP_TITLE", ""),
    }


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in (408, 429, 500, 502, 503, 504)
    msg = str(exc).lower()
    return "rate" in msg or "429" in msg or "timeout" in msg or "overloaded" in msg


def _resolve_models(tier: str) -> list[str]:
    """Модели с учётом AIConfig (БД переопределяет settings)."""
    default_main     = getattr(settings, "AI_MODEL_MAIN",      "google/gemma-4-31b-it:free")
    default_light    = getattr(settings, "AI_MODEL_LIGHT",     "google/gemma-4-26b-a4b-it:free")
    default_fallback = getattr(settings, "AI_MODEL_FALLBACK",  "openrouter/free")
    default_fb2      = getattr(settings, "AI_MODEL_FALLBACK2", "google/gemma-4-31b-it:free")

    cfg_main = cfg_light = cfg_fallback = ""
    try:
        from ai_admin.models import AIConfig
        cfg = AIConfig.get()
        cfg_main     = cfg.model_main or ""
        cfg_light    = cfg.model_light or ""
        cfg_fallback = cfg.model_fallback or ""
    except Exception:
        pass

    main_model = cfg_main  if tier == "main"  else cfg_light
    if not main_model:
        main_model = default_main if tier == "main" else default_light

    fallback = cfg_fallback or default_fallback

    models = [main_model, fallback, default_fb2]
    seen: set[str] = set()
    return [m for m in models if m and not (m in seen or seen.add(m))]


def _log_usage(*, feature, tier, model, user, status, error,
               prompt_preview, response_preview, usage, latency_ms):
    """Записать вызов в AIUsageLog. Ошибки при записи не должны ломать вызов."""
    try:
        from ai_admin.models import AIUsageLog
        AIUsageLog.objects.create(
            user              = user if (user and getattr(user, "is_authenticated", False)) else None,
            feature           = feature or "other",
            tier              = tier,
            model             = model or "",
            status            = status,
            error_message     = (error or "")[:2000],
            prompt_tokens     = (usage or {}).get("prompt_tokens", 0) or 0,
            completion_tokens = (usage or {}).get("completion_tokens", 0) or 0,
            total_tokens      = (usage or {}).get("total_tokens", 0) or 0,
            latency_ms        = latency_ms,
            request_preview   = (prompt_preview or "")[:500],
            response_preview  = (response_preview or "")[:500],
        )
    except Exception as exc:
        logger.warning("Failed to write AIUsageLog: %s", exc)


def _preview_messages(messages) -> str:
    """Берём последнее user-сообщение как превью промпта."""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content") or ""
            if isinstance(c, str):
                return c
    return ""


def _preview_response(resp) -> str:
    try:
        msg = resp.choices[0].message
        if msg.content:
            return msg.content
        if msg.tool_calls:
            return " | ".join(tc.function.arguments or "" for tc in msg.tool_calls)
    except Exception:
        pass
    return ""


def _usage_dict(resp) -> dict:
    try:
        u = resp.usage
        return {
            "prompt_tokens":     getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
            "total_tokens":      getattr(u, "total_tokens", 0) or 0,
        }
    except Exception:
        return {}


def chat_completion(*, tier: str = "main", feature: str = "other",
                    user=None, **kwargs):
    """
    Вызов LLM с автоматическим fallback и логированием в AIUsageLog.

    tier    : "main" | "light"
    feature : ключ из AIUsageLog.FEATURE_CHOICES (для статистики)
    user    : Django User — для атрибуции в логах
    kwargs  : messages, tools, tool_choice, max_tokens — как в OpenAI SDK.
    """
    # Проверка глобального тумблера этой фичи + dry-run
    dry_run = False
    try:
        from ai_admin.models import AIConfig
        cfg = AIConfig.get()
        if not cfg.feature_enabled(feature):
            raise RuntimeError(f"Функция «{feature}» отключена в AIConfig")
        dry_run = bool(cfg.dry_run_mode)
    except RuntimeError:
        raise
    except Exception:
        pass  # БД недоступна — работаем без гейта

    # Dry-run: возвращаем фейковый ответ, реального API-звонка не делаем
    if dry_run:
        prompt_preview = _preview_messages(kwargs.get("messages"))
        resp = _build_dry_run_response(kwargs)
        _log_usage(
            feature=feature, tier=tier, model="dry-run", user=user,
            status="dry_run", error="",
            prompt_preview=prompt_preview,
            response_preview=_preview_response(resp),
            usage={},  # нули — пусть видно, что токенов не потрачено
            latency_ms=0,
        )
        logger.info("chat_completion dry-run: feature=%s tier=%s (no API call)", feature, tier)
        return resp

    models = _resolve_models(tier)
    kwargs.setdefault("extra_headers", _extra_headers())
    prompt_preview = _preview_messages(kwargs.get("messages"))
    client = _client()

    last_exc: Exception | None = None
    for model in models:
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(model=model, **kwargs)
            latency = int((time.monotonic() - t0) * 1000)
            _log_usage(
                feature=feature, tier=tier, model=model, user=user,
                status="ok", error="",
                prompt_preview=prompt_preview,
                response_preview=_preview_response(resp),
                usage=_usage_dict(resp),
                latency_ms=latency,
            )
            return resp
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            retryable = _is_retryable(exc)
            is_rate_limit = isinstance(exc, APIStatusError) and exc.status_code == 429
            is_last = (model == models[-1])
            _log_usage(
                feature=feature, tier=tier, model=model, user=user,
                status=("rate_limit" if is_rate_limit else "error"),
                error=str(exc),
                prompt_preview=prompt_preview,
                response_preview="",
                usage={},
                latency_ms=latency,
            )
            last_exc = exc
            if retryable and not is_last:
                logger.warning("LLM model %s failed (%s), trying fallback", model, exc)
                continue
            raise
    raise last_exc  # type: ignore[misc]
