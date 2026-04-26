"""
Вьюхи уведомлений:
- `list_view`          — страница `/notifications/` с фильтром «Все / Непрочитанные».
- `mark_all_read`      — POST, массово помечает непрочитанные как прочитанные.
- `redirect_and_read`  — клик по карточке: помечает одну запись + redirect на её URL.
- `badge_partial`      — HTMX-endpoint: возвращает HTML бейджа для polling'а в navbar.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def list_view(request):
    """Лента уведомлений с фильтром."""
    filter_mode = request.GET.get("filter", "all")
    qs = Notification.objects.for_user(request.user).select_related("actor")

    if filter_mode == "unread":
        qs = qs.filter(read_at__isnull=True)

    qs = qs.order_by("-updated_at")[:200]
    unread_count = Notification.objects.unread(request.user).count()

    ctx = {
        "notifications": qs,
        "filter_mode": filter_mode,
        "unread_count": unread_count,
    }
    return render(request, "notifications/list.html", ctx)


@login_required
@require_POST
def mark_all_read(request):
    """Массовая отметка — все непрочитанные → read_at=now()."""
    now = timezone.now()
    Notification.objects.unread(request.user).update(read_at=now)
    if request.headers.get("HX-Request"):
        # При HTMX-запросе достаточно вернуть пустой бейдж
        return render(request, "notifications/_badge.html", {"notifications_unread": 0})
    return redirect("notifications_list")


@login_required
def redirect_and_read(request, pk: int):
    """Клик по карточке: помечает прочитанной и делает 302 на её URL."""
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at", "updated_at"])
    target_url = n.url or "/"
    return HttpResponseRedirect(target_url)


@login_required
def badge_partial(request):
    """HTMX-фрагмент: только кусок HTML с бейджем непрочитанных (polling каждые 10с)."""
    try:
        unread = Notification.objects.unread(request.user).count()
    except Exception:
        unread = 0
    return render(request, "notifications/_badge.html", {"notifications_unread": unread})
