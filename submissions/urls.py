from django.urls import path
from . import views

urlpatterns = [
    path('', views.SubmissionListView.as_view(), name='submission-list'),
    path('create/', views.SubmissionCreateView.as_view(), name='submission-create'),
    path('run/', views.SubmissionRunView.as_view(), name='submission-run'),
    path('<int:submission_id>/', views.SubmissionDetailView.as_view(), name='submission-detail'),
]
