from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/",   admin.site.urls),
    path("",         include("core.urls")),
    path("books/",   include("books.urls")),
    path("users/",   include("users.urls")),
    path("search/",  include("search.urls")),
    path("reviews/", include("reviews.urls")),
    path("tickets/", include("tickets.urls")),
    path("social/",       include("social.urls")),
    path("collections/",  include("curated.urls")),
    path("graph/",        include("graph.urls")),
    path("ai-chat/",      include("ai_chat.urls")),
    path("clubs/",        include("clubs.urls")),
    path("chat/",         include("chat.urls")),
    path("ai-admin/",     include("ai_admin.urls")),
    path("api-dashboard/", include("public_api.dashboard_urls")),
    path("api/v1/",        include("public_api.urls")),
    path("notifications/", include("notifications.urls")),
    path("",               include("analytics.urls")),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "core.views.custom_404"
handler500 = "core.views.custom_500"
