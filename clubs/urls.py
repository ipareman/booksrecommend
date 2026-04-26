from django.urls import path
from . import views

urlpatterns = [
    path("", views.clubs_list, name="clubs_list"),
    path("create/", views.club_create, name="club_create"),
    path("invite/<str:token>/", views.club_invite_accept, name="club_invite_accept"),
    path("<int:pk>/", views.club_detail, name="club_detail"),
    path("<int:pk>/join/", views.club_join, name="club_join"),
    path("<int:pk>/leave/", views.club_leave, name="club_leave"),
    path("<int:pk>/members/<int:user_id>/remove/", views.club_remove_member, name="club_remove_member"),
    path("<int:pk>/delete/", views.club_delete, name="club_delete"),
    path("<int:pk>/rotate-invite/", views.club_rotate_invite, name="club_rotate_invite"),
    path("<int:pk>/add-book/", views.club_add_book, name="club_add_book"),
    path("<int:pk>/search-books/", views.club_search_books, name="club_search_books"),
    path("<int:pk>/update-book/<int:book_id>/", views.club_update_book, name="club_update_book"),
    path("<int:pk>/remove-book/<int:book_id>/", views.club_remove_book, name="club_remove_book"),
    path("<int:pk>/set-current/<int:book_id>/", views.club_set_current_book, name="club_set_current_book"),
    path("<int:pk>/vote-next/<int:book_id>/", views.club_vote_next_book, name="club_vote_next_book"),
    path("<int:pk>/polls/create/", views.club_create_poll, name="club_create_poll"),
    path("<int:pk>/polls/<int:poll_id>/vote/<int:option_id>/", views.club_vote_poll, name="club_vote_poll"),
    path("<int:pk>/polls/<int:poll_id>/close/", views.club_close_poll, name="club_close_poll"),
]
