from django.test import TestCase, Client
from django.urls import reverse
from .models import (
    AccessLog, Person, Vehicle, AccessPoint, AccessPermission,
    ControlDevice, Payment, Service, UserSubscription, Invoice
)
from .forms import (
    PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm,
    GuestRegistrationForm
)
from .utils import verify_access_with_models, publish_mqtt_message, process_payment_for_access
from .billing_utils import generate_invoice_for_subscription, generate_all_due_invoices, get_due_cycle_start_date_for_subscription # Import the new function
from django.utils import timezone
from datetime import timedelta, date as dt_date, datetime as dt_datetime, date
from decimal import Decimal
from unittest.mock import patch, MagicMock, call as mock_call
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User, Group
from django.contrib.messages.storage.fallback import FallbackStorage
from .admin import PaymentAdmin

# DRF Test specific imports
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from rest_framework import status
from .serializers import AccessRequestSerializer, AccessResponseSerializer, AccessPermissionSerializer

# For management command testing
from io import StringIO
from django.core.management import call_command


# --- Model Tests ---
class PersonModelTest(TestCase):
    def test_person_creation(self):
        user_host = User.objects.create_user(username='hostuser', password='password')
        host_person = Person.objects.create(user=user_host, full_name="Host Person", identifier="HOST01")
        person = Person.objects.create(full_name="John Doe", identifier="JD001", is_temporary_guest=True, registered_by=host_person)
        self.assertIsInstance(person, Person)
        self.assertEqual(str(person), "John Doe (JD001) (Invitado Temp.)")

    def test_person_str_not_guest(self):
        person = Person.objects.create(full_name="Regular Person", identifier="REG01")
        self.assertEqual(str(person), "Regular Person (REG01)")


class VehicleModelTest(TestCase):
    def setUp(self):
        self.owner = Person.objects.create(full_name="Jane Smith", identifier="JS002")

    def test_vehicle_creation(self):
        vehicle = Vehicle.objects.create(owner=self.owner, license_plate="XYZ123", description="Red Car")
        self.assertIsInstance(vehicle, Vehicle)
        self.assertEqual(str(vehicle), "XYZ123 (Jane Smith)")

class AccessPointModelTest(TestCase):
    def test_access_point_creation(self):
        ap = AccessPoint.objects.create(name="Main Gate", description="Main entrance")
        self.assertIsInstance(ap, AccessPoint)
        self.assertEqual(str(ap), "Main Gate")

class AccessPermissionModelTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(full_name="Alice Wonderland", identifier="AW003")
        self.access_point = AccessPoint.objects.create(name="Wonderland Gate")

    def test_access_permission_creation(self):
        now = timezone.now()
        permission = AccessPermission.objects.create(person=self.person, access_point=self.access_point, is_active=True, valid_from=now, valid_until=now + timedelta(days=30))
        self.assertIsInstance(permission, AccessPermission)
        self.assertIn("Alice Wonderland", str(permission))

    def test_access_permission_unique_together(self):
        AccessPermission.objects.create(person=self.person, access_point=self.access_point)
        with self.assertRaises(Exception):
            AccessPermission.objects.create(person=self.person, access_point=self.access_point)

class ControlDeviceModelTest(TestCase):
    def setUp(self):
        self.ap = AccessPoint.objects.create(name="Garage Door AP")

    def test_control_device_creation(self):
        device = ControlDevice.objects.create(name="Garage Controller 1", device_id="GDCTRL001", access_point=self.ap, mqtt_topic="garage/door1/control", ip_address="192.168.1.100", is_active=True)
        self.assertIsInstance(device, ControlDevice)
        self.assertEqual(str(device), "Garage Controller 1 (GDCTRL001) - AP: Garage Door AP")

    def test_control_device_str_no_ap(self):
        device = ControlDevice.objects.create(name="Unassigned Controller", device_id="UCTRL002", mqtt_topic="unassigned/control")
        self.assertEqual(str(device), "Unassigned Controller (UCTRL002) - AP: No asignado")

class PaymentModelTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(full_name="Payment User", identifier="PU001")

    def test_payment_creation(self):
        payment = Payment.objects.create(person=self.person, amount=Decimal("50.00"), payment_method='tarjeta_credito', reference_number='TXN12345')
        self.assertIsInstance(payment, Payment)
        self.assertIn(f"Pago de {payment.amount:.2f} por Payment User", str(payment))

class ServiceModelTest(TestCase):
    def test_service_creation(self):
        service = Service.objects.create(name="Estacionamiento Mensual", description="Acceso mensual.", price=Decimal("75.50"))
        self.assertIsInstance(service, Service)
        self.assertEqual(str(service), "Estacionamiento Mensual - $75.50")

class UserSubscriptionModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = Person.objects.create(full_name="Subscriber User", identifier="SUB001")
        cls.service = Service.objects.create(name="Servicio Básico", price=Decimal("100.00"))

    def test_user_subscription_creation(self):
        start_date = dt_date(2024, 1, 1)
        end_date = dt_date(2024, 12, 31)
        sub = UserSubscription.objects.create(person=self.person, service=self.service, start_date=start_date, end_date=end_date, billing_cycle='annually', is_active=True)
        self.assertIsInstance(sub, UserSubscription)
        self.assertIn("Subscriber User", str(sub))

    def test_get_effective_price_no_override(self):
        sub = UserSubscription.objects.create(person=self.person, service=self.service)
        self.assertEqual(sub.get_effective_price(), self.service.price)

    def test_get_effective_price_with_override(self):
        override_price = Decimal("90.00")
        sub = UserSubscription.objects.create(person=self.person, service=self.service, price_override=override_price)
        self.assertEqual(sub.get_effective_price(), override_price)

class InvoiceModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = Person.objects.create(full_name="Invoice User", identifier="INV001")

    def test_invoice_creation(self):
        invoice = Invoice.objects.create(person=self.person, invoice_number="INV-2024-001", amount_due=Decimal("150.00"), due_date=dt_date(2024, 7, 31), status='pending')
        self.assertIsInstance(invoice, Invoice)
        self.assertIn("Factura INV-2024-001", str(invoice))


# --- Form Tests ---
class PersonFormTest(TestCase):
    def test_person_form_valid_data(self):
        form = PersonForm(data={'full_name': 'Form User', 'identifier': 'FU001'})
        self.assertTrue(form.is_valid())

    def test_person_form_invalid_missing_identifier(self):
        form = PersonForm(data={'full_name': 'Form User No ID'})
        self.assertFalse(form.is_valid())
        self.assertIn('identifier', form.errors)

    def test_person_form_save(self):
        form = PersonForm(data={'full_name': 'Save User', 'identifier': 'SU001'})
        self.assertTrue(form.is_valid())
        person = form.save()
        self.assertIsInstance(person, Person)
        self.assertEqual(person.identifier, 'SU001')

class VehicleFormTest(TestCase):
    def setUp(self):
        self.owner = Person.objects.create(full_name="Owner Test", identifier="OT001")

    def test_vehicle_form_valid_data(self):
        form = VehicleForm(data={'owner': self.owner.pk, 'license_plate': 'VF123', 'description': 'Test Vehicle'})
        self.assertTrue(form.is_valid())

    def test_vehicle_form_invalid_missing_plate(self):
        form = VehicleForm(data={'owner': self.owner.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('license_plate', form.errors)

class AccessPermissionFormTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(full_name="Perm Form Person", identifier="PFP01")
        self.ap = AccessPoint.objects.create(name="Perm Form AP")

    def test_access_permission_form_valid_data(self):
        form = AccessPermissionForm(data={'person': self.person.pk, 'access_point': self.ap.pk, 'is_active': True, 'valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'), 'valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')})
        self.assertTrue(form.is_valid())

    def test_access_permission_form_save(self):
        form = AccessPermissionForm(data={'person': self.person.pk, 'access_point': self.ap.pk, 'is_active': True})
        self.assertTrue(form.is_valid())
        permission = form.save()
        self.assertIsInstance(permission, AccessPermission)
        self.assertTrue(permission.is_active)

class ControlDeviceFormTest(TestCase):
    def setUp(self):
        self.ap = AccessPoint.objects.create(name="Device Form AP")

    def test_control_device_form_valid_data(self):
        form = ControlDeviceForm(data={'name': 'Test Device', 'device_id': 'DEVFORM001', 'access_point': self.ap.pk, 'mqtt_topic': 'test/device/topic', 'is_active': True})
        self.assertTrue(form.is_valid())

    def test_control_device_form_invalid_missing_device_id(self):
        form = ControlDeviceForm(data={'name': 'Test Device No ID'})
        self.assertFalse(form.is_valid())
        self.assertIn('device_id', form.errors)

    def test_control_device_form_save(self):
        form = ControlDeviceForm(data={'name': 'Save Device', 'device_id': 'SDEV001', 'access_point': self.ap.pk, 'mqtt_topic': 'save/device/topic'})
        self.assertTrue(form.is_valid())
        device = form.save()
        self.assertIsInstance(device, ControlDevice)
        self.assertEqual(device.device_id, 'SDEV001')

class GuestRegistrationFormTest(TestCase):
    def setUp(self):
        self.ap1 = AccessPoint.objects.create(name="Puerta Principal")
        Person.objects.create(full_name="Existing User", identifier="EXISTING_ID")

    def test_form_valid_data(self):
        form_data = {'guest_full_name': "Nuevo Invitado", 'guest_identifier': "NEW_GUEST_ID", 'access_point': self.ap1.pk, 'permission_valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'), 'permission_valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')}
        form = GuestRegistrationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors.as_text())

    def test_form_guest_identifier_exists(self):
        form_data = {'guest_full_name': "Otro Invitado", 'guest_identifier': "EXISTING_ID", 'access_point': self.ap1.pk, 'permission_valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'), 'permission_valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')}
        form = GuestRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('guest_identifier', form.errors)

    def test_form_permission_dates_invalid_order(self):
        form_data = {'guest_full_name': "Invitado Fechas Mal", 'guest_identifier': "GUEST_DATES_BAD", 'access_point': self.ap1.pk, 'permission_valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'), 'permission_valid_until': (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')}
        form = GuestRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertTrue(form.has_error('permission_valid_until') or form.non_field_errors())

    def test_form_missing_required_fields(self):
        form = GuestRegistrationForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('guest_full_name', form.errors)
        self.assertIn('guest_identifier', form.errors)


# --- View Tests ---
class AccessLogListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        AccessLog.objects.create(qr_data="QR_Log_1", access_granted=True)
        AccessLog.objects.create(qr_data="QR_Log_2", access_granted=False)

    def test_view_url_exists_at_desired_location(self):
        response = self.client.get('/access/logs/')
        self.assertEqual(response.status_code, 200)

    def test_view_url_accessible_by_name(self):
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(response.status_code, 200)

    def test_view_uses_correct_template(self):
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertTemplateUsed(response, 'log_viewer_app/access_log_list.html')

    def test_view_displays_logs_when_present(self):
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertTrue(len(response.context['access_logs']) >= 2)
        self.assertContains(response, "QR_Log_1")

    def test_view_displays_no_logs_message_when_empty(self):
        AccessLog.objects.all().delete()
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(len(response.context['access_logs']), 0)
        self.assertContains(response, "No hay registros de acceso para mostrar.")

class PersonListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        Person.objects.create(full_name="List Person 1", identifier="LP1")

    def test_person_list_view_url_accessible_by_name(self):
        response = self.client.get(reverse('log_viewer_app:person_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/person_list.html')
        self.assertContains(response, "LP1")

class PersonCreateViewTest(TestCase):
    def test_person_create_view_get(self):
        response = self.client.get(reverse('log_viewer_app:person_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/person_form.html')
        self.assertIsInstance(response.context['form'], PersonForm)

    def test_person_create_view_post_valid(self):
        initial_count = Person.objects.count()
        response = self.client.post(reverse('log_viewer_app:person_create'), {'full_name': 'Create Person Test', 'identifier': 'CPT01'})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('log_viewer_app:person_list'))
        self.assertEqual(Person.objects.count(), initial_count + 1)

    def test_person_create_view_post_invalid(self):
        response = self.client.post(reverse('log_viewer_app:person_create'), {'full_name': 'No ID'})
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'identifier', 'This field is required.')

class VehicleListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = Person.objects.create(full_name="Owner For Vehicle", identifier="OFV01")
        Vehicle.objects.create(owner=owner, license_plate="VL1", description="Vehicle List Test")

    def test_vehicle_list_view_accessible(self):
        response = self.client.get(reverse('log_viewer_app:vehicle_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/vehicle_list.html')
        self.assertContains(response, "VL1")

class VehicleCreateViewTest(TestCase):
    def setUp(self):
        self.owner = Person.objects.create(full_name="Owner For Create Vehicle", identifier="OFCV01")

    def test_vehicle_create_view_get(self):
        response = self.client.get(reverse('log_viewer_app:vehicle_create'))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], VehicleForm)

    def test_vehicle_create_view_post_valid(self):
        response = self.client.post(reverse('log_viewer_app:vehicle_create'), {'owner': self.owner.pk, 'license_plate': 'VCV01', 'description': 'Created Vehicle'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Vehicle.objects.filter(license_plate='VCV01').exists())

class AccessPermissionListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        person = Person.objects.create(full_name="Perm List Person", identifier="PLP01")
        ap = AccessPoint.objects.create(name="Perm List AP")
        AccessPermission.objects.create(person=person, access_point=ap, is_active=True)

    def test_permission_list_view_accessible(self):
        response = self.client.get(reverse('log_viewer_app:permission_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/permission_list.html')
        self.assertContains(response, "PLP01")

class AccessPermissionCreateViewTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(full_name="Perm Create Person", identifier="PCP01")
        self.ap = AccessPoint.objects.create(name="Perm Create AP")

    def test_permission_create_view_get(self):
        response = self.client.get(reverse('log_viewer_app:permission_create'))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], AccessPermissionForm)

    def test_permission_create_view_post_valid(self):
        response = self.client.post(reverse('log_viewer_app:permission_create'), {'person': self.person.pk, 'access_point': self.ap.pk, 'is_active': True})
        self.assertEqual(response.status_code, 302, f"Form errors: {response.context.get('form').errors if response.context else 'No context'}")
        self.assertTrue(AccessPermission.objects.filter(person=self.person, access_point=self.ap).exists())

class AccessPermissionUpdateViewTest(TestCase):
    def setUp(self):
        self.person1 = Person.objects.create(full_name="Test Person Update", identifier="TPU01")
        self.ap1 = AccessPoint.objects.create(name="Test AP Update")
        self.permission1 = AccessPermission.objects.create(person=self.person1, access_point=self.ap1, is_active=True)
        self.update_url = reverse('log_viewer_app:permission_update', kwargs={'pk': self.permission1.pk})
        self.list_url = reverse('log_viewer_app:permission_list')

    def test_permission_update_view_get_success(self):
        response = self.client.get(self.update_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/permission_form.html')
        self.assertIsInstance(response.context['form'], AccessPermissionForm)
        self.assertEqual(response.context['form'].instance, self.permission1)
        self.assertEqual(response.context['permission_instance'], self.permission1)

    def test_permission_update_view_post_success(self):
        post_data = {'person': self.person1.pk, 'access_point': self.ap1.pk, 'is_active': False, 'valid_from': self.permission1.valid_from.strftime('%Y-%m-%dT%H:%M') if self.permission1.valid_from else '', 'valid_until': self.permission1.valid_until.strftime('%Y-%m-%dT%H:%M') if self.permission1.valid_until else ''}
        response = self.client.post(self.update_url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, self.list_url)
        self.permission1.refresh_from_db()
        self.assertFalse(self.permission1.is_active)

    def test_permission_update_view_post_invalid_non_existent_person(self):
        post_data = {'person': 99999, 'access_point': self.ap1.pk, 'is_active': True}
        response = self.client.post(self.update_url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('person', response.context['form'].errors)

    def test_permission_update_view_get_not_found(self):
        response = self.client.get(reverse('log_viewer_app:permission_update', kwargs={'pk': 99999}))
        self.assertEqual(response.status_code, 404)

class ControlDeviceListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ap = AccessPoint.objects.create(name="CD List AP")
        ControlDevice.objects.create(name="CD List Dev 1", device_id="CDL1", access_point=ap, mqtt_topic="cd/list/1")

    def test_cd_list_view_accessible(self):
        response = self.client.get(reverse('log_viewer_app:control_device_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/control_device_list.html')
        self.assertContains(response, "CDL1")

class ControlDeviceCreateViewTest(TestCase):
    def setUp(self):
        self.ap = AccessPoint.objects.create(name="CD Create AP")

    def test_cd_create_view_get(self):
        response = self.client.get(reverse('log_viewer_app:control_device_create'))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], ControlDeviceForm)

    def test_cd_create_view_post_valid(self):
        response = self.client.post(reverse('log_viewer_app:control_device_create'), {'name': 'New CD', 'device_id': 'NCD01', 'access_point': self.ap.pk, 'mqtt_topic': 'new/cd/topic'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ControlDevice.objects.filter(device_id='NCD01').exists())

class ControlDeviceUpdateViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ap = AccessPoint.objects.create(name="CD Update AP")
        cls.device = ControlDevice.objects.create(name="CD Update Dev", device_id="CDU01", access_point=cls.ap, mqtt_topic="cd/update/topic")

    def test_cd_update_view_get(self):
        response = self.client.get(reverse('log_viewer_app:control_device_update', kwargs={'pk': self.device.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], ControlDeviceForm)
        self.assertContains(response, "CDU01")

    def test_cd_update_view_post_valid(self):
        response = self.client.post(reverse('log_viewer_app:control_device_update', kwargs={'pk': self.device.pk}), {'name': 'Updated CD Name', 'device_id': 'CDU01_updated', 'access_point': self.ap.pk, 'mqtt_topic': 'updated/cd/topic', 'is_active': True})
        self.assertEqual(response.status_code, 302)
        updated_device = ControlDevice.objects.get(pk=self.device.pk)
        self.assertEqual(updated_device.name, "Updated CD Name")
        self.assertEqual(updated_device.device_id, "CDU01_updated")

    def test_cd_update_view_non_existent(self):
        response = self.client.get(reverse('log_viewer_app:control_device_update', kwargs={'pk': 9999}))
        self.assertEqual(response.status_code, 404)


# --- Logic Tests ---
class MQTTUtilsTest(TestCase):
    @patch('log_viewer_app.utils.publish.single')
    def test_publish_mqtt_message_success(self, mock_publish_single):
        original_mqtt_user = getattr(settings, 'MQTT_USERNAME', None); original_mqtt_pass = getattr(settings, 'MQTT_PASSWORD', None)
        if hasattr(settings, 'MQTT_USERNAME'): delattr(settings, 'MQTT_USERNAME')
        if hasattr(settings, 'MQTT_PASSWORD'): delattr(settings, 'MQTT_PASSWORD')
        current_broker_host = 'testbroker_success' ; current_broker_port = 18830; current_client_id = 'testclient_success'
        settings.MQTT_BROKER_HOST = current_broker_host; settings.MQTT_BROKER_PORT = current_broker_port; settings.MQTT_CLIENT_ID = current_client_id
        result = publish_mqtt_message("test/topic", "payload_test")
        self.assertTrue(result); mock_publish_single.assert_called_once_with("test/topic", payload="payload_test", qos=1, retain=False, hostname=current_broker_host, port=current_broker_port, client_id=current_client_id, auth=None)
        if original_mqtt_user is not None : setattr(settings, 'MQTT_USERNAME', original_mqtt_user)
        if original_mqtt_pass is not None : setattr(settings, 'MQTT_PASSWORD', original_mqtt_pass)
        settings.MQTT_BROKER_HOST = 'localhost' ; settings.MQTT_BROKER_PORT = 1883
    @patch('log_viewer_app.utils.publish.single')
    def test_publish_mqtt_message_with_auth(self, mock_publish_single):
        settings.MQTT_BROKER_HOST = 'authbroker'; settings.MQTT_BROKER_PORT = 18831; settings.MQTT_CLIENT_ID = 'authclient'; settings.MQTT_USERNAME = 'user'; settings.MQTT_PASSWORD = 'pass'
        result = publish_mqtt_message("auth/topic", "auth_payload")
        self.assertTrue(result); mock_publish_single.assert_called_once_with("auth/topic", payload="auth_payload", qos=1, retain=False, hostname='authbroker', port=18831, client_id='authclient', auth={'username': 'user', 'password': 'pass'})
    @patch('log_viewer_app.utils.publish.single', side_effect=ConnectionRefusedError("Test refuse"))
    @patch('log_viewer_app.utils.logger.error')
    def test_publish_mqtt_connection_refused(self, mock_logger_error, mock_publish_single):
        original_host = settings.MQTT_BROKER_HOST; original_port = settings.MQTT_BROKER_PORT
        settings.MQTT_BROKER_HOST = 'refused_broker_for_test' ; settings.MQTT_BROKER_PORT = 12345
        result = publish_mqtt_message("refuse/topic", "refuse_payload")
        self.assertFalse(result); expected_message = f"MQTT Error: Conexión rechazada al broker {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}. Verifica que el broker esté activo y accesible."
        called_with_expected_message = False
        for call_args in mock_logger_error.call_args_list:
            if call_args[0][0] == expected_message: called_with_expected_message = True; break
        self.assertTrue(called_with_expected_message, f"Expected log message not found. Actual calls: {mock_logger_error.call_args_list}")
        settings.MQTT_BROKER_HOST = original_host; settings.MQTT_BROKER_PORT = original_port
    @patch('log_viewer_app.utils.publish.single', side_effect=Exception("Generic MQTT error"))
    @patch('log_viewer_app.utils.logger.error')
    def test_publish_mqtt_generic_exception(self, mock_logger_error, mock_publish_single):
        result = publish_mqtt_message("generic/topic", "generic_payload"); self.assertFalse(result); mock_logger_error.assert_called_with("MQTT Error: No se pudo publicar en tópico 'generic/topic'. Error: Generic MQTT error")

class VerifyAccessLogicTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person1 = Person.objects.create(full_name="Allowed User", identifier="ALLOW_ID"); cls.person2 = Person.objects.create(full_name="NoPerm User", identifier="NOPERM_ID"); cls.person3 = Person.objects.create(full_name="InactivePerm User", identifier="INACTIVE_ID"); cls.person4 = Person.objects.create(full_name="FuturePerm User", identifier="FUTURE_ID"); cls.person5 = Person.objects.create(full_name="ExpiredPerm User", identifier="EXPIRED_ID"); cls.person6 = Person.objects.create(full_name="TimeValid User", identifier="TIMEVALID_ID")
        cls.ap1 = AccessPoint.objects.create(name="MainDoor"); cls.ap_mqtt = AccessPoint.objects.create(name="MQTT_Controlled_Door")
        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap1, is_active=True); AccessPermission.objects.create(person=cls.person3, access_point=cls.ap1, is_active=False); AccessPermission.objects.create(person=cls.person4, access_point=cls.ap1, is_active=True, valid_from=timezone.now() + timedelta(days=1)); AccessPermission.objects.create(person=cls.person5, access_point=cls.ap1, is_active=True, valid_until=timezone.now() - timedelta(days=1)); AccessPermission.objects.create(person=cls.person6, access_point=cls.ap1, is_active=True, valid_from=timezone.now() - timedelta(hours=1), valid_until=timezone.now() + timedelta(hours=1))
        cls.device1_ap_mqtt = ControlDevice.objects.create(name="MQTT_Door_Ctrl1", device_id="CTRL_MQTT1", access_point=cls.ap_mqtt, mqtt_topic="door/mqtt1/open", is_active=True)
        cls.person_mqtt = Person.objects.create(full_name="MQTT Access User", identifier="MQTT_ACCESS_ID"); AccessPermission.objects.create(person=cls.person_mqtt, access_point=cls.ap_mqtt, is_active=True)
    def tearDown(self): AccessLog.objects.all().delete()
    def test_access_allowed(self): self.assertTrue(verify_access_with_models("ALLOW_ID", "MainDoor"))
    def test_person_not_found(self): self.assertFalse(verify_access_with_models("UNKNOWN_ID", "MainDoor"))
    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_triggers_mqtt_publish_single_device(self, mock_publish): mock_publish.return_value=True; self.assertTrue(verify_access_with_models("MQTT_ACCESS_ID", "MQTT_Controlled_Door")); mock_publish.assert_called_once_with(topic=self.device1_ap_mqtt.mqtt_topic, payload="OPEN")
    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_no_active_devices(self, mock_publish): ControlDevice.objects.filter(device_id="CTRL_MQTT1").update(is_active=False); self.assertTrue(verify_access_with_models("MQTT_ACCESS_ID", "MQTT_Controlled_Door")); mock_publish.assert_not_called(); ControlDevice.objects.filter(device_id="CTRL_MQTT1").update(is_active=True)
    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_denied_no_mqtt_publish(self, mock_publish): self.assertFalse(verify_access_with_models("NOPERM_ID", "MQTT_Controlled_Door")); mock_publish.assert_not_called()
    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_multiple_active_devices_mqtt_publish(self, mock_publish): mock_publish.return_value=True; dev_extra = ControlDevice.objects.create(name="ExtraDev", device_id="EXTRA01", access_point=self.ap_mqtt, mqtt_topic="extra/topic", is_active=True); self.assertTrue(verify_access_with_models("MQTT_ACCESS_ID", "MQTT_Controlled_Door")); self.assertEqual(mock_publish.call_count, 2); topics = [c.kwargs['topic'] for c in mock_publish.call_args_list]; self.assertCountEqual(topics, [self.device1_ap_mqtt.mqtt_topic, dev_extra.mqtt_topic]); dev_extra.delete()
    def test_access_point_not_found(self): self.assertFalse(verify_access_with_models("ALLOW_ID", "NonExistentDoor"))
    def test_permission_not_found(self): self.assertFalse(verify_access_with_models("NOPERM_ID", "MainDoor"))
    def test_permission_inactive(self): self.assertFalse(verify_access_with_models("INACTIVE_ID", "MainDoor"))
    def test_permission_future_valid_from(self): self.assertFalse(verify_access_with_models("FUTURE_ID", "MainDoor"))
    def test_permission_expired_valid_until(self): self.assertFalse(verify_access_with_models("EXPIRED_ID", "MainDoor"))
    def test_permission_time_valid(self): self.assertTrue(verify_access_with_models("TIMEVALID_ID", "MainDoor"))
    def test_permission_valid_from_only_no_end(self): p, _ = Person.objects.get_or_create(identifier="NOEND_ID", defaults={'full_name':"PermNoEnd User"}); AccessPermission.objects.get_or_create(person=p,access_point=self.ap1,defaults={'is_active':True,'valid_from':timezone.now()-timedelta(days=1),'valid_until':None}); self.assertTrue(verify_access_with_models("NOEND_ID", "MainDoor"))
    def test_permission_default_valid_from_no_end(self): p, _ = Person.objects.get_or_create(identifier="DEFAULTSTART_ID", defaults={'full_name':"PermDefaultStart User"}); AccessPermission.objects.get_or_create(person=p,access_point=self.ap1,defaults={'is_active':True,'valid_until':None}); self.assertTrue(verify_access_with_models("DEFAULTSTART_ID", "MainDoor"))

# --- ProcessPaymentLogicTest and PaymentAdminActionTest remain here ---
class ProcessPaymentLogicTest(TestCase):
    def setUp(self):
        self.person1 = Person.objects.create(full_name="User With No Perms", identifier="PAY_USER_NOPEM")
        self.person2 = Person.objects.create(full_name="User Expired Perm", identifier="PAY_USER_EXP")
        self.person3 = Person.objects.create(full_name="User Active Perm", identifier="PAY_USER_ACTIVE")
        self.person4 = Person.objects.create(full_name="User No AP Perm", identifier="PAY_USER_NOAP")
        self.ap1, _ = AccessPoint.objects.get_or_create(name="Main Entrance", defaults={'description':"Default AP"})
        self.ap2 = AccessPoint.objects.create(name="Side Entrance")
        AccessPermission.objects.create(person=self.person2, access_point=self.ap1, is_active=True, valid_from=timezone.now() - timedelta(days=60), valid_until=timezone.now() - timedelta(days=30))
        self.active_perm_p3_ap1 = AccessPermission.objects.create(person=self.person3, access_point=self.ap1, is_active=True, valid_from=timezone.now() - timedelta(days=10), valid_until=timezone.now() + timedelta(days=20))
        self.active_perm_p3_ap2 = AccessPermission.objects.create(person=self.person3, access_point=self.ap2, is_active=True, valid_from=timezone.now() - timedelta(days=5), valid_until=timezone.now() + timedelta(days=5))

    def test_payment_no_person(self): payment = Payment.objects.create(amount=Decimal("10.00"), person=None); self.assertFalse(process_payment_for_access(payment)); payment.refresh_from_db(); self.assertFalse(payment.processed_for_access)
    def test_payment_already_processed(self): payment = Payment.objects.create(person=self.person1, amount=Decimal("10.00"), processed_for_access=True); self.assertTrue(process_payment_for_access(payment)); self.assertFalse(AccessPermission.objects.filter(person=self.person1).exists())
    def test_new_user_no_permissions_creates_default(self):
        payment_date = timezone.make_aware(dt_datetime(2023, 1, 15, 10, 0, 0)); payment = Payment.objects.create(person=self.person1, amount=Decimal("10.00"), payment_date=payment_date)
        self.assertTrue(process_payment_for_access(payment)); payment.refresh_from_db(); self.assertTrue(payment.processed_for_access)
        perms = AccessPermission.objects.filter(person=self.person1); self.assertEqual(perms.count(), 1); perm = perms.first()
        self.assertEqual(perm.access_point, self.ap1); self.assertTrue(perm.is_active); self.assertEqual(perm.valid_from, payment_date); self.assertEqual(perm.valid_until, payment_date + timedelta(days=30))
    def test_new_user_no_default_ap_available(self):
        AccessPoint.objects.all().delete(); payment = Payment.objects.create(person=self.person4, amount=Decimal("10.00"))
        self.assertFalse(process_payment_for_access(payment)); payment.refresh_from_db(); self.assertFalse(payment.processed_for_access)
        self.ap1 = AccessPoint.objects.create(name="Main Entrance")
    def test_existing_user_one_expired_permission(self):
        payment_date = timezone.now(); payment = Payment.objects.create(person=self.person2, amount=Decimal("10.00"), payment_date=payment_date)
        self.assertTrue(process_payment_for_access(payment)); payment.refresh_from_db(); self.assertTrue(payment.processed_for_access)
        perm = AccessPermission.objects.get(person=self.person2, access_point=self.ap1); self.assertTrue(perm.is_active); self.assertEqual(perm.valid_from, payment_date) ; self.assertEqual(perm.valid_until, payment_date + timedelta(days=30))
    def test_existing_user_one_active_permission_extends_from_valid_until(self):
        payment_date = self.active_perm_p3_ap1.valid_from ; payment = Payment.objects.create(person=self.person3, amount=Decimal("10.00"), payment_date=payment_date)
        original_valid_from_ap1 = self.active_perm_p3_ap1.valid_from; original_valid_until_ap1 = self.active_perm_p3_ap1.valid_until
        original_valid_from_ap2 = self.active_perm_p3_ap2.valid_from; original_valid_until_ap2 = self.active_perm_p3_ap2.valid_until
        self.assertTrue(process_payment_for_access(payment)); payment.refresh_from_db(); self.assertTrue(payment.processed_for_access)
        perm_ap1 = AccessPermission.objects.get(pk=self.active_perm_p3_ap1.pk); self.assertTrue(perm_ap1.is_active); self.assertEqual(perm_ap1.valid_from, original_valid_from_ap1) ; self.assertEqual(perm_ap1.valid_until, original_valid_until_ap1 + timedelta(days=30))
        perm_ap2 = AccessPermission.objects.get(pk=self.active_perm_p3_ap2.pk); self.assertTrue(perm_ap2.is_active); self.assertEqual(perm_ap2.valid_from, payment_date) ; self.assertEqual(perm_ap2.valid_until, original_valid_until_ap2 + timedelta(days=30))
    def test_existing_user_permission_no_expiry_sets_from_payment_date(self):
        p, _ = Person.objects.get_or_create(identifier="PAY_USER_NOEXPIRY", defaults={'full_name': "User No Expiry"}); perm = AccessPermission.objects.create(person=p, access_point=self.ap1, is_active=True, valid_until=None)
        payment_date = timezone.now(); payment = Payment.objects.create(person=p, amount=Decimal("10.00"), payment_date=payment_date)
        self.assertTrue(process_payment_for_access(payment)); perm.refresh_from_db(); self.assertTrue(perm.is_active); self.assertEqual(perm.valid_until, payment_date + timedelta(days=30))

class PaymentAdminActionTest(TestCase):
    def setUp(self):
        self.site = admin.AdminSite(); self.payment_admin = PaymentAdmin(Payment, self.site)
        self.person1 = Person.objects.create(full_name="AdminAction User1", identifier="AAU001")
        self.person2 = Person.objects.create(full_name="AdminAction User2", identifier="AAU002")
        self.person3 = Person.objects.create(full_name="AdminAction User3", identifier="AAU003")
        AccessPoint.objects.get_or_create(name="Main Entrance")
        self.payment1_new_pk = Payment.objects.create(person=self.person1, amount=Decimal("20.00"), processed_for_access=False).pk
        self.payment1_new = Payment.objects.get(pk=self.payment1_new_pk)
        self.payment2_processed_pk = Payment.objects.create(person=self.person2, amount=Decimal("20.00"), processed_for_access=True).pk
        self.payment2_processed = Payment.objects.get(pk=self.payment2_processed_pk)
        self.payment3_new_fail_pk = Payment.objects.create(person=self.person3, amount=Decimal("20.00"), processed_for_access=False).pk
        self.payment3_new_fail = Payment.objects.get(pk=self.payment3_new_fail_pk)
        self.request = MagicMock(); setattr(self.request, 'session', 'session'); messages_storage = FallbackStorage(self.request); setattr(self.request, '_messages', messages_storage)

    @patch('log_viewer_app.admin.process_payment_for_access')
    def test_process_selected_payments_action(self, mock_process_func):
        def side_effect_func(payment_instance):
            if payment_instance.pk == self.payment1_new.pk: return True
            elif payment_instance.pk == self.payment3_new_fail.pk: return False
            return True
        mock_process_func.side_effect = side_effect_func
        payments_list_for_action = [self.payment1_new, self.payment2_processed, self.payment3_new_fail]
        self.assertFalse(self.payment1_new.processed_for_access)
        self.assertTrue(self.payment2_processed.processed_for_access)
        self.assertFalse(self.payment3_new_fail.processed_for_access)
        self.payment_admin.process_selected_payments_action(self.request, payments_list_for_action)
        self.assertEqual(mock_process_func.call_count, 2)
        mock_process_func.assert_any_call(self.payment1_new)
        mock_process_func.assert_any_call(self.payment3_new_fail)
        admin_messages = [m.message for m in list(self.request._messages)]; self.assertIn("1 pago(s) procesado(s) exitosamente.", admin_messages); self.assertIn("1 pago(s) ya habían sido procesados.", admin_messages); self.assertIn("1 pago(s) no pudieron ser procesados.", admin_messages)

    @patch('log_viewer_app.admin.process_payment_for_access')
    def test_process_single_unprocessed_payment(self, mock_process_func):
        mock_process_func.return_value = True
        payment_to_process = self.payment1_new
        self.assertFalse(payment_to_process.processed_for_access)
        single_payment_list = [payment_to_process]
        self.payment_admin.process_selected_payments_action(self.request, single_payment_list)
        mock_process_func.assert_called_once_with(payment_to_process)
        admin_messages = [m.message for m in list(self.request._messages)]; self.assertIn("1 pago(s) procesado(s) exitosamente.", admin_messages); self.assertEqual(len(admin_messages), 1)

# --- API Test Classes ---
class TokenAuthAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='apiuser', password='apipassword123')
        self.token_url = reverse('log_viewer_app:api_auth_token')

    def test_obtain_token_success(self):
        response = self.client.post(self.token_url, {'username': 'apiuser', 'password': 'apipassword123'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertTrue(Token.objects.filter(user=self.user, key=response.data['token']).exists())

    def test_obtain_token_failure_wrong_password(self):
        response = self.client.post(self.token_url, {'username': 'apiuser', 'password': 'wrongpassword'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn('token', response.data)

    def test_obtain_token_failure_non_existent_user(self):
        response = self.client.post(self.token_url, {'username': 'nouser', 'password': 'somepassword'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn('token', response.data)

class AccessVerificationAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testapiuser', password='testpassword')
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.person_allowed = Person.objects.create(full_name="Allowed API User", identifier="QR_API_ALLOW")
        self.ap_main = AccessPoint.objects.create(name="API_Main_Gate")
        AccessPermission.objects.create(person=self.person_allowed, access_point=self.ap_main, is_active=True)
        self.url = reverse('log_viewer_app:api_verify_access')

    def test_verify_access_unauthenticated(self):
        unauth_client = APIClient()
        response = unauth_client.post(self.url, {'qr_identifier': 'QR_API_ALLOW', 'access_point_name': 'API_Main_Gate'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify_access_authenticated_granted(self):
        data = {'qr_identifier': 'QR_API_ALLOW', 'access_point_name': 'API_Main_Gate'}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['access_granted'])
    def test_verify_access_authenticated_denied_no_permission(self):
        data = {'qr_identifier': 'QR_API_DENY_NO_PERM', 'access_point_name': 'API_Main_Gate'}
        Person.objects.create(full_name="No Perm API User", identifier="QR_API_DENY_NO_PERM")
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['access_granted'])
    def test_verify_access_authenticated_denied_person_not_found(self):
        data = {'qr_identifier': 'QR_NON_EXISTENT', 'access_point_name': 'API_Main_Gate'}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['access_granted'])
    def test_verify_access_invalid_request_data_missing_qr(self):
        data = {'access_point_name': 'API_Main_Gate'}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('qr_identifier', response.data)
    def test_verify_access_invalid_request_data_missing_ap(self):
        data = {'qr_identifier': 'QR_API_ALLOW'}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('access_point_name', response.data)

class UserDashboardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.test_user = User.objects.create_user(username='dashboarduser', password='password')
        self.person_profile = Person.objects.create(user=self.test_user, full_name="Dashboard User", identifier="DASH_ID")
        self.ap1 = AccessPoint.objects.create(name="AP Dashboard 1")
        self.ap2 = AccessPoint.objects.create(name="AP Dashboard 2")
        self.ap3 = AccessPoint.objects.create(name="AP Dashboard 3")
        AccessPermission.objects.create(person=self.person_profile, access_point=self.ap1, is_active=True, valid_from=timezone.now(), valid_until=timezone.now() + timedelta(days=5))
        AccessPermission.objects.create(person=self.person_profile, access_point=self.ap2, is_active=True, valid_from=timezone.now() - timedelta(days=10), valid_until=timezone.now() - timedelta(days=5))
        AccessPermission.objects.create(person=self.person_profile, access_point=self.ap3, is_active=False, valid_from=timezone.now(), valid_until=timezone.now() + timedelta(days=5))
        Vehicle.objects.create(owner=self.person_profile, license_plate="DASH123", description="Dash Car 1")
        Vehicle.objects.create(owner=self.person_profile, license_plate="DASH456", description="Dash Car 2")
        self.user_no_profile = User.objects.create_user(username='nouserprofile', password='password')
        self.dashboard_url = reverse('log_viewer_app:user_dashboard')

        # For UserDashboardViewTest - data for subscriptions and invoices
        self.service1 = Service.objects.create(name="Servicio Básico Dashboard", price=Decimal("30.00"))
        self.subscription1 = UserSubscription.objects.create(
            person=self.person_profile,
            service=self.service1,
            start_date=timezone.now().date() - timedelta(days=15),
            billing_cycle='monthly',
            is_active=True
        )
        self.invoice1 = Invoice.objects.create(
            person=self.person_profile,
            user_subscription=self.subscription1,
            invoice_number="INV-DASH-001",
            amount_due=Decimal("30.00"),
            due_date=timezone.now().date() + timedelta(days=10),
            status='pending'
        )
        self.user_with_profile_no_data = User.objects.create_user(username='emptydashuser', password='password')
        self.person_with_profile_no_data = Person.objects.create(user=self.user_with_profile_no_data, full_name="Empty Dash User", identifier="EMPTY_DASH_ID")


    def test_dashboard_redirects_if_not_logged_in(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response.url)

    def test_dashboard_user_without_person_profile(self):
        self.client.login(username='nouserprofile', password='password')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')
        self.assertIsNone(response.context['person_profile'])
        self.assertContains(response, "Tu usuario no está asociado a un perfil de persona")

    def test_dashboard_user_with_profile_displays_data(self): # Updated
        self.client.login(username='dashboarduser', password='password')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')
        self.assertEqual(response.context['person_profile'], self.person_profile)

        # Permissions (only one active and current)
        self.assertEqual(len(response.context['user_permissions']), 1)
        self.assertEqual(response.context['user_permissions'][0].access_point, self.ap1)
        self.assertContains(response, self.ap1.name)
        self.assertNotContains(response, self.ap2.name)
        self.assertNotContains(response, self.ap3.name)

        # Vehicles
        self.assertEqual(len(response.context['user_vehicles']), 2)
        self.assertContains(response, "DASH123")

        # Subscriptions
        self.assertIn('user_subscriptions', response.context)
        self.assertEqual(len(response.context['user_subscriptions']), 1)
        self.assertEqual(response.context['user_subscriptions'][0], self.subscription1)
        self.assertContains(response, self.service1.name)
        self.assertContains(response, f"{self.subscription1.get_effective_price():.2f}")


        # Invoices
        self.assertIn('user_invoices', response.context)
        self.assertEqual(len(response.context['user_invoices']), 1)
        self.assertEqual(response.context['user_invoices'][0], self.invoice1)
        self.assertContains(response, self.invoice1.invoice_number)
        self.assertContains(response, f"{self.invoice1.amount_due:.2f}")


    def test_dashboard_user_with_profile_no_specific_data(self): # Renamed and updated
        self.client.login(username='emptydashuser', password='password')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')
        self.assertEqual(response.context['person_profile'], self.person_with_profile_no_data)

        self.assertEqual(len(response.context['user_permissions']), 0)
        self.assertContains(response, "No tienes permisos de acceso activos o futuros asignados.")

        self.assertEqual(len(response.context['user_vehicles']), 0)
        self.assertContains(response, "No tienes vehículos registrados.")

        self.assertIn('user_subscriptions', response.context)
        self.assertEqual(len(response.context['user_subscriptions']), 0)
        self.assertContains(response, "No tienes suscripciones registradas.")

        self.assertIn('user_invoices', response.context)
        self.assertEqual(len(response.context['user_invoices']), 0)
        self.assertContains(response, "No tienes facturas generadas.")

class UserPermissionsListAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(username='user1perm', password='password1')
        self.person1 = Person.objects.create(full_name="User One Perms", identifier="U1P", user=self.user1)
        self.token1 = Token.objects.create(user=self.user1)
        self.ap1 = AccessPoint.objects.create(name="AP Test 1"); self.ap2 = AccessPoint.objects.create(name="AP Test 2")
        AccessPermission.objects.create(person=self.person1, access_point=self.ap1, is_active=True)
        AccessPermission.objects.create(person=self.person1, access_point=self.ap2, is_active=False)
        self.user2 = User.objects.create_user(username='user2noperm', password='password2')
        self.person2 = Person.objects.create(full_name="User Two No Perms", identifier="U2NP", user=self.user2)
        self.token2 = Token.objects.create(user=self.user2)
        self.user3_no_profile = User.objects.create_user(username='user3noprofile', password='password3')
        self.token3 = Token.objects.create(user=self.user3_no_profile)
        self.url = reverse('log_viewer_app:api_user_permissions')

    def test_list_permissions_unauthenticated(self):
        unauth_client = APIClient(); response = unauth_client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
    def test_list_permissions_user_with_permissions(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key); response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK); self.assertEqual(len(response.data), 2)
        self.assertContains(response, self.person1.full_name) ; self.assertContains(response, self.ap1.name)
    def test_list_permissions_user_no_permissions(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2.key); response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK); self.assertEqual(len(response.data), 0)
    def test_list_permissions_user_no_person_profile(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token3.key); response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK); self.assertEqual(len(response.data), 0)

class QRScannerPageViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.test_user = User.objects.create_user(username='qrscanneruser', password='password123')
        self.ap1 = AccessPoint.objects.create(name="Scanner AP Alpha")
        self.ap2 = AccessPoint.objects.create(name="Scanner AP Beta")
        self.scanner_url = reverse('log_viewer_app:qr_scanner_page')

    def test_scanner_page_redirects_if_not_logged_in(self):
        response = self.client.get(self.scanner_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response.url)

    def test_scanner_page_authenticated_user_loads_correctly(self):
        self.client.login(username='qrscanneruser', password='password123')
        token_obj, created = Token.objects.get_or_create(user=self.test_user)
        response = self.client.get(self.scanner_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/qr_scanner_page.html')
        self.assertIn('access_points', response.context)
        self.assertQuerySetEqual(response.context['access_points'], AccessPoint.objects.all().order_by('name'), transform=lambda x: x)
        self.assertIn('user_auth_token', response.context)
        self.assertEqual(response.context['user_auth_token'], token_obj.key)

    def test_scanner_page_no_access_points(self):
        self.client.login(username='qrscanneruser', password='password123')
        AccessPoint.objects.all().delete()
        response = self.client.get(self.scanner_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_points', response.context)
        self.assertEqual(len(response.context['access_points']), 0)

    def test_scanner_page_token_creation_for_user_without_token(self):
        new_user = User.objects.create_user(username='newtokenuser', password='password123')
        self.client.login(username='newtokenuser', password='password123')
        self.assertFalse(Token.objects.filter(user=new_user).exists())
        response = self.client.get(self.scanner_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Token.objects.filter(user=new_user).exists())
        new_token = Token.objects.get(user=new_user)
        self.assertEqual(response.context['user_auth_token'], new_token.key)

# --- Billing Utils Tests ---
class BillingUtilsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person1 = Person.objects.create(full_name="Bill Utils User", identifier="BUU001")
        cls.service1 = Service.objects.create(name="Bill Utils Service", price=Decimal("10.00"))
        cls.subscription1 = UserSubscription.objects.create(
            person=cls.person1,
            service=cls.service1,
            start_date=dt_date(2023, 1, 1),
            billing_cycle_anchor_day=15,
            is_active=True
        )

    def test_generate_invoice_for_active_subscription(self):
        cycle_date = date(2023, 1, 15) # Use direct 'date'
        invoice, created = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertTrue(created)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.person, self.person1)
        self.assertEqual(invoice.user_subscription, self.subscription1)
        self.assertEqual(invoice.amount_due, self.service1.price)
        self.assertEqual(invoice.status, 'pending')
        self.assertEqual(invoice.invoice_number, f"SUB-{self.subscription1.pk}-{cycle_date.strftime('%Y%m%d')}")
        self.assertEqual(invoice.due_date, cycle_date + timedelta(days=settings.INVOICE_DUE_DAYS))

    def test_generate_invoice_for_inactive_subscription(self):
        self.subscription1.is_active = False
        self.subscription1.save()
        cycle_date = date(2023, 1, 15)
        invoice, created = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertFalse(created)
        self.assertIsNone(invoice)
        self.assertFalse(Invoice.objects.filter(user_subscription=self.subscription1, cycle_start_date=cycle_date).exists())

    def test_generate_invoice_duplicate_avoidance(self):
        cycle_date = date(2023, 1, 15)
        invoice1, created1 = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertTrue(created1)
        self.assertIsNotNone(invoice1)

        invoice2, created2 = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertFalse(created2) # Should not be newly created
        self.assertIsNotNone(invoice2)
        self.assertEqual(invoice1.pk, invoice2.pk)
        self.assertEqual(Invoice.objects.filter(user_subscription=self.subscription1, cycle_start_date=cycle_date).count(), 1)

    def test_generate_invoice_uses_price_override(self):
        self.subscription1.price_override = Decimal("8.88")
        self.subscription1.save()
        cycle_date = date(2023, 1, 15)
        invoice, created = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertTrue(created)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount_due, Decimal("8.88"))

    def test_generate_invoice_correct_due_date(self):
        cycle_date = date(2023, 1, 15)
        invoice, created = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertTrue(created)
        self.assertIsNotNone(invoice)
        expected_due_date = cycle_date + timedelta(days=settings.INVOICE_DUE_DAYS)
        self.assertEqual(invoice.due_date, expected_due_date)

    def test_generate_invoice_respects_subscription_start_date(self):
        cycle_date = self.subscription1.start_date - timedelta(days=1)
        invoice, created = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertFalse(created)
        self.assertIsNone(invoice, "Invoice should not be generated if cycle date is before subscription start date.")

    def test_generate_invoice_respects_subscription_end_date(self):
        self.subscription1.end_date = date(2023, 1, 31)
        self.subscription1.save()
        cycle_date = self.subscription1.end_date + timedelta(days=1)
        invoice, created = generate_invoice_for_subscription(self.subscription1, cycle_date)
        self.assertFalse(created)
        self.assertIsNone(invoice, "Invoice should not be generated if cycle date is after subscription end date.")

# --- Management Command Tests ---

# Test class for the new get_due_cycle_start_date_for_subscription utility
class GetDueCycleStartDateUtilTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = Person.objects.create(full_name="Cycle Test User", identifier="CYCLEU1")
        cls.service_monthly = Service.objects.create(name="Cycle Monthly Service", price=Decimal("50.00"))
        cls.service_once = Service.objects.create(name="Cycle One-Time Service", price=Decimal("200.00"))

        # Monthly subscription starting a while ago
        cls.sub_monthly = UserSubscription.objects.create(
            person=cls.person, service=cls.service_monthly, start_date=date(2023, 1, 10),
            billing_cycle='monthly', billing_cycle_anchor_day=10, is_active=True
        )
        Invoice.objects.create( # Last invoice was for March 10, 2023
            person=cls.person, user_subscription=cls.sub_monthly, cycle_start_date=date(2023, 3, 10),
            invoice_number="INV-MARCH", amount_due=Decimal("50.00"), due_date=date(2023, 3, 25)
        )

        # One-time subscription, not yet invoiced
        cls.sub_once_new = UserSubscription.objects.create(
            person=cls.person, service=cls.service_once, start_date=date(2023, 4, 1),
            billing_cycle='once', billing_cycle_anchor_day=5, is_active=True # Anchor day for 'once' is less common but possible
        )

        # One-time subscription, already invoiced (logic implies this shouldn't be re-calculated as due by this func)
        cls.sub_once_billed = UserSubscription.objects.create(
            person=cls.person, service=cls.service_once, start_date=date(2023, 2, 1),
            billing_cycle='once', billing_cycle_anchor_day=5, is_active=True
        )
        Invoice.objects.create(
            person=cls.person, user_subscription=cls.sub_once_billed, cycle_start_date=date(2023, 2, 1),
            invoice_number="INV-ONCE-BILLED", amount_due=Decimal("200.00"), due_date=date(2023, 2, 16)
        )

        # Monthly subscription, but next cycle is past its end_date
        cls.sub_monthly_ended = UserSubscription.objects.create(
            person=cls.person, service=cls.service_monthly, start_date=date(2023, 1, 20),
            end_date=date(2023, 3, 20), # Ends March 20
            billing_cycle='monthly', billing_cycle_anchor_day=20, is_active=True
        )
        Invoice.objects.create( # Last invoice Feb 20
            person=cls.person, user_subscription=cls.sub_monthly_ended, cycle_start_date=date(2023, 2, 20),
            invoice_number="INV-FEB-ENDED", amount_due=Decimal("50.00"), due_date=date(2023, 3, 7)
        ) # Next cycle would be Mar 20, but it ends on Mar 20. Should still be Mar 20.
           # If next cycle is Apr 20, it should be None.

        # Subscription with no anchor day (should use start_date for first cycle calc for recurring)
        cls.sub_monthly_no_anchor = UserSubscription.objects.create(
            person=cls.person, service=cls.service_monthly, start_date=date(2023, 4, 5),
            billing_cycle='monthly', billing_cycle_anchor_day=None, is_active=True
        )


    def test_monthly_next_cycle_due(self):
        # Last invoice Mar 10, as_of_date Apr 10 -> next cycle is Apr 10
        as_of_date = date(2023, 4, 10)
        due_date = get_due_cycle_start_date_for_subscription(self.sub_monthly, as_of_date)
        self.assertEqual(due_date, date(2023, 4, 10))

    def test_monthly_next_cycle_not_yet_due(self):
        # Last invoice Mar 10, as_of_date Apr 5 -> next cycle Apr 10 is not yet due
        as_of_date = date(2023, 4, 5)
        due_date = get_due_cycle_start_date_for_subscription(self.sub_monthly, as_of_date)
        self.assertIsNone(due_date)

    def test_monthly_first_invoice_due(self):
        sub_new_monthly = UserSubscription.objects.create(
            person=self.person, service=self.service_monthly, start_date=date(2023, 3, 15),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        as_of_date = date(2023, 3, 15)
        # Logic: first_cycle_candidate = 2023-03-15.replace(day=15) = 2023-03-15. <= as_of_date.
        due_date = get_due_cycle_start_date_for_subscription(sub_new_monthly, as_of_date)
        self.assertEqual(due_date, date(2023, 3, 15))

    def test_monthly_first_invoice_anchor_passed_in_start_month(self):
        # Starts Mar 20, anchor day is 15. First invoice should be Apr 15.
        sub_anchor_passed = UserSubscription.objects.create(
            person=self.person, service=self.service_monthly, start_date=date(2023, 3, 20),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        as_of_date_apr_15 = date(2023, 4, 15)
        # Logic: first_cycle_candidate = 2023-03-20.replace(day=15) = 2023-03-15. < start_date. So add 1 month = 2023-04-15.
        due_date = get_due_cycle_start_date_for_subscription(sub_anchor_passed, as_of_date_apr_15)
        self.assertEqual(due_date, date(2023, 4, 15))

        as_of_date_mar_15 = date(2023, 3, 15) # Too early
        due_date_early = get_due_cycle_start_date_for_subscription(sub_anchor_passed, as_of_date_mar_15)
        self.assertIsNone(due_date_early)


    def test_once_new_is_due(self):
        # sub_once_new starts Apr 1. as_of_date Apr 5.
        as_of_date = date(2023, 4, 5)
        due_date = get_due_cycle_start_date_for_subscription(self.sub_once_new, as_of_date)
        self.assertEqual(due_date, self.sub_once_new.start_date) # Should be start_date

    def test_once_new_is_not_yet_due(self):
        # sub_once_new starts Apr 1. as_of_date Mar 30.
        as_of_date = date(2023, 3, 30)
        due_date = get_due_cycle_start_date_for_subscription(self.sub_once_new, as_of_date)
        self.assertIsNone(due_date)

    def test_once_already_billed_returns_its_start_date_if_no_invoice_check(self):
        # This function DOES NOT check for existing invoices. So it will return its start date.
        as_of_date = date(2023, 2, 5) # After start date of sub_once_billed
        due_date = get_due_cycle_start_date_for_subscription(self.sub_once_billed, as_of_date)
        self.assertEqual(due_date, self.sub_once_billed.start_date)

    def test_monthly_ended_before_next_cycle(self):
        # sub_monthly_ended: last billed Feb 20. Ends Mar 20. Next cycle Mar 20.
        # as_of_date Mar 20. Should be due for Mar 20.
        as_of_date_mar_20 = date(2023, 3, 20)
        due_date = get_due_cycle_start_date_for_subscription(self.sub_monthly_ended, as_of_date_mar_20)
        self.assertEqual(due_date, date(2023, 3, 20))

        # as_of_date Apr 20. Next cycle would be Apr 20, but sub ended Mar 20. So, None.
        as_of_date_apr_20 = date(2023, 4, 20)
        due_date_after_end = get_due_cycle_start_date_for_subscription(self.sub_monthly_ended, as_of_date_apr_20)
        self.assertIsNone(due_date_after_end)

    def test_inactive_subscription_returns_none(self):
        as_of_date = date(2023, 1, 15)
        self.sub_monthly.is_active = False; self.sub_monthly.save()
        due_date = get_due_cycle_start_date_for_subscription(self.sub_monthly, as_of_date)
        self.assertIsNone(due_date)
        self.sub_monthly.is_active = True; self.sub_monthly.save() # revert

    def test_monthly_no_anchor_day(self):
        # sub_monthly_no_anchor starts Apr 5, no anchor day.
        # First cycle candidate should be its start_date.
        as_of_date = date(2023, 4, 5)
        due_date = get_due_cycle_start_date_for_subscription(self.sub_monthly_no_anchor, as_of_date)
        self.assertEqual(due_date, date(2023, 4, 5))

        # Check next month if already invoiced for start_date
        Invoice.objects.create(
            person=self.person, user_subscription=self.sub_monthly_no_anchor, cycle_start_date=date(2023, 4, 5),
            invoice_number="INV-NOANCHOR-APR", amount_due=Decimal("50.00"), due_date=date(2023, 4, 20)
        )
        as_of_date_may = date(2023, 5, 5)
        due_date_may = get_due_cycle_start_date_for_subscription(self.sub_monthly_no_anchor, as_of_date_may)
        self.assertEqual(due_date_may, date(2023, 5, 5))


# Tests for the refactored generate_all_due_invoices utility
class GenerateAllDueInvoicesUtilTest(TestCase):
    @classmethod
    def setUpTestData(cls): # Keep this setup, it's good for generate_all_due_invoices
        cls.person1 = Person.objects.create(full_name="Util Test User 1", identifier="UTILU1")
        cls.person2 = Person.objects.create(full_name="Util Test User 2", identifier="UTILU2")
        cls.service_monthly = Service.objects.create(name="Monthly Service Util", price=Decimal("30.00"))
        cls.service_once = Service.objects.create(name="One-Time Service Util", price=Decimal("100.00"))

        # Sub 1: Monthly, active, anchor day matches as_of_date, first invoice due on as_of_date_test (Feb 15)
        cls.sub1_monthly_new = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023, 2, 1), # Start Feb 1
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True # Anchor 15th
        )

        # Sub 2: Monthly, active, anchor day matches, with a prior invoice (next cycle due on as_of_date_test)
        cls.sub2_monthly_recurring = UserSubscription.objects.create(
            person=cls.person2, service=cls.service_monthly, start_date=date(2023, 1, 1), # Started earlier
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        Invoice.objects.create( # Prior invoice for sub2 on Jan 15
            person=cls.person2, user_subscription=cls.sub2_monthly_recurring, cycle_start_date=date(2023, 1, 15),
            invoice_number="PREV-SUB2-20230115", amount_due=Decimal("30.00"), due_date=date(2023, 1, 30)
        ) # Expecting Feb 15 invoice

        # Sub 3: Monthly, active, anchor day does NOT match as_of_date
        cls.sub3_monthly_wrong_anchor = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023, 1, 1), # Will not be processed on Feb 15
            billing_cycle='monthly', billing_cycle_anchor_day=16, is_active=True
        )

        # Sub 4: One-time, active, not yet invoiced, anchor day matches as_of_date_test (Feb 15)
        # Its cycle_start_for_invoice will be its start_date.
        cls.sub4_once_new = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_once, start_date=date(2023, 2, 10),
            billing_cycle='once', billing_cycle_anchor_day=15, is_active=True
        )

        # Sub 5: One-time, active, already invoiced (start_date was Jan 5, anchor 15th - so it was due on Jan 15th for its start_date)
        # This setup is a bit complex for "already invoiced one-time".
        # A one-time invoice is typically for its start_date. If anchor_day is different, it means it's due on the first anchor_day
        # on or after its start_date.
        # Let's simplify: sub5_once_existing's start_date *is* its cycle_start_date.
        cls.sub5_once_existing = UserSubscription.objects.create(
            person=cls.person2, service=cls.service_once, start_date=date(2023, 1, 15),
            billing_cycle='once', billing_cycle_anchor_day=15, is_active=True
        )
        Invoice.objects.create(
            person=cls.person2, user_subscription=cls.sub5_once_existing, cycle_start_date=cls.sub5_once_existing.start_date,
            invoice_number="PREV-SUB5-20230115", amount_due=Decimal("100.00"), due_date=date(2023, 1, 30)
        )

        # Sub 6: Monthly, active, anchor day matches, but next cycle (Mar 15) is in the future from as_of_date_test (Feb 15)
        cls.sub6_monthly_future_cycle = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023, 2, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        Invoice.objects.create( # Invoice for Feb 15 already exists
            person=cls.person1, user_subscription=cls.sub6_monthly_future_cycle, cycle_start_date=date(2023, 2, 15),
            invoice_number="PREV-SUB6-20230215", amount_due=Decimal("30.00"), due_date=date(2023, 3, 2)
        ) # So, next cycle is Mar 15, which is after as_of_date_test (Feb 15)

        # Sub 7: Inactive subscription, anchor day matches - should be ignored by main query
        cls.sub7_inactive = UserSubscription.objects.create(
            person=cls.person2, service=cls.service_monthly, start_date=date(2023, 1, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=False
        )

        # Sub 8: Subscription with billing_cycle_anchor_day = None - should be skipped and counted in failed/skipped
        cls.sub8_no_anchor = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023, 1, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=None, is_active=True
        )

    @patch('log_viewer_app.billing_utils.generate_invoice_for_subscription') # Mock the lower-level invoice creation
    @patch('log_viewer_app.billing_utils.get_due_cycle_start_date_for_subscription') # Mock the helper we are indirectly testing via generate_all_due_invoices
    def test_generate_all_due_invoices_orchestration(self, mock_get_due_cycle_date, mock_generate_invoice):
        as_of_date_test = date(2023, 2, 15)

        # Define behavior for mock_get_due_cycle_date
        def get_due_date_side_effect(subscription, as_of_date_arg):
            if as_of_date_arg != as_of_date_test: return None # Should always be called with as_of_date_test
            if subscription == self.sub1_monthly_new: return date(2023, 2, 15)
            if subscription == self.sub2_monthly_recurring: return date(2023, 2, 15)
            if subscription == self.sub4_once_new: return self.sub4_once_new.start_date
            if subscription == self.sub5_once_existing: return self.sub5_once_existing.start_date
            # sub3_monthly_wrong_anchor: get_due_cycle_start_date_for_subscription would return a date,
            # but generate_all_due_invoices filters by anchor day first. So it won't be called for sub3.
            # sub6_monthly_future_cycle: get_due_cycle_start_date_for_subscription would return None (next cycle Mar 15)
            if subscription == self.sub6_monthly_future_cycle: return None
            return None # Default for others not explicitly handled (like sub7_inactive, sub8_no_anchor - though they are filtered earlier)
        mock_get_due_cycle_date.side_effect = get_due_date_side_effect

        # Define behavior for mock_generate_invoice
        mock_invoice_sub1 = MagicMock(spec=Invoice); mock_invoice_sub1.invoice_number = "INV_SUB1"
        mock_invoice_sub2 = MagicMock(spec=Invoice); mock_invoice_sub2.invoice_number = "INV_SUB2"
        mock_invoice_sub4 = MagicMock(spec=Invoice); mock_invoice_sub4.invoice_number = "INV_SUB4"
        # For sub5, an actual invoice exists, so generate_invoice_for_subscription should return that and created=False
        actual_invoice_sub5 = Invoice.objects.get(user_subscription=self.sub5_once_existing)

        def generate_invoice_side_effect(subscription, cycle_start_date):
            if subscription == self.sub1_monthly_new: return mock_invoice_sub1, True
            if subscription == self.sub2_monthly_recurring: return mock_invoice_sub2, True
            if subscription == self.sub4_once_new: return mock_invoice_sub4, True
            if subscription == self.sub5_once_existing: return actual_invoice_sub5, False # Already exists
            return None, False
        mock_generate_invoice.side_effect = generate_invoice_side_effect

        new_gen, existed, failed_skipped = generate_all_due_invoices(as_of_date=as_of_date_test)

        # Assertions
        # generate_all_due_invoices filters by anchor day first.
        # Expected calls to get_due_cycle_start_date_for_subscription:
        # sub1 (anchor 15 - yes), sub2 (anchor 15 - yes), sub4 (anchor 15 - yes),
        # sub5 (anchor 15 - yes), sub6 (anchor 15 - yes)
        # sub3 (anchor 16 - no), sub7 (inactive - no by main query), sub8 (no anchor - skip, fail count incremented)
        self.assertEqual(mock_get_due_cycle_date.call_count, 5) # sub1, sub2, sub4, sub5, sub6

        # Expected calls to generate_invoice_for_subscription (based on get_due_cycle_date side_effect):
        # sub1 (returns date), sub2 (returns date), sub4 (returns date), sub5 (returns date)
        # sub6 (get_due_cycle_date returns None for it)
        self.assertEqual(mock_generate_invoice.call_count, 4)
        mock_generate_invoice.assert_any_call(self.sub1_monthly_new, date(2023, 2, 15))
        mock_generate_invoice.assert_any_call(self.sub2_monthly_recurring, date(2023, 2, 15))
        mock_generate_invoice.assert_any_call(self.sub4_once_new, self.sub4_once_new.start_date)
        mock_generate_invoice.assert_any_call(self.sub5_once_existing, self.sub5_once_existing.start_date)

        self.assertEqual(new_gen, 3, "Should be 3 newly generated invoices (sub1, sub2, sub4)")
        self.assertEqual(existed, 1, "Should be 1 existing invoice (sub5)")
        self.assertEqual(failed_skipped, 1, "Should be 1 failed/skipped (sub8_no_anchor due to no anchor day)")


# Refactored command test
class GeneratePeriodicInvoicesCommandTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Minimal setup, as the utility function is tested separately.
        # We just need to ensure the command can run.
        # No specific subscriptions needed here if we are mocking generate_all_due_invoices
        pass

    @patch('log_viewer_app.management.commands.generate_periodic_invoices.generate_all_due_invoices')
    @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    def test_command_calls_utility_and_reports(self, mock_timezone, mock_generate_all):
        mock_today = date(2023, 3, 20)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        # Define what the mocked utility function will return
        mock_generate_all.return_value = (2, 1, 0) # 2 new, 1 existed, 0 failed

        out = StringIO()
        call_command('generate_periodic_invoices', stdout=out)

        # Verify generate_all_due_invoices was called correctly
        mock_generate_all.assert_called_once_with(as_of_date=mock_today)

        # Verify command output
        output = out.getvalue()
        self.assertIn("Iniciando generación de facturas periódicas...", output)
        self.assertIn("Se generaron 2 nueva(s) factura(s).", output)
        self.assertIn("1 factura(s) ya existían para el ciclo actual y fueron omitidas.", output)
        self.assertNotIn("suscripciones fueron omitidas o fallaron", output) # 0 failed
        self.assertIn("Proceso de generación de facturas periódicas completado.", output)

    @patch('log_viewer_app.management.commands.generate_periodic_invoices.generate_all_due_invoices')
    @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    def test_command_reports_no_new_invoices(self, mock_timezone, mock_generate_all):
        mock_today = date(2023, 3, 21)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)
        mock_generate_all.return_value = (0, 0, 0) # No invoices generated or failed

        # Mock UserSubscription.objects.filter().count() for the specific message
        with patch('log_viewer_app.management.commands.generate_periodic_invoices.UserSubscription.objects.filter') as mock_filter:
            mock_filter.return_value.count.return_value = 5 # Simulate 5 active subs

            out = StringIO()
            call_command('generate_periodic_invoices', stdout=out)

            mock_generate_all.assert_called_once_with(as_of_date=mock_today)
            output = out.getvalue()
            self.assertNotIn("nueva(s) factura(s)", output)
            self.assertNotIn("ya existían", output)
            self.assertIn("No hay facturas debidas para generar en este momento según los días de anclaje y ciclos.", output)

    @patch('log_viewer_app.management.commands.generate_periodic_invoices.generate_all_due_invoices')
    @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    def test_command_reports_no_active_subscriptions(self, mock_timezone, mock_generate_all):
        mock_today = date(2023, 3, 22)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)
        mock_generate_all.return_value = (0, 0, 0)

        with patch('log_viewer_app.management.commands.generate_periodic_invoices.UserSubscription.objects.filter') as mock_filter:
            mock_filter.return_value.count.return_value = 0 # Simulate 0 active subs

            out = StringIO()
            call_command('generate_periodic_invoices', stdout=out)

            mock_generate_all.assert_called_once_with(as_of_date=mock_today)
            output = out.getvalue()
            self.assertIn("No hay suscripciones activas para facturar.", output)


    # Old tests for GeneratePeriodicInvoicesCommandTest are removed as they tested
    # the direct invoice generation logic which is now in generate_all_due_invoices
    # and tested by GenerateAllDueInvoicesUtilTest.

    # @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    # def test_command_generates_invoices_correctly(self, mock_timezone):
    #     ...
    # @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    # def test_command_handles_existing_invoice(self, mock_timezone):
    #     ...
    # @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    # def test_command_no_active_subscriptions(self, mock_timezone):
    #     ...
    # @patch('log_viewer_app.management.commands.generate_periodic_invoices.timezone')
    # def test_command_output_contains_summary(self, mock_timezone):
    #     ...

# Old BillingUtilsTest might need to be removed or heavily adapted if generate_all_due_invoices
# is the primary public interface now. The existing BillingUtilsTest tests generate_invoice_for_subscription.
# It should remain to test that lower-level function.
# The prompt asks to "Update Pruebas Unitarias", implying modifying existing ones and adding new ones.
# BillingUtilsTest (for generate_invoice_for_subscription) remains valid for the lower-level function.

# The OldGeneratePeriodicInvoicesCommandTest class is now removed.
