from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat_list, name="chat_list"),
    path("dm/<int:user_id>/", views.chat_dm, name="chat_dm"),
    path("<int:room_id>/", views.chat_room, name="chat_room"),
    path("<int:room_id>/history/", views.chat_history, name="chat_history"),
    path("message/<int:message_id>/edit/", views.chat_edit_message, name="chat_edit_message"),
    path("message/<int:message_id>/react/", views.chat_toggle_reaction, name="chat_toggle_reaction"),
    path("books/search/", views.chat_book_search, name="chat_book_search"),
    path("<int:room_id>/voice/", views.chat_voice_upload, name="chat_voice_upload"),
]
