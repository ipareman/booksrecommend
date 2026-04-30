from django.urls import path
from . import views

urlpatterns = [
    path("design-demos/", views.design_demos, name="design_demos"),
    path("typewriter-home-demo/", views.typewriter_home_demo, name="typewriter_home_demo"),
    path("typewriter-community-demo/", views.typewriter_community_demo, name="typewriter_community_demo"),
    path("community/", views.community, name="community"),
    path("lucky/", views.lucky, name="lucky"),
    path("lucky/spin/", views.lucky_spin, name="lucky_spin"),
    path("", views.home, name="home"),
]
