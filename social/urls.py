from django.urls import path
from . import views

urlpatterns = [
    path("friends/", views.friend_list, name="friend_list"),
    path("friends/request/<int:user_id>/", views.friend_request, name="friend_request"),
    path("friends/<int:friendship_id>/accept/", views.friend_accept, name="friend_accept"),
    path("friends/<int:friendship_id>/reject/", views.friend_reject, name="friend_reject"),
    path("friends/<int:user_id>/remove/", views.friend_remove, name="friend_remove"),
    path("recommend/<int:book_id>/", views.recommend_book, name="recommend_book"),
    path("recommend/<int:book_id>/friends/", views.recommend_friends_partial, name="recommend_friends_partial"),
    path("recommendations/", views.my_recommendations, name="my_recommendations"),
    path("feed/", views.activity_feed, name="activity_feed"),
    path("joint-recs/<int:friend_id>/", views.joint_recs, name="joint_recs"),
]
