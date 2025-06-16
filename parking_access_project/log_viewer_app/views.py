from django.shortcuts import render, redirect
from .models import AccessLog, Person, Vehicle, AccessPermission # AccessPermission es nuevo aquí
from .forms import PersonForm, VehicleForm, AccessPermissionForm # AccessPermissionForm es nuevo aquí

def access_log_list_view(request):
    # Recuperar todos los registros de acceso, ordenados por fecha descendente
    logs = AccessLog.objects.all().order_by('-timestamp')

    context = {
        'access_logs': logs,
        'page_title': 'Registros de Acceso'
    }
    return render(request, 'log_viewer_app/access_log_list.html', context)


def person_list_view(request):
    persons = Person.objects.all().order_by('full_name')
    context = {
        'persons': persons,
        'page_title': 'Lista de Personas'
    }
    return render(request, 'log_viewer_app/person_list.html', context)

def person_create_view(request):
    if request.method == 'POST':
        form = PersonForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:person_list')
    else:
        form = PersonForm()

    context = {
        'form': form,
        'page_title': 'Añadir Nueva Persona'
    }
    return render(request, 'log_viewer_app/person_form.html', context)


def vehicle_list_view(request):
    vehicles = Vehicle.objects.all().select_related('owner').order_by('license_plate')
    context = {
        'vehicles': vehicles,
        'page_title': 'Lista de Vehículos'
    }
    return render(request, 'log_viewer_app/vehicle_list.html', context)

def vehicle_create_view(request):
    if request.method == 'POST':
        form = VehicleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:vehicle_list')
    else:
        form = VehicleForm()

    context = {
        'form': form,
        'page_title': 'Añadir Nuevo Vehículo'
    }
    return render(request, 'log_viewer_app/vehicle_form.html', context)

def permission_list_view(request):
    permissions = AccessPermission.objects.all().select_related('person', 'access_point').order_by('person__full_name', 'access_point__name')
    context = {
        'permissions': permissions,
        'page_title': 'Lista de Permisos de Acceso'
    }
    return render(request, 'log_viewer_app/permission_list.html', context)

def permission_create_view(request):
    if request.method == 'POST':
        form = AccessPermissionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('log_viewer_app:permission_list')
    else:
        form = AccessPermissionForm()

    context = {
        'form': form,
        'page_title': 'Asignar Nuevo Permiso de Acceso'
    }
    return render(request, 'log_viewer_app/permission_form.html', context)


# La función record_access_attempt NO debe estar en views.py, está en utils.py
# (Comentario original preservado)
