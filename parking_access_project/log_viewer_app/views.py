from django.shortcuts import render, redirect, get_object_or_404
from .models import (
    AccessLog, Person, Vehicle, AccessPermission, ControlDevice, AccessPoint,
    UserSubscription, Invoice # UserSubscription e Invoice añadidos aquí
)
from .forms import (
    PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm,
    GuestRegistrationForm, PersonProfileEditForm # PersonProfileEditForm importado
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib import messages
import logging
from django.db.models import Q, Sum # Sum importado
from django.utils import timezone
from decimal import Decimal # Decimal importado

logger = logging.getLogger(__name__)

# DRF Imports
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.authtoken.models import Token

from .serializers import (
    AccessRequestSerializer, AccessResponseSerializer,
    AccessPermissionSerializer
)
from .utils import verify_access_with_models


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
    context = {'form': form, 'permission_instance': permission, 'page_title': f"Editar Permiso: {permission.person.full_name} en {permission.access_point.name}"}
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
    user_subscriptions = []
    user_invoices = []
    total_amount_due = Decimal('0.00') # Initialize here

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

            user_subscriptions = UserSubscription.objects.filter(
                person=person_profile
            ).select_related('service').order_by('service__name', '-start_date')

            user_invoices = Invoice.objects.filter(
                person=person_profile
            ).select_related('user_subscription__service', 'person').order_by('-due_date', '-created_at')

            # Calculate total amount due from pending/overdue invoices
            due_invoices_aggregation = user_invoices.filter(
                status__in=['pending', 'overdue']
            ).aggregate(total_due=Sum('amount_due'))

            if due_invoices_aggregation['total_due'] is not None:
                total_amount_due = due_invoices_aggregation['total_due']

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
        'user_subscriptions': user_subscriptions,
        'user_invoices': user_invoices,
        'total_amount_due': total_amount_due, # Added to context
        'page_title': 'Mi Portal de Usuario'
    }
    return render(request, 'log_viewer_app/user_dashboard.html', context)

@login_required
def person_profile_edit_view(request):
    try:
        person_profile = Person.objects.get(user=request.user)
    except Person.DoesNotExist:
        messages.error(request, "No se encontró un perfil de persona asociado a tu usuario. Por favor, contacta al administrador.")
        return redirect('log_viewer_app:user_dashboard')
    except Exception as e:
        logger.error(f"Error buscando Person profile para user {request.user.username} en edición de perfil: {e}")
        messages.error(request, "Ocurrió un error al cargar tu perfil.")
        return redirect('log_viewer_app:user_dashboard')

    if request.method == 'POST':
        form = PersonProfileEditForm(request.POST, instance=person_profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Tu perfil ha sido actualizado exitosamente.")
            return redirect('log_viewer_app:user_dashboard')
    else:
        form = PersonProfileEditForm(instance=person_profile)

    context = {
        'form': form,
        'page_title': 'Editar Mi Perfil'
    }
    return render(request, 'log_viewer_app/person_profile_edit_form.html', context)

@login_required
def qr_scanner_page_view(request):
    user = request.user; access_points = AccessPoint.objects.all().order_by('name'); token_string = ""
    try:
        token_obj, created = Token.objects.get_or_create(user=user)
        if created: logger.info(f"Nuevo token API creado para {user.username} en página QR scanner.")
        token_string = token_obj.key
    except Exception as e: logger.error(f"Error al obtener/crear token para {user.username} en qr_scanner_page_view: {e}")
    context = {'access_points': access_points, 'user_auth_token': token_string, 'page_title': 'Escáner de Códigos QR'}
    return render(request, 'log_viewer_app/qr_scanner_page.html', context)

@login_required
def guest_registration_view(request):
    try:
        guest_manager_group = Group.objects.get(name='Gestores de Invitados')
    except Group.DoesNotExist:
        messages.error(request, "El grupo 'Gestores de Invitados' no existe. Contacta al administrador.")
        return redirect('log_viewer_app:user_dashboard')

    if not request.user.groups.filter(name='Gestores de Invitados').exists() and not request.user.is_superuser:
        messages.error(request, "No tienes permisos para registrar invitados.")
        return redirect('log_viewer_app:user_dashboard')

    host_person_profile = None
    try:
        host_person_profile = Person.objects.get(user=request.user)
    except Person.DoesNotExist:
        messages.error(request, "Tu usuario no está asociado a un perfil de Persona. No puedes registrar invitados.")
        return redirect('log_viewer_app:user_dashboard')

    if request.method == 'POST':
        form = GuestRegistrationForm(request.POST)
        if form.is_valid():
            try:
                guest = Person.objects.create(
                    full_name=form.cleaned_data['guest_full_name'],
                    identifier=form.cleaned_data['guest_identifier'],
                    is_temporary_guest=True,
                    registered_by=host_person_profile
                )
                AccessPermission.objects.create(
                    person=guest,
                    access_point=form.cleaned_data['access_point'],
                    is_active=True,
                    valid_from=form.cleaned_data['permission_valid_from'],
                    valid_until=form.cleaned_data['permission_valid_until']
                )
                AccessLog.objects.create(
                    qr_data=guest.identifier,
                    access_granted=True,
                    event_type="GUEST_REGISTERED",
                    user_id=host_person_profile.identifier,
                    notes=f"Invitado {guest.full_name} registrado por {host_person_profile.full_name}. Permiso para {form.cleaned_data['access_point'].name}."
                )
                messages.success(request, f"Invitado {guest.full_name} registrado exitosamente con acceso temporal.")
                return redirect('log_viewer_app:person_list')
            except Exception as e:
                logger.error(f"Error al registrar invitado: {e}")
                messages.error(request, "Ocurrió un error al registrar al invitado. Inténtalo de nuevo.")
    else:
        form = GuestRegistrationForm()

    context = {'form': form, 'page_title': 'Registrar Invitado Temporal'}
    return render(request, 'log_viewer_app/guest_registration_form.html', context)

# --- API Views ---
class AccessVerificationAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        serializer = AccessRequestSerializer(data=request.data)
        if serializer.is_valid():
            qr_identifier = serializer.validated_data['qr_identifier']; access_point_name = serializer.validated_data['access_point_name']
            access_granted = verify_access_with_models(qr_identifier, access_point_name)
            person_name_for_response = None
            try: person = Person.objects.get(identifier=qr_identifier); person_name_for_response = person.full_name
            except Person.DoesNotExist: pass
            response_data = {'access_granted': access_granted, 'message': "Acceso Permitido" if access_granted else "Acceso Denegado", 'person_name': person_name_for_response, 'access_point_name': access_point_name, 'timestamp': timezone.now()}
            response_serializer = AccessResponseSerializer(data=response_data)
            if response_serializer.is_valid(raise_exception=True): return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserPermissionsListAPIView(ListAPIView):
    serializer_class = AccessPermissionSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        user = self.request.user
        try:
            person_profile = Person.objects.get(user=user)
            return AccessPermission.objects.filter(person=person_profile).select_related('person', 'access_point').order_by('-valid_until', 'access_point__name')
        except Person.DoesNotExist: return AccessPermission.objects.none()
