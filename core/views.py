from django.shortcuts import render
from django.db.models import Count, Q
from books.models import Book, Genre, Author, MoodTag, Quote, Series


def _book_of_the_week():
    """Книга с наибольшим числом добавлений в списки за последние 7 дней."""
    from django.utils import timezone
    from datetime import timedelta
    from books.models import UserList
    week_ago = timezone.now() - timedelta(days=7)
    # Считаем по UserList.books через промежуточную таблицу
    from django.db.models import Count
    result = (
        Book.objects
        .filter(in_lists__created_at__gte=week_ago)
        .annotate(add_count=Count("in_lists"))
        .order_by("-add_count", "-avg_rating")
        .prefetch_related("authors", "genres")
        .first()
    )
    # Если за неделю ничего не добавляли — просто самая рейтинговая
    if not result:
        result = Book.objects.prefetch_related("authors", "genres").order_by("-avg_rating").first()
    return result


def home(request):
    from social.models import ActivityEvent
    ticker_events = list(
        ActivityEvent.objects
        .filter(event_type__in=["review", "join_club", "new_friendship"])
        .select_related("user", "book", "target_user")
        .order_by("-created_at")[:40]
    )
    # Подборки (опубликованные, с обложками первых 4 книг)
    from curated.models import Collection
    collections_qs = list(
        Collection.objects
        .filter(is_published=True)
        .annotate(num_books=Count("items"))
        .filter(num_books__gt=0)
        .order_by("-created_at")[:4]
    )
    collections = []
    for col in collections_qs:
        preview_books = list(
            Book.objects
            .filter(in_collections__collection=col)
            .exclude(cover_image="")
            .order_by("in_collections__order")[:4]
        )
        collections.append({"obj": col, "preview_books": preview_books})

    # Клубы (публичные, с участниками и текущей книгой)
    from clubs.models import BookClub, ClubBook
    clubs_qs = list(
        BookClub.objects
        .filter(is_public=True)
        .annotate(num_members=Count("memberships"))
        .order_by("-num_members")[:4]
    )
    clubs = []
    for club in clubs_qs:
        current_book = (
            ClubBook.objects
            .filter(club=club, is_current=True)
            .select_related("book")
            .first()
        )
        clubs.append({"obj": club, "current_book": current_book})

    # Серии книг (случайные, минимум 2 книги с обложками)
    series_qs = list(
        Series.objects
        .annotate(num_books=Count("books"))
        .filter(num_books__gte=2)
        .order_by("?")[:4]
    )
    home_series = []
    for s in series_qs:
        preview_books = list(
            s.books
            .exclude(cover_image="")
            .order_by("series_order", "publication_year")[:3]
        )
        if not preview_books:
            preview_books = list(s.books.order_by("series_order")[:3])
        home_series.append({
            "obj":           s,
            "preview_books": preview_books,
            "num_books":     s.num_books,
        })

    # Цитаты (случайные, с обложками)
    quotes = list(
        Quote.objects
        .filter(text__regex=r'.{40,}')  # минимум 40 символов
        .select_related("book", "user")
        .order_by("-created_at")[:6]
    )

    # Свежие рецензии
    from reviews.models import Review, Critique
    home_critiques = list(
        Critique.objects
        .filter(status="approved")
        .select_related("user", "user__profile", "book")
        .prefetch_related("book__authors")
        .order_by("-created_at")[:4]
    )

    # Свежие отзывы
    recent_reviews = list(
        Review.objects
        .filter(status="approved", text__regex=r'.{30,}')
        .select_related("user", "user__profile", "book")
        .prefetch_related("book__authors")
        .order_by("-created_at")[:6]
    )

    # Статистика платформы
    platform_stats = {
        "books": Book.objects.count(),
        "reviews": Review.objects.filter(status="approved").count(),
        "clubs": BookClub.objects.filter(is_public=True).count(),
        "collections": Collection.objects.filter(is_published=True).count(),
    }

    ctx = {
        "popular":         Book.objects.prefetch_related("authors", "genres").order_by("-rating_count")[:8],
        "newest":          Book.objects.prefetch_related("authors", "genres").order_by("-publication_year")[:8],
        "book_of_week":    _book_of_the_week(),
        "query":           request.GET.get("q", ""),
        "ticker_events":   ticker_events,
        "mood_tags":       MoodTag.objects.all(),
        "home_collections": collections,
        "home_series":     home_series,
        "home_clubs":      clubs,
        "home_quotes":     quotes,
        "home_critiques":  home_critiques,
        "home_reviews":    recent_reviews,
        "platform_stats":  platform_stats,
    }

    # Персональные рекомендации для авторизованных пользователей
    if request.user.is_authenticated:
        from books.recommendations import recommended_for_user
        try:
            ctx["personal_recs"] = recommended_for_user(request.user, limit=6)
        except Exception:
            ctx["personal_recs"] = []

        # Лента активности (последние 10 событий для главной)
        from social.models import ActivityEvent
        from social.helpers import friend_ids_set
        fids = friend_ids_set(request.user)
        friend_events = list(
            ActivityEvent.objects
            .filter(user_id__in=fids)
            .select_related("user", "book", "target_user")
            .prefetch_related("book__authors")[:5]
        )
        other_events = list(
            ActivityEvent.objects
            .exclude(user_id__in=fids | {request.user.pk})
            .select_related("user", "book", "target_user")
            .prefetch_related("book__authors")[:5]
        )
        ctx["feed_events"] = (friend_events + other_events)[:10]
        ctx["feed_friend_ids"] = fids

        # Для онбординг-модала: жанры и топ-авторы по количеству книг
        profile = getattr(request.user, "profile", None)
        if profile and not profile.onboarding_done:
            ctx["onboarding_genres"]  = Genre.objects.order_by("name")
            ctx["onboarding_authors"] = (
                Author.objects
                .annotate(book_count=Count("books"))
                .filter(book_count__gt=0)
                .order_by("-book_count")[:40]
            )

    return render(request, "core/home.html", ctx)


def custom_404(request, exception):
    return render(request, "404.html", status=404)


def custom_500(request):
    return render(request, "500.html", status=500)
