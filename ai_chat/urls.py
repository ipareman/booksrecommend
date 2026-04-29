from django.urls import path
from . import views

urlpatterns = [
    path("<int:book_id>/",       views.book_chat,       name="book_chat"),
    path("<int:book_id>/send/",  views.book_chat_send,  name="book_chat_send"),
    path("<int:book_id>/status/", views.book_chat_status, name="book_chat_status"),
    path("<int:book_id>/clear/", views.book_chat_clear, name="book_chat_clear"),

    path("discovery/",            views.discovery_chat,     name="discovery_chat"),
    path("discovery/send/",       views.discovery_send,     name="discovery_send"),
    path("discovery/status/",     views.discovery_status,   name="discovery_status"),
    path("discovery/clear/",      views.discovery_clear,    name="discovery_clear"),
    path("discovery/dislike/",    views.discovery_dislike,  name="discovery_dislike"),
    path("discovery/elaborate/",  views.discovery_elaborate, name="discovery_elaborate"),
    path("discovery/elaborate/status/", views.discovery_elaborate_status, name="discovery_elaborate_status"),
    path("discovery/save-list/",  views.discovery_save_list, name="discovery_save_list"),
]
