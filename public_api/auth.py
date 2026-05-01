import time
from functools import wraps

import rest_framework
from django.http import JsonResponse
from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiKey, ApiRequestLog


def _extract_key(request):
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.headers.get("X-API-Key", "").strip()


def _remote_addr(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR") or None


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """DRF authentication class for API keys."""

    def authenticate(self, request):
        raw_key = _extract_key(request)
        if not raw_key:
            return None

        api_key = ApiKey.objects.filter(
            key_hash=ApiKey.hash_key(raw_key),
            is_active=True,
        ).select_related("owner").first()

        if api_key is None:
            raise AuthenticationFailed("Invalid API key")

        api_key.last_used_at = timezone.now()
        api_key.save(update_fields=["last_used_at"])

        return (api_key.owner, api_key)


def api_key_required(view_func):
    """Legacy decorator for backward compatibility with non-DRF views."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        started = time.monotonic()
        raw_key = _extract_key(request)
        api_key = None
        status = 200

        if raw_key:
            api_key = ApiKey.objects.filter(
                key_hash=ApiKey.hash_key(raw_key),
                is_active=True,
            ).select_related("owner").first()

        if api_key is None:
            status = 401
            response = JsonResponse(
                {"error": "invalid_api_key", "detail": "Передайте API-ключ в Authorization: Bearer <key>."},
                status=status,
            )
        else:
            request.api_key = api_key
            api_key.last_used_at = timezone.now()
            api_key.save(update_fields=["last_used_at"])
            response = view_func(request, *args, **kwargs)
            status = response.status_code

        ApiRequestLog.objects.create(
            api_key=api_key,
            path=request.path[:255],
            method=request.method[:8],
            status_code=status,
            remote_addr=_remote_addr(request),
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return response

    return wrapper
