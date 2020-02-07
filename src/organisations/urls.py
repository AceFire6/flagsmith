from django.conf.urls import url, include
from rest_framework_nested import routers

from organisations.views import InviteViewSet
from users.views import FFAdminUserViewSet
from . import views

router = routers.DefaultRouter()
router.register(r'', views.OrganisationViewSet, basename="organisation")

organisations_router = routers.NestedSimpleRouter(router, r'', lookup="organisation")
organisations_router.register(r'invites', InviteViewSet, basename="organisation-invites")
organisations_router.register(r'users', FFAdminUserViewSet, basename='organisation-users')

app_name = "organisations"

urlpatterns = [
    url(r'^', include(router.urls)),
    url(r'^', include(organisations_router.urls)),
]
