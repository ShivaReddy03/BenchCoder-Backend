from django.urls import path
from .views import SolutionConfigView, SolutionCreateView, SolutionDetailView

urlpatterns = [
    path('config/', SolutionConfigView.as_view(), name='solution-config'),
    path('', SolutionCreateView.as_view(), name='solution-create'),
    path('<int:request_id>/', SolutionDetailView.as_view(), name='solution-detail'),
]
