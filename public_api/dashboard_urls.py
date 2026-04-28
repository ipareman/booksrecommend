from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="api_dashboard"),
    path("keys/create/", views.create_key, name="api_key_create"),
    path("keys/<int:key_id>/revoke/", views.revoke_key, name="api_key_revoke"),
]
