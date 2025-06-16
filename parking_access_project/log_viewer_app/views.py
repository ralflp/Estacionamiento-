from django.shortcuts import render, redirect, get_object_or_404
from .models import AccessLog, Person, Vehicle, AccessPermission, ControlDevice
from .forms import PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm

# DRF Imports
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .serializers import (
    AccessRequestSerializer, AccessResponseSerializer,
    AccessPermissionSerializer
)
from .utils import verify_access_with_models # Suponiendo que está en utils.py
# Person model already imported above
from django.utils import timezone # Para el timestamp en AccessResponseSerializer


# Django Template Views (existentes)
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


# --- API Views ---

class AccessVerificationAPIView(APIView):
    permission_classes = [IsAuthenticated] # Asegura que solo clientes autenticados puedan usarla

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
            # We should always be able to serialize response_data if AccessResponseSerializer is defined correctly
            if response_serializer.is_valid(raise_exception=True): # raise_exception helps debug if our data is bad
                return Response(response_serializer.data, status=status.HTTP_200_OK)
            # The following lines are unlikely to be reached if raise_exception=True is used above
            # and AccessResponseSerializer is correctly implemented.
            # else:
            #     return Response(response_serializer.errors, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserPermissionsListAPIView(ListAPIView):
    serializer_class = AccessPermissionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Esta vista debe devolver una lista de todos los permisos
        para la persona asociada con el usuario actualmente autenticado.
        """
        user = self.request.user
        try:
            # Encontrar el perfil de Persona asociado al usuario de Django
            # Se asume que el campo 'user' en el modelo Person es el OneToOneField al User de Django.
            person_profile = Person.objects.get(user=user)
            return AccessPermission.objects.filter(person=person_profile).select_related('person', 'access_point').order_by('-valid_until')
        except Person.DoesNotExist:
            # Si no hay un perfil de Persona para este usuario de Django, no devolver permisos.
            return AccessPermission.objects.none()
