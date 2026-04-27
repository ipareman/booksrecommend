from django.urls import path
from . import views

urlpatterns = [
    path("", views.collections_list, name="collections_list"),
    path("<int:pk>/", views.collection_detail, name="collection_detail"),
    path("<int:pk>/like/", views.collection_like_toggle, name="collection_like_toggle"),
    path("<int:pk>/clone/", views.collection_clone, name="collection_clone"),
    path("<int:pk>/comments/add/", views.collection_comment_add, name="collection_comment_add"),
    path("comments/<int:pk>/edit/", views.collection_comment_edit, name="collection_comment_edit"),
    path("comments/<int:pk>/delete/", views.collection_comment_delete, name="collection_comment_delete"),
    path("comments/<int:pk>/vote/", views.collection_comment_vote, name="collection_comment_vote"),
    path("create/", views.collection_create, name="collection_create"),
    path("<int:pk>/edit/", views.collection_edit, name="collection_edit"),
    path("<int:pk>/delete/", views.collection_delete, name="collection_delete"),
    path("<int:pk>/publish/", views.collection_toggle_publish, name="collection_toggle_publish"),
    path("<int:pk>/add-book/", views.collection_add_book, name="collection_add_book"),
    path("<int:pk>/remove-book/<int:book_id>/", views.collection_remove_book, name="collection_remove_book"),
    path("<int:pk>/search-books/", views.collection_search_books, name="collection_search_books"),
]
