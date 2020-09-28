from django.conf.urls import url, include
from django.urls import path
from rest_framework import routers

from .views import AmplitudeConfigurationViewSet

# app_name = "amplitude"

router = routers.DefaultRouter()
router.register(r'amplitude', AmplitudeConfigurationViewSet)
# router.register(r'amplitude', AmplitudeConfigurationViewSet, basename='amplitude')

urlpatterns = [
    url(r'^integrations/', include(router.urls))
    # path('', include(router.urls))
]