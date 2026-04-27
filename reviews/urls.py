from django.urls import path
from . import views

urlpatterns = [
    path("<int:book_id>/create/",     views.review_create,   name="review_create"),
    path("<int:book_id>/page/",       views.reviews_page,    name="reviews_page"),
    path("<int:review_id>/moderate/", views.review_moderate, name="review_moderate"),
    path("<int:review_id>/delete/",   views.review_delete,   name="review_delete"),
    path("<int:review_id>/like/",     views.review_like,     name="review_like"),

    # Рецензии
    path("critiques/<int:book_id>/create/",          views.critique_create,   name="critique_create"),
    path("critiques/<int:pk>/",                      views.critique_detail,   name="critique_detail"),
    path("critiques/<int:pk>/edit/",                 views.critique_edit,     name="critique_edit"),
    path("critiques/<int:pk>/moderate/",             views.critique_moderate, name="critique_moderate"),
    path("critiques/<int:pk>/delete/",               views.critique_delete,   name="critique_delete"),
    path("critiques/<int:pk>/like/",                 views.critique_like,     name="critique_like"),
    path("critiques/<int:book_id>/page/",            views.critiques_page,    name="critiques_page"),

    # Комментарии к рецензиям
    path("critiques/<int:critique_id>/comments/",           views.comment_create,  name="critique_comment_create"),
    path("critiques/comments/<int:pk>/edit/",               views.comment_edit,    name="critique_comment_edit"),
    path("critiques/comments/<int:pk>/delete/",              views.comment_delete,  name="critique_comment_delete"),
    path("critiques/comments/<int:pk>/vote/",               views.comment_vote,    name="critique_comment_vote"),
    path("critiques/<int:critique_id>/comments/page/",      views.comments_page,   name="critique_comments_page"),
]
