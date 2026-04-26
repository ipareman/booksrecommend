from django.db.models import Q
from .models import Friendship


def get_friends(user):
    """Возвращает queryset User-ов, которые являются друзьями."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    friend_ids = set(
        Friendship.objects.filter(
            Q(from_user=user, status="accepted") | Q(to_user=user, status="accepted")
        ).values_list("from_user_id", "to_user_id")
        .distinct()
    )
    ids = set()
    for a, b in friend_ids:
        ids.add(a if a != user.pk else b)
    return User.objects.filter(pk__in=ids)


def get_friendship_status(user, other_user):
    """Возвращает (status, friendship) или (None, None)."""
    fs = Friendship.objects.filter(
        Q(from_user=user, to_user=other_user)
        | Q(from_user=other_user, to_user=user)
    ).first()
    if fs:
        return fs.status, fs
    return None, None


def are_friends(user, other_user):
    return Friendship.objects.filter(
        Q(from_user=user, to_user=other_user)
        | Q(from_user=other_user, to_user=user),
        status="accepted",
    ).exists()


def friend_ids_set(user):
    """Множество id друзей — для быстрой проверки в шаблонах."""
    rows = Friendship.objects.filter(
        Q(from_user=user, status="accepted") | Q(to_user=user, status="accepted")
    ).values_list("from_user_id", "to_user_id")
    ids = set()
    for a, b in rows:
        ids.add(a if a != user.pk else b)
    return ids
