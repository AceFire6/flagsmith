from django.conf.urls import url, include
from rest_framework_nested import routers

from features.views import FeatureViewSet
from segments.views import SegmentViewSet
from . import views


router = routers.DefaultRouter()
router.register(r'', views.ProjectViewSet, basename="project")

projects_router = routers.NestedSimpleRouter(router, r'', lookup="project")
projects_router.register(r'features', FeatureViewSet, basename="project-features")
projects_router.register(r'segments', SegmentViewSet, basename="project-segments")

app_name = "projects"

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^', include(projects_router.urls))
]
