from django.urls import path

from . import views


urlpatterns = [
    path("", views.ticket_list, name="ticket_list"),
    path("new/", views.ticket_create, name="ticket_create"),
    path("<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("<int:pk>/reply/", views.ticket_reply, name="ticket_reply"),
    path("report/<str:app_label>/<str:model>/<int:object_id>/", views.report_create, name="ticket_report_create"),
]
