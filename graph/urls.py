from django.urls import path
from . import views

urlpatterns = [
    path("admin/", views.graph_admin, name="graph_admin"),
    path("admin/add/", views.graph_admin_add_relation, name="graph_admin_add"),
    path("admin/generate-auto/", views.graph_generate_auto, name="graph_generate_auto"),
    path("<int:pk>/", views.book_graph, name="book_graph"),
    path("<int:pk>/data/", views.book_graph_data, name="book_graph_data"),
    path("search-books/", views.graph_search_books, name="graph_search_books"),
    path("add-relation/", views.admin_add_relation, name="graph_add_relation"),
    path("relation/<int:relation_id>/delete/", views.admin_remove_relation, name="graph_remove_relation"),
]
