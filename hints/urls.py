from django.urls import path
from .views import HintConfigView, HintCreateView, HintDetailView

urlpatterns = [path('',HintCreateView.as_view(),name='hint-create'),path('config/',HintConfigView.as_view(),name='hint-config'),path('<int:request_id>/',HintDetailView.as_view(),name='hint-detail')]
