from django.urls import path

from . import views


urlpatterns = [
    # Редирект-«считалка»: /b/<book>/s/<store>/
    path("b/<int:book_id>/s/<int:store_id>/", views.redirect_to_store, name="store_click"),

    # Admin-панель — partial content
    path("admin-panel/analytics/",         views.analytics_partial, name="admin_analytics"),
    path("admin-panel/analytics/refresh/", views.refresh_now,       name="admin_analytics_refresh"),

    # Deep-dive детальные страницы (каждая — отдельный URL со своими фильтрами)
    path("admin-panel/analytics/registrations/", views.detail_registrations, name="analytics_detail_registrations"),
    path("admin-panel/analytics/funnel/",        views.detail_funnel,        name="analytics_detail_funnel"),
    path("admin-panel/analytics/stores/",        views.detail_stores,        name="analytics_detail_stores"),
    path("admin-panel/analytics/books/",         views.detail_books,         name="analytics_detail_books"),
    path("admin-panel/analytics/moderation/",    views.detail_moderation,    name="analytics_detail_moderation"),
    path("admin-panel/analytics/cohorts/",       views.detail_cohorts,       name="analytics_detail_cohorts"),
]
