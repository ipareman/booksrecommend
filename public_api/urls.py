from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework import permissions
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from . import views

# DRF Router for ViewSets
router = DefaultRouter()
router.register(r"books", views.BookViewSet, basename="book")
router.register(r"authors", views.AuthorViewSet, basename="author")

urlpatterns = [
    # DRF-spectacular OpenAPI schema and UI
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    
    # DRF ViewSets (REST API)
    path("", include(router.urls)),
    
    # Dashboard URLs (staff only)
    path("dashboard/", views.dashboard, name="api_dashboard"),
    path("dashboard/create-key/", views.create_key, name="api_create_key"),
    path("dashboard/revoke/<int:key_id>/", views.revoke_key, name="api_revoke_key"),
]
