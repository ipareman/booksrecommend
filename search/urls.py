from django.urls import path
from . import views

urlpatterns = [
    path("", views.search, name="search"),
    path("autocomplete/", views.autocomplete, name="search_autocomplete"),
    path("ai/", views.ai_search, name="ai_search"),
]
