from .views import unread_counts


def social_counts(request):
    if request.user.is_authenticated:
        return {"social_unread": unread_counts(request.user)}
    return {"social_unread": 0}
