from django.urls import path

from . import views

urlpatterns = [
    path("",                     views.list_view,          name="notifications_list"),
    path("mark-all-read/",       views.mark_all_read,      name="notifications_mark_all_read"),
    path("badge/",               views.badge_partial,      name="notifications_badge"),
    path("<int:pk>/go/",         views.redirect_and_read,  name="notifications_go"),
]
