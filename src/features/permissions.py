from rest_framework.permissions import BasePermission

from projects.models import Project

ACTION_PERMISSIONS_MAP = {
    'retrieve': 'VIEW_PROJECT',
    'destroy': 'DELETE_FEATURE',
    'list': 'VIEW_PROJECT',
    'create': 'CREATE_FEATURE'
}


class FeaturePermissions(BasePermission):
    def has_permission(self, request, view):
        try:
            project_id = view.kwargs.get('project_pk') or request.data.get('project')
            project = Project.objects.get(id=project_id)

            if view.action in ACTION_PERMISSIONS_MAP:
                return request.user.has_project_permission(ACTION_PERMISSIONS_MAP.get(view.action), project)

            # move on to object specific permissions
            return view.detail

        except Project.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        # map of actions and their required permission
        if view.action in ACTION_PERMISSIONS_MAP:
            return request.user.has_project_permission(ACTION_PERMISSIONS_MAP[view.action], obj.project)

        if view.action in ('update', 'segments'):
            return request.user.is_project_admin(obj.project)

        return False
