from django.urls import path

from . import views

urlpatterns = [
    path("docs/", views.docs, name="api_docs"),
    path("", views.api_root, name="api_root"),
    path("books/", views.books_list, name="api_books_list"),
    path("books/<int:pk>/", views.book_detail, name="api_book_detail"),
    path("authors/", views.authors_list, name="api_authors_list"),
    path("authors/<int:pk>/", views.author_detail, name="api_author_detail"),
]
