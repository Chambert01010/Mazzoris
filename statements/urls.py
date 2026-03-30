from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("process/<str:bank_name>/", views.process_statement, name="process_statement"),
]
