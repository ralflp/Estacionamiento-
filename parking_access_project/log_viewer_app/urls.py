from django.urls import path
from . import views
from rest_framework.authtoken.views import obtain_auth_token

app_name = 'log_viewer_app'

urlpatterns = [
    # URLs existentes para vistas web
    path('logs/', views.access_log_list_view, name='access_log_list'),
    path('persons/', views.person_list_view, name='person_list'),
    path('persons/add/', views.person_create_view, name='person_create'),
    path('vehicles/', views.vehicle_list_view, name='vehicle_list'),
    path('vehicles/add/', views.vehicle_create_view, name='vehicle_create'),
    path('permissions/', views.permission_list_view, name='permission_list'),
    path('permissions/assign/', views.permission_create_view, name='permission_create'),
    path('permissions/<int:pk>/update/', views.permission_update_view, name='permission_update'),
    path('control-devices/', views.control_device_list_view, name='control_device_list'),
    path('control-devices/add/', views.control_device_create_view, name='control_device_create'),
    path('control-devices/<int:pk>/update/', views.control_device_update_view, name='control_device_update'),

    # Nueva URL para el Portal de Usuario
    path('portal/dashboard/', views.user_dashboard_view, name='user_dashboard'),

    # URLs para API Endpoints
    path('api/verify-access/', views.AccessVerificationAPIView.as_view(), name='api_verify_access'),
    path('api/user/permissions/', views.UserPermissionsListAPIView.as_view(), name='api_user_permissions'),
    path('api/auth/token/', obtain_auth_token, name='api_auth_token'),
]
