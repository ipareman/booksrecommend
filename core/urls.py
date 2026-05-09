from django.urls import path
from . import views

urlpatterns = [
    path("design-demos/", views.design_demos, name="design_demos"),
    path("typewriter-home-demo/", views.typewriter_home_demo, name="typewriter_home_demo"),
    path("typewriter-community-demo/", views.typewriter_community_demo, name="typewriter_community_demo"),
    path("ai-generated-demo/", views.ai_generated_demo, name="ai_generated_demo"),
    path("week-books-demo/", views.week_books_demo, name="week_books_demo"),
    path("week-books-demo/gold/", views.week_book_gold_demo, name="week_book_gold_demo"),
    path("week-books-demo/silver/", views.week_book_silver_demo, name="week_book_silver_demo"),
    path("week-books-demo/bronze/", views.week_book_bronze_demo, name="week_book_bronze_demo"),
    path("community/", views.community, name="community"),
    path("subscription/", views.subscription_demo, name="subscription_demo"),
    path("subscription/yookassa/", views.subscription_yookassa_demo, name="subscription_yookassa_demo"),
    path("lucky/", views.lucky, name="lucky"),
    path("lucky/spin/", views.lucky_spin, name="lucky_spin"),
    path("", views.home, name="home"),
]
