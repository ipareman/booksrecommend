from django.urls import path
from . import views

urlpatterns = [
    path("",             views.dashboard,        name="ai_admin_dashboard"),
    path("log/<int:log_id>/", views.log_detail,      name="ai_admin_log_detail"),
    path("tasks/",          views.tasks_view,         name="ai_admin_tasks"),
    path("tasks/partial/",  views.tasks_partial_view, name="ai_admin_tasks_partial"),
    path("tasks/revoke/",   views.task_revoke,        name="ai_admin_task_revoke"),
    path("tasks/enqueue/",  views.task_enqueue,       name="ai_admin_task_enqueue"),
    path("config/",      views.config_view,      name="ai_admin_config"),
]
