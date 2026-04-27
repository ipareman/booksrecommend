from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from notifications.helpers import emit
from notifications.models import Notification

from .forms import TicketCreateForm, TicketReportForm, TicketResponseForm
from .models import Ticket


ALLOWED_REPORT_TARGETS = {
    ("books", "book"),
    ("reviews", "review"),
    ("reviews", "critique"),
    ("reviews", "critiquecomment"),
    ("curated", "collectioncomment"),
}


def _target_label(obj):
    meta = obj._meta
    if meta.model_name == "book":
        return f"Книга: {obj.title}"
    if meta.model_name == "review":
        return f"Отзыв на «{obj.book.title}»"
    if meta.model_name == "critique":
        return f"Рецензия: {obj.title}"
    if meta.model_name == "critiquecomment":
        return f"Комментарий к рецензии «{obj.critique.title}»"
    if meta.model_name == "collectioncomment":
        return f"Комментарий к подборке «{obj.collection.title}»"
    return str(obj)


def _target_url(obj):
    meta = obj._meta
    if meta.model_name == "book":
        return reverse("book_detail", kwargs={"pk": obj.pk})
    if meta.model_name == "review":
        return reverse("book_detail", kwargs={"pk": obj.book_id}) + f"#review-{obj.pk}"
    if meta.model_name == "critique":
        return reverse("critique_detail", kwargs={"pk": obj.pk})
    if meta.model_name == "critiquecomment":
        return reverse("critique_detail", kwargs={"pk": obj.critique_id}) + f"#comment-{obj.pk}"
    if meta.model_name == "collectioncomment":
        return reverse("collection_detail", kwargs={"pk": obj.collection_id}) + f"#collection-comment-{obj.pk}"
    return ""


def _visible_tickets(user):
    qs = Ticket.objects.select_related("user", "responded_by", "target_ct")
    if user.is_staff:
        return qs
    return qs.filter(user=user)


@login_required
def ticket_list(request):
    tickets = _visible_tickets(request.user)

    kind = request.GET.get("kind", "").strip()
    status = request.GET.get("status", "").strip()
    sort = request.GET.get("sort", "-updated").strip()
    q = request.GET.get("q", "").strip()

    if kind in {Ticket.KIND_REQUEST, Ticket.KIND_REPORT}:
        tickets = tickets.filter(kind=kind)
    if status in {choice[0] for choice in Ticket.STATUS_CHOICES}:
        tickets = tickets.filter(status=status)
    if q:
        tickets = tickets.filter(
            Q(subject__icontains=q)
            | Q(body__icontains=q)
            | Q(target_label__icontains=q)
            | Q(user__username__icontains=q)
        )

    if sort == "priority":
        tickets = tickets.order_by("priority", "-updated_at")
    else:
        ordering = {
            "-updated": "-updated_at",
            "updated": "updated_at",
            "-created": "-created_at",
            "created": "created_at",
        }.get(sort, "-updated_at")
        tickets = tickets.order_by(ordering)

    return render(request, "tickets/list.html", {
        "tickets": tickets,
        "kind": kind,
        "status": status,
        "sort": sort,
        "q": q,
        "status_choices": Ticket.STATUS_CHOICES,
    })


@login_required
def ticket_create(request):
    if request.method == "POST":
        form = TicketCreateForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.user = request.user
            ticket.kind = Ticket.KIND_REQUEST
            ticket.save()
            messages.success(request, "Обращение создано.")
            return redirect("ticket_detail", pk=ticket.pk)
    else:
        form = TicketCreateForm()
    return render(request, "tickets/form.html", {"form": form, "title": "Новое обращение"})


@login_required
def report_create(request, app_label, model, object_id):
    if (app_label, model) not in ALLOWED_REPORT_TARGETS:
        raise PermissionDenied

    ct = get_object_or_404(ContentType, app_label=app_label, model=model)
    obj = get_object_or_404(ct.model_class(), pk=object_id)
    label = _target_label(obj)

    if request.method == "POST":
        form = TicketReportForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.user = request.user
            ticket.kind = Ticket.KIND_REPORT
            ticket.subject = f"Жалоба: {label}"[:180]
            ticket.target = obj
            ticket.target_label = label
            ticket.target_url = _target_url(obj)
            ticket.save()
            messages.success(request, "Жалоба отправлена.")
            return redirect(ticket.target_url or "ticket_list")
    else:
        form = TicketReportForm()
    return render(request, "tickets/report_form.html", {"form": form, "target_label": label, "target_url": _target_url(obj)})


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(_visible_tickets(request.user), pk=pk)
    response_form = TicketResponseForm(instance=ticket) if request.user.is_staff else None
    return render(request, "tickets/detail.html", {"ticket": ticket, "response_form": response_form})


@login_required
@require_POST
def ticket_reply(request, pk):
    if not request.user.is_staff:
        raise PermissionDenied

    ticket = get_object_or_404(Ticket, pk=pk)
    form = TicketResponseForm(request.POST, instance=ticket)
    if not form.is_valid():
        return render(request, "tickets/detail.html", {"ticket": ticket, "response_form": form})

    response = form.cleaned_data["admin_response"].strip()
    ticket = form.save(commit=False)
    ticket.responded_by = request.user
    ticket.responded_at = ticket.responded_at or None
    if response:
        ticket.mark_answered(request.user, response)
        emit(
            user=ticket.user,
            kind=Notification.KIND_ADMIN_NOTICE,
            actor=request.user,
            target=ticket,
            text=f"Ответ на тикет #{ticket.pk}: {response[:180]}",
            url=ticket.get_absolute_url(),
            extra={"ticket_id": ticket.pk},
        )
        messages.success(request, "Ответ отправлен пользователю.")
    else:
        ticket.save(update_fields=["status", "admin_response", "responded_by", "responded_at", "updated_at"])
        messages.success(request, "Тикет обновлен.")

    return redirect("ticket_detail", pk=ticket.pk)
