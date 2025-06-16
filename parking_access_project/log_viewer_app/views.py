from django.shortcuts import render, redirect, get_object_or_404
from .models import AccessLog, Person, Vehicle, AccessPermission, ControlDevice, AccessPoint # AccessPoint explicit
from .forms import PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm
from django.contrib.auth.decorators import login_required
import logging
from django.db.models import Q

logger = logging.getLogger(__name__)

# DRF Imports
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.authtoken.models import Token # Nueva importación para Token

from .serializers import (
    AccessRequestSerializer, AccessResponseSerializer,
    AccessPermissionSerializer
)
from .utils import verify_access_with_models
from django.utils import timezone


# Django Template Views
def access_log_list_view(request):
    logs = AccessLog.objects.all().order_by('-timestamp')
    context = {'access_logs': logs, 'page_title': 'Registros de Acceso'}
    return render(request, 'log_viewer_app/access_log_list.html', context)

def person_list_view(request):
    persons = Person.objects.all().order_by('full_name')
    context = {'persons': persons, 'page_title': 'Lista de Personas'}
    return render(request, 'log_viewer_app/person_list.html', context)

def person_create_view(request):
    if request.method == 'POST':
        form = PersonForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:person_list')
    else:
        form = PersonForm()
    context = {'form': form, 'page_title': 'Añadir Nueva Persona'}
    return render(request, 'log_viewer_app/person_form.html', context)

def vehicle_list_view(request):
    vehicles = Vehicle.objects.all().select_related('owner').order_by('license_plate')
    context = {'vehicles': vehicles, 'page_title': 'Lista de Vehículos'}
    return render(request, 'log_viewer_app/vehicle_list.html', context)

def vehicle_create_view(request):
    if request.method == 'POST':
        form = VehicleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:vehicle_list')
    else:
        form = VehicleForm()
    context = {'form': form, 'page_title': 'Añadir Nuevo Vehículo'}
    return render(request, 'log_viewer_app/vehicle_form.html', context)

def permission_list_view(request):
    permissions = AccessPermission.objects.all().select_related('person', 'access_point').order_by('person__full_name', 'access_point__name')
    context = {'permissions': permissions, 'page_title': 'Lista de Permisos de Acceso'}
    return render(request, 'log_viewer_app/permission_list.html', context)

def permission_create_view(request):
    if request.method == 'POST':
        form = AccessPermissionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:permission_list')
    else:
        form = AccessPermissionForm()
    context = {'form': form, 'page_title': 'Asignar Nuevo Permiso de Acceso'}
    return render(request, 'log_viewer_app/permission_form.html', context)

def permission_update_view(request, pk):
    permission = get_object_or_404(AccessPermission, pk=pk)
    if request.method == 'POST':
        form = AccessPermissionForm(request.POST, instance=permission)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:permission_list')
    else:
        form = AccessPermissionForm(instance=permission)

    context = {
        'form': form,
        'permission_instance': permission,
        'page_title': f"Editar Permiso: {permission.person.full_name} en {permission.access_point.name}"
    }
    return render(request, 'log_viewer_app/permission_form.html', context)

def control_device_list_view(request):
    devices = ControlDevice.objects.all().select_related('access_point').order_by('name')
    context = {'devices': devices, 'page_title': 'Lista de Dispositivos de Control'}
    return render(request, 'log_viewer_app/control_device_list.html', context)

def control_device_create_view(request):
    if request.method == 'POST':
        form = ControlDeviceForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:control_device_list')
    else:
        form = ControlDeviceForm()
    context = {'form': form, 'page_title': 'Añadir Nuevo Dispositivo de Control'}
    return render(request, 'log_viewer_app/control_device_form.html', context)

def control_device_update_view(request, pk):
    device = get_object_or_404(ControlDevice, pk=pk)
    if request.method == 'POST':
        form = ControlDeviceForm(request.POST, instance=device)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:control_device_list')
    else:
        form = ControlDeviceForm(instance=device)
    context = {'form': form, 'device': device, 'page_title': f'Editar Dispositivo: {device.name}'}
    return render(request, 'log_viewer_app/control_device_form.html', context)

@login_required
def user_dashboard_view(request):
    user = request.user
    person_profile = None
    user_permissions = []
    user_vehicles = []

    try:
        person_profile = Person.objects.get(user=user)
        if person_profile:
            now_date = timezone.now().date()
            user_permissions = AccessPermission.objects.filter(
                person=person_profile,
                is_active=True
            ).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=now_date)
            ).select_related('access_point').order_by('access_point__name')

            user_vehicles = Vehicle.objects.filter(owner=person_profile).order_by('license_plate')

    except Person.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Error buscando Person profile o datos relacionados para user {user.username}: {e}")
        pass

    context = {
        'current_user': user,
        'person_profile': person_profile,
        'user_permissions': user_permissions,
        'user_vehicles': user_vehicles,
        'page_title': 'Mi Portal de Usuario'
    }
    return render(request, 'log_viewer_app/user_dashboard.html', context)

@login_required
def qr_scanner_page_view(request):
    user = request.user
    access_points = AccessPoint.objects.all().order_by('name')
    token_string = ""
    try:
        token_obj, created = Token.objects.get_or_create(user=user)
        if created:
            logger.info(f"Nuevo token de API creado para el usuario {user.username} para la página del escáner QR.")
        token_string = token_obj.key
    except Exception as e:
        logger.error(f"Error al obtener o crear token para {user.username} en qr_scanner_page_view: {e}")

    context = {
        'access_points': access_points,
        'user_auth_token': token_string,
        'page_title': 'Escáner de Códigos QR'
    }
    return render(request, 'log_viewer_app/qr_scanner_page.html', context)


# --- API Views ---

class AccessVerificationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = AccessRequestSerializer(data=request.data)
        if serializer.is_valid():
            qr_identifier = serializer.validated_data['qr_identifier']
            access_point_name = serializer.validated_data['access_point_name']

            access_granted = verify_access_with_models(qr_identifier, access_point_name)

            person_name_for_response = None
            try:
                person = Person.objects.get(identifier=qr_identifier)
                person_name_for_response = person.full_name
            except Person.DoesNotExist:
                pass

            response_data = {
                'access_granted': access_granted,
                'message': "Acceso Permitido" if access_granted else "Acceso Denegado",
                'person_name': person_name_for_response,
                'access_point_name': access_point_name,
                'timestamp': timezone.now()
            }
            response_serializer = AccessResponseSerializer(data=response_data)
            if response_serializer.is_valid(raise_exception=True):
                return Response(response_serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserPermissionsListAPIView(ListAPIView):
    serializer_class = AccessPermissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        try:
            person_profile = Person.objects.get(user=user)
            return AccessPermission.objects.filter(person=person_profile).select_related('person', 'access_point').order_by('-valid_until', 'access_point__name')
        except Person.DoesNotExist:
            return AccessPermission.objects.none()
