from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path("register/",                               views.register,              name="register"),
    path("login/",                                  views.user_login,            name="login"),
    path("logout/",                                 views.user_logout,           name="logout"),

    # Сброс пароля
    path("password-reset/",
         auth_views.PasswordResetView.as_view(
             template_name="registration/password_reset_form.html",
             email_template_name="registration/password_reset_email.html",
             subject_template_name="registration/password_reset_subject.txt",
         ), name="password_reset"),
    path("password-reset/done/",
         auth_views.PasswordResetDoneView.as_view(
             template_name="registration/password_reset_done.html",
         ), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/",
         auth_views.PasswordResetConfirmView.as_view(
             template_name="registration/password_reset_confirm.html",
         ), name="password_reset_confirm"),
    path("password-reset/complete/",
         auth_views.PasswordResetCompleteView.as_view(
             template_name="registration/password_reset_complete.html",
         ), name="password_reset_complete"),
    path("verify-email/<uidb64>/<token>/",          views.verify_email,          name="verify_email"),
    path("profile/",                                views.profile,               name="profile"),
    path("settings/",                               views.account_settings,      name="account_settings"),
    path("telegram/save/",                          views.save_telegram,         name="save_telegram"),
    path("max/save/",                               views.save_max,              name="save_max"),
    path("vk/save/",                                views.save_vk,               name="save_vk"),
    path("contacts/save/",                          views.save_contacts,         name="save_contacts"),
    path("lists/create/",                           views.create_list,           name="create_list"),
    path("lists/<int:list_id>/delete/",             views.delete_list,           name="delete_list"),
    path("lists/export/",                           views.export_lists,          name="export_lists"),
    path("import/",                                 views.import_library_view,   name="import_library"),
    path("import/status/",                          views.import_status,         name="import_status"),
    path("onboarding/",                             views.onboarding,            name="onboarding"),
    path("taste-data/",                             views.taste_data,            name="taste_data"),
    path("sessions/terminate/",                     views.session_terminate,     name="session_terminate"),
    path("sessions/terminate-all/",                 views.sessions_terminate_all, name="sessions_terminate_all"),
    path("ai-recs/refresh/",                        views.ai_recs_refresh,       name="ai_recs_refresh"),
    path("ai-recs/status/",                         views.ai_recs_status,        name="ai_recs_status"),
    path("admin-panel/",                            views.admin_panel,           name="admin_panel"),
    path("admin-panel/users/partial/",              views.admin_users_partial,   name="admin_users_partial"),
    path("admin-panel/users/<int:user_id>/block/",        views.admin_block_user,         name="admin_block_user"),
    path("admin-panel/users/<int:user_id>/unblock/",      views.admin_unblock_user,       name="admin_unblock_user"),
    path("admin-panel/users/<int:user_id>/card/",          views.admin_user_card,           name="admin_user_card"),
    path("admin-panel/users/<int:user_id>/block-history/", views.admin_user_block_history, name="admin_user_block_history"),
    path("admin-panel/users/<int:user_id>/notify-form/", views.admin_notify_form, name="admin_notify_form"),
    path("admin-panel/users/<int:user_id>/notify/",     views.admin_send_notification,  name="admin_send_notification"),
    path("admin-panel/stores/save/",                  views.admin_store_save,         name="admin_store_save"),
    path("admin-panel/stores/<int:id>/delete/",       views.admin_store_delete,      name="admin_store_delete"),
    path("admin-panel/notifications/toggle/",          views.admin_notif_toggle,       name="admin_notif_toggle"),
    path("admin-panel/charts-demo/",                   views.admin_charts_demo,        name="admin_charts_demo"),
    path("admin-panel/tests/",                         views.admin_tests,              name="admin_tests"),
    path("admin-panel/tests/run/",                     views.admin_run_tests,          name="admin_run_tests"),
    path("leaderboard/",                               views.leaderboard,              name="leaderboard"),
    path("<str:username>/activity/",                views.user_activity_public,  name="user_activity_public"),
    path("<str:username>/",                          views.user_profile_public,   name="user_profile_public"),
]
