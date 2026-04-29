from django.urls import path
from . import views

urlpatterns = [
    path("design-demos/", views.design_demos, name="design_demos"),
    path("typewriter-home-demo/", views.typewriter_home_demo, name="typewriter_home_demo"),
    path("typewriter-community-demo/", views.typewriter_community_demo, name="typewriter_community_demo"),
    path("community/", views.community, name="community"),
    path("", views.home, name="home"),
]
