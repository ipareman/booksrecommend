from django.urls import path
from . import views

urlpatterns = [
    path("design-demos/", views.design_demos, name="design_demos"),
    path("typewriter-home-demo/", views.typewriter_home_demo, name="typewriter_home_demo"),
    path("", views.home, name="home"),
]
