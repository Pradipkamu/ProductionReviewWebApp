from fastapi import HTTPException, Request
from .enums import UserRole

WRITE_ROLES = {
    'mis': {'PRODUCTION', 'PLANNING'}, 'process': {'PRODUCTION'}, 'oee': {'PRODUCTION'},
    'schedules': {'PLANNING'}, 'schedule': {'PLANNING'}, 'quality': {'QUALITY'},
    'vendor': {'PURCHASE', 'VENDOR', 'PRODUCTION'}, 'import': {'PLANNING', 'QUALITY', 'PRODUCTION'},
    'actions': {'PRODUCTION', 'QUALITY', 'PLANNING', 'PURCHASE', 'DISPATCH', 'VENDOR', 'MANAGEMENT'},
    'reviews': {'MANAGEMENT', 'PRODUCTION', 'QUALITY', 'PLANNING'},
    'masters': {'PLANNING'}, 'governance': {'MANAGEMENT'}, 'insights': {'MANAGEMENT'},
    'capacity': {'PLANNING', 'PRODUCTION'},
}

def enforce_api_policy(user, request: Request):
    path = request.url.path
    if user.must_change_password and path not in {'/api/auth/me', '/api/auth/change-password'}:
        raise HTTPException(403, 'Password change required before accessing the application')
    if path.startswith('/api/auth/users') or path.startswith('/api/masters/users'):
        if user.role != UserRole.ADMIN:
            raise HTTPException(403, 'Only ADMIN can manage users')
    if request.method in {'GET', 'HEAD', 'OPTIONS'} or path == '/api/auth/change-password':
        return
    section = path.split('/')[2] if len(path.split('/')) > 2 else ''
    if user.role == UserRole.ADMIN:
        return
    # OEE/loss action creation is an action-management write even though the
    # source endpoint lives under /oee. Management may raise the action without
    # receiving permission to edit the underlying production record.
    if section == 'oee' and path.endswith('/raise-action') and user.role.value in WRITE_ROLES['actions']:
        return
    if section == 'insights' and '/reminders/' in path and user.role.value != 'VIEW_ONLY':
        return
    if user.role.value not in WRITE_ROLES.get(section, set()):
        raise HTTPException(403, f'{user.role.value} cannot modify {section}')


def validate_password(password: str):
    if len(password) < 12 or len(password) > 128 or not any(c.isupper() for c in password) or not any(c.islower() for c in password) or not any(c.isdigit() for c in password) or not any(not c.isalnum() for c in password):
        raise HTTPException(422, 'Use 12–128 characters including uppercase, lowercase, a number and a symbol')
