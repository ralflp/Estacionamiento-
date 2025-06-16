from django.test import TestCase
from django.urls import reverse
from .models import (
    AccessLog, Person, Vehicle, AccessPoint, AccessPermission,
    ControlDevice, Payment, Service, UserSubscription, Invoice # Added Service, UserSubscription, Invoice
)
from .forms import PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm
from .utils import verify_access_with_models, publish_mqtt_message, process_payment_for_access
from django.utils import timezone
from datetime import timedelta, date as dt_date, datetime as dt_datetime
from decimal import Decimal # Added for Decimal comparisons
from unittest.mock import patch, MagicMock, call as mock_call
from django.conf import settings
from django.contrib import admin
from django.contrib.messages.storage.fallback import FallbackStorage
from .admin import PaymentAdmin

# DRF Test specific imports
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework import status
from .serializers import AccessRequestSerializer, AccessResponseSerializer, AccessPermissionSerializer


# --- Model Tests ---
class PersonModelTest(TestCase):
    def test_person_creation(self):
        person = Person.objects.create(full_name="John Doe", identifier="JD001")
        self.assertIsInstance(person, Person)
        self.assertEqual(person.full_name, "John Doe")
        self.assertEqual(person.identifier, "JD001")
        self.assertIsNotNone(person.created_at)
        self.assertIsNotNone(person.updated_at)
        self.assertEqual(str(person), "John Doe (JD001)")

class VehicleModelTest(TestCase):
    def setUp(self):
        self.owner = Person.objects.create(full_name="Jane Smith", identifier="JS002")

    def test_vehicle_creation(self):
        vehicle = Vehicle.objects.create(
            owner=self.owner, license_plate="XYZ123", description="Red Car"
        )
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
        permission = AccessPermission.objects.create(
            person=self.person, access_point=self.access_point, is_active=True,
            valid_from=now, valid_until=now + timedelta(days=30)
        )
        self.assertIsInstance(permission, AccessPermission)
        self.assertIn("Alice Wonderland", str(permission))
        self.assertIn("Activo", str(permission))

    def test_access_permission_unique_together(self):
        AccessPermission.objects.create(person=self.person, access_point=self.access_point)
        with self.assertRaises(Exception):
            AccessPermission.objects.create(person=self.person, access_point=self.access_point)

class ControlDeviceModelTest(TestCase):
    def setUp(self):
        self.ap = AccessPoint.objects.create(name="Garage Door AP")

    def test_control_device_creation(self):
        device = ControlDevice.objects.create(
            name="Garage Controller 1", device_id="GDCTRL001", access_point=self.ap,
            mqtt_topic="garage/door1/control", ip_address="192.168.1.100", is_active=True
        )
        self.assertIsInstance(device, ControlDevice)
        self.assertEqual(str(device), "Garage Controller 1 (GDCTRL001) - AP: Garage Door AP")

    def test_control_device_str_no_ap(self):
        device = ControlDevice.objects.create(name="Unassigned Controller", device_id="UCTRL002", mqtt_topic="unassigned/control")
        self.assertEqual(str(device), "Unassigned Controller (UCTRL002) - AP: No asignado")

class PaymentModelTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(full_name="Payment User", identifier="PU001")

    def test_payment_creation(self):
        payment_time_before = timezone.now() - timedelta(seconds=1)
        payment = Payment.objects.create(
            person=self.person,
            amount=Decimal("50.00"), # Use Decimal for currency
            payment_method='tarjeta_credito',
            reference_number='TXN12345'
        )
        payment_time_after = timezone.now() + timedelta(seconds=1)

        self.assertIsInstance(payment, Payment)
        self.assertEqual(payment.person, self.person)
        self.assertEqual(payment.amount, Decimal("50.00"))
        self.assertEqual(payment.payment_method, 'tarjeta_credito')
        self.assertFalse(payment.processed_for_access)
        self.assertTrue(payment_time_before <= payment.payment_date <= payment_time_after)
        self.assertIn(f"Pago de {payment.amount:.2f} por Payment User", str(payment))

class ServiceModelTest(TestCase):
    def test_service_creation(self):
        service = Service.objects.create(
            name="Estacionamiento Mensual",
            description="Acceso mensual al estacionamiento.",
            price=Decimal("75.50")
        )
        self.assertIsInstance(service, Service)
        self.assertEqual(service.name, "Estacionamiento Mensual")
        self.assertEqual(service.price, Decimal("75.50"))
        self.assertEqual(str(service), "Estacionamiento Mensual - $75.50")

class UserSubscriptionModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = Person.objects.create(full_name="Subscriber User", identifier="SUB001")
        cls.service = Service.objects.create(name="Servicio Básico", price=Decimal("100.00"))
        cls.service_premium = Service.objects.create(name="Servicio Premium", price=Decimal("200.00"))

    def test_user_subscription_creation(self):
        start_date = dt_date(2024, 1, 1)
        end_date = dt_date(2024, 12, 31)
        subscription = UserSubscription.objects.create(
            person=self.person,
            service=self.service,
            start_date=start_date,
            end_date=end_date,
            billing_cycle='annually',
            is_active=True
        )
        self.assertIsInstance(subscription, UserSubscription)
        self.assertEqual(subscription.person, self.person)
        self.assertEqual(subscription.service, self.service)
        self.assertEqual(subscription.start_date, start_date)
        self.assertEqual(subscription.billing_cycle, 'annually')
        self.assertTrue(subscription.is_active)
        expected_str = f"Suscripción de Subscriber User a Servicio Básico (Activa) - ${self.service.price:.2f} (Anual). Fin: {end_date.strftime('%Y-%m-%d')}"
        self.assertEqual(str(subscription), expected_str)

    def test_get_effective_price_no_override(self):
        subscription = UserSubscription.objects.create(person=self.person, service=self.service)
        self.assertEqual(subscription.get_effective_price(), self.service.price)

    def test_get_effective_price_with_override(self):
        override_price = Decimal("90.00")
        subscription = UserSubscription.objects.create(
            person=self.person, service=self.service, price_override=override_price
        )
        self.assertEqual(subscription.get_effective_price(), override_price)

class InvoiceModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person = Person.objects.create(full_name="Invoice User", identifier="INV001")
        cls.service = Service.objects.create(name="Servicio Facturable", price=Decimal("150.00"))
        cls.subscription = UserSubscription.objects.create(person=cls.person, service=cls.service)

    def test_invoice_creation(self):
        due_date = dt_date(2024, 7, 31)
        invoice = Invoice.objects.create(
            person=self.person,
            user_subscription=self.subscription,
            invoice_number="INV-2024-001",
            amount_due=Decimal("150.00"),
            due_date=due_date,
            status='pending'
        )
        self.assertIsInstance(invoice, Invoice)
        self.assertEqual(invoice.invoice_number, "INV-2024-001")
        self.assertEqual(invoice.amount_due, Decimal("150.00"))
        self.assertEqual(invoice.status, "pending")
        expected_str = f"Factura INV-2024-001 para Invoice User - ${invoice.amount_due:.2f} (Estado: Pendiente)"
        self.assertEqual(str(invoice), expected_str)


# --- Form Tests ---
# ... (Existing Form Tests remain here) ...
class PersonFormTest(TestCase):
    def test_person_form_valid_data(self): form = PersonForm(data={'full_name': 'Form User', 'identifier': 'FU001'}); self.assertTrue(form.is_valid())
    def test_person_form_invalid_missing_identifier(self): form = PersonForm(data={'full_name': 'Form User No ID'}); self.assertFalse(form.is_valid()); self.assertIn('identifier', form.errors)
    def test_person_form_save(self): form = PersonForm(data={'full_name': 'Save User', 'identifier': 'SU001'}); self.assertTrue(form.is_valid()); person = form.save(); self.assertIsInstance(person, Person); self.assertEqual(person.identifier, 'SU001')

class VehicleFormTest(TestCase):
    def setUp(self): self.owner = Person.objects.create(full_name="Owner Test", identifier="OT001")
    def test_vehicle_form_valid_data(self): form = VehicleForm(data={'owner': self.owner.pk, 'license_plate': 'VF123', 'description': 'Test Vehicle'}); self.assertTrue(form.is_valid())
    def test_vehicle_form_invalid_missing_plate(self): form = VehicleForm(data={'owner': self.owner.pk}); self.assertFalse(form.is_valid()); self.assertIn('license_plate', form.errors)

class AccessPermissionFormTest(TestCase):
    def setUp(self): self.person = Person.objects.create(full_name="Perm Form Person", identifier="PFP01"); self.ap = AccessPoint.objects.create(name="Perm Form AP")
    def test_access_permission_form_valid_data(self): form = AccessPermissionForm(data={'person': self.person.pk, 'access_point': self.ap.pk, 'is_active': True, 'valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'), 'valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')}); self.assertTrue(form.is_valid())
    def test_access_permission_form_save(self): form = AccessPermissionForm(data={'person': self.person.pk, 'access_point': self.ap.pk, 'is_active': True}); self.assertTrue(form.is_valid()); permission = form.save(); self.assertIsInstance(permission, AccessPermission); self.assertTrue(permission.is_active)

class ControlDeviceFormTest(TestCase):
    def setUp(self): self.ap = AccessPoint.objects.create(name="Device Form AP")
    def test_control_device_form_valid_data(self): form = ControlDeviceForm(data={'name': 'Test Device', 'device_id': 'DEVFORM001', 'access_point': self.ap.pk, 'mqtt_topic': 'test/device/topic', 'is_active': True}); self.assertTrue(form.is_valid())
    def test_control_device_form_invalid_missing_device_id(self): form = ControlDeviceForm(data={'name': 'Test Device No ID'}); self.assertFalse(form.is_valid()); self.assertIn('device_id', form.errors)
    def test_control_device_form_save(self): form = ControlDeviceForm(data={'name': 'Save Device', 'device_id': 'SDEV001', 'access_point': self.ap.pk, 'mqtt_topic': 'save/device/topic'}); self.assertTrue(form.is_valid()); device = form.save(); self.assertIsInstance(device, ControlDevice); self.assertEqual(device.device_id, 'SDEV001')


# --- View Tests ---
# ... (Existing View Tests remain here) ...
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
        original_mqtt_user = getattr(settings, 'MQTT_USERNAME', None)
        original_mqtt_pass = getattr(settings, 'MQTT_PASSWORD', None)
        if hasattr(settings, 'MQTT_USERNAME'): delattr(settings, 'MQTT_USERNAME')
        if hasattr(settings, 'MQTT_PASSWORD'): delattr(settings, 'MQTT_PASSWORD')

        current_broker_host = 'testbroker_success'
        current_broker_port = 18830
        current_client_id = 'testclient_success'

        settings.MQTT_BROKER_HOST = current_broker_host
        settings.MQTT_BROKER_PORT = current_broker_port
        settings.MQTT_CLIENT_ID = current_client_id

        result = publish_mqtt_message("test/topic", "payload_test")
        self.assertTrue(result)
        mock_publish_single.assert_called_once_with(
            "test/topic", payload="payload_test", qos=1, retain=False,
            hostname=current_broker_host, port=current_broker_port, client_id=current_client_id, auth=None
        )
        if original_mqtt_user is not None : setattr(settings, 'MQTT_USERNAME', original_mqtt_user)
        if original_mqtt_pass is not None : setattr(settings, 'MQTT_PASSWORD', original_mqtt_pass)
        settings.MQTT_BROKER_HOST = 'localhost'
        settings.MQTT_BROKER_PORT = 1883


    @patch('log_viewer_app.utils.publish.single')
    def test_publish_mqtt_message_with_auth(self, mock_publish_single):
        settings.MQTT_BROKER_HOST = 'authbroker'
        settings.MQTT_BROKER_PORT = 18831
        settings.MQTT_CLIENT_ID = 'authclient'
        settings.MQTT_USERNAME = 'user'
        settings.MQTT_PASSWORD = 'pass'
        result = publish_mqtt_message("auth/topic", "auth_payload")
        self.assertTrue(result)
        mock_publish_single.assert_called_once_with(
            "auth/topic", payload="auth_payload", qos=1, retain=False,
            hostname='authbroker', port=18831, client_id='authclient', auth={'username': 'user', 'password': 'pass'}
        )

    @patch('log_viewer_app.utils.publish.single', side_effect=ConnectionRefusedError("Test refuse"))
    @patch('log_viewer_app.utils.logger.error')
    def test_publish_mqtt_connection_refused(self, mock_logger_error, mock_publish_single):
        original_host = settings.MQTT_BROKER_HOST
        original_port = settings.MQTT_BROKER_PORT

        settings.MQTT_BROKER_HOST = 'refused_broker_for_test'
        settings.MQTT_BROKER_PORT = 12345

        result = publish_mqtt_message("refuse/topic", "refuse_payload")
        self.assertFalse(result)
        expected_message = f"MQTT Error: Conexión rechazada al broker {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}. Verifica que el broker esté activo y accesible."

        called_with_expected_message = False
        for call_args in mock_logger_error.call_args_list:
            if call_args[0][0] == expected_message:
                called_with_expected_message = True
                break
        self.assertTrue(called_with_expected_message, f"Expected log message not found. Actual calls: {mock_logger_error.call_args_list}")

        settings.MQTT_BROKER_HOST = original_host
        settings.MQTT_BROKER_PORT = original_port


    @patch('log_viewer_app.utils.publish.single', side_effect=Exception("Generic MQTT error"))
    @patch('log_viewer_app.utils.logger.error')
    def test_publish_mqtt_generic_exception(self, mock_logger_error, mock_publish_single):
        result = publish_mqtt_message("generic/topic", "generic_payload")
        self.assertFalse(result)
        mock_logger_error.assert_called_with(
            "MQTT Error: No se pudo publicar en tópico 'generic/topic'. Error: Generic MQTT error"
        )

class VerifyAccessLogicTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person1 = Person.objects.create(full_name="Allowed User", identifier="ALLOW_ID")
        cls.person2 = Person.objects.create(full_name="NoPerm User", identifier="NOPERM_ID")
        cls.person3 = Person.objects.create(full_name="InactivePerm User", identifier="INACTIVE_ID")
        cls.person4 = Person.objects.create(full_name="FuturePerm User", identifier="FUTURE_ID")
        cls.person5 = Person.objects.create(full_name="ExpiredPerm User", identifier="EXPIRED_ID")
        cls.person6 = Person.objects.create(full_name="TimeValid User", identifier="TIMEVALID_ID")
        cls.ap1 = AccessPoint.objects.create(name="MainDoor")
        cls.ap_mqtt = AccessPoint.objects.create(name="MQTT_Controlled_Door")
        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap1, is_active=True)
        AccessPermission.objects.create(person=cls.person3, access_point=cls.ap1, is_active=False)
        AccessPermission.objects.create(person=cls.person4, access_point=cls.ap1, is_active=True, valid_from=timezone.now() + timedelta(days=1))
        AccessPermission.objects.create(person=cls.person5, access_point=cls.ap1, is_active=True, valid_until=timezone.now() - timedelta(days=1))
        AccessPermission.objects.create(person=cls.person6, access_point=cls.ap1, is_active=True, valid_from=timezone.now() - timedelta(hours=1), valid_until=timezone.now() + timedelta(hours=1))
        cls.device1_ap_mqtt = ControlDevice.objects.create(name="MQTT_Door_Ctrl1", device_id="CTRL_MQTT1", access_point=cls.ap_mqtt, mqtt_topic="door/mqtt1/open", is_active=True)
        cls.person_mqtt = Person.objects.create(full_name="MQTT Access User", identifier="MQTT_ACCESS_ID")
        AccessPermission.objects.create(person=cls.person_mqtt, access_point=cls.ap_mqtt, is_active=True)

    def tearDown(self):
        AccessLog.objects.all().delete()

    def test_access_allowed(self):
        self.assertTrue(verify_access_with_models("ALLOW_ID", "MainDoor"))

    def test_person_not_found(self):
        self.assertFalse(verify_access_with_models("UNKNOWN_ID", "MainDoor"))

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_triggers_mqtt_publish_single_device(self, mock_publish):
        mock_publish.return_value=True
        self.assertTrue(verify_access_with_models("MQTT_ACCESS_ID", "MQTT_Controlled_Door"))
        mock_publish.assert_called_once_with(topic=self.device1_ap_mqtt.mqtt_topic, payload="OPEN")

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_no_active_devices(self, mock_publish):
        ControlDevice.objects.filter(device_id="CTRL_MQTT1").update(is_active=False)
        self.assertTrue(verify_access_with_models("MQTT_ACCESS_ID", "MQTT_Controlled_Door"))
        mock_publish.assert_not_called()
        ControlDevice.objects.filter(device_id="CTRL_MQTT1").update(is_active=True)

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_denied_no_mqtt_publish(self, mock_publish):
        self.assertFalse(verify_access_with_models("NOPERM_ID", "MQTT_Controlled_Door"))
        mock_publish.assert_not_called()

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_multiple_active_devices_mqtt_publish(self, mock_publish):
        mock_publish.return_value=True
        dev_extra = ControlDevice.objects.create(name="ExtraDev", device_id="EXTRA01", access_point=self.ap_mqtt, mqtt_topic="extra/topic", is_active=True)
        self.assertTrue(verify_access_with_models("MQTT_ACCESS_ID", "MQTT_Controlled_Door"))
        self.assertEqual(mock_publish.call_count, 2)
        topics = [c.kwargs['topic'] for c in mock_publish.call_args_list]
        self.assertCountEqual(topics, [self.device1_ap_mqtt.mqtt_topic, dev_extra.mqtt_topic])
        dev_extra.delete()

    def test_access_point_not_found(self):
        self.assertFalse(verify_access_with_models("ALLOW_ID", "NonExistentDoor"))

    def test_permission_not_found(self):
        self.assertFalse(verify_access_with_models("NOPERM_ID", "MainDoor"))

    def test_permission_inactive(self):
        self.assertFalse(verify_access_with_models("INACTIVE_ID", "MainDoor"))

    def test_permission_future_valid_from(self):
        self.assertFalse(verify_access_with_models("FUTURE_ID", "MainDoor"))

    def test_permission_expired_valid_until(self):
        self.assertFalse(verify_access_with_models("EXPIRED_ID", "MainDoor"))

    def test_permission_time_valid(self):
        self.assertTrue(verify_access_with_models("TIMEVALID_ID", "MainDoor"))

    def test_permission_valid_from_only_no_end(self):
        p, _ = Person.objects.get_or_create(identifier="NOEND_ID", defaults={'full_name':"PermNoEnd User"})
        AccessPermission.objects.get_or_create(person=p,access_point=self.ap1,defaults={'is_active':True,'valid_from':timezone.now()-timedelta(days=1),'valid_until':None})
        self.assertTrue(verify_access_with_models("NOEND_ID", "MainDoor"))

    def test_permission_default_valid_from_no_end(self):
        p, _ = Person.objects.get_or_create(identifier="DEFAULTSTART_ID", defaults={'full_name':"PermDefaultStart User"})
        AccessPermission.objects.get_or_create(person=p,access_point=self.ap1,defaults={'is_active':True,'valid_until':None})
        self.assertTrue(verify_access_with_models("DEFAULTSTART_ID", "MainDoor"))

# --- New Tests for Payment Processing ---
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

    def test_payment_no_person(self):
        payment = Payment.objects.create(amount=10.00, person=None)
        self.assertFalse(process_payment_for_access(payment))
        payment.refresh_from_db()
        self.assertFalse(payment.processed_for_access)

    def test_payment_already_processed(self):
        payment = Payment.objects.create(person=self.person1, amount=10.00, processed_for_access=True)
        self.assertTrue(process_payment_for_access(payment))
        self.assertFalse(AccessPermission.objects.filter(person=self.person1).exists())

    def test_new_user_no_permissions_creates_default(self):
        payment_date = timezone.make_aware(dt_datetime(2023, 1, 15, 10, 0, 0))
        payment = Payment.objects.create(person=self.person1, amount=10.00, payment_date=payment_date)
        self.assertTrue(process_payment_for_access(payment))
        payment.refresh_from_db()
        self.assertTrue(payment.processed_for_access)
        perms = AccessPermission.objects.filter(person=self.person1)
        self.assertEqual(perms.count(), 1)
        perm = perms.first()
        self.assertEqual(perm.access_point, self.ap1)
        self.assertTrue(perm.is_active)
        self.assertEqual(perm.valid_from, payment_date)
        self.assertEqual(perm.valid_until, payment_date + timedelta(days=30))

    def test_new_user_no_default_ap_available(self):
        AccessPoint.objects.all().delete()
        payment = Payment.objects.create(person=self.person4, amount=10.00)
        self.assertFalse(process_payment_for_access(payment))
        payment.refresh_from_db()
        self.assertFalse(payment.processed_for_access)
        self.ap1 = AccessPoint.objects.create(name="Main Entrance") # Recreate

    def test_existing_user_one_expired_permission(self):
        payment_date = timezone.now()
        payment = Payment.objects.create(person=self.person2, amount=10.00, payment_date=payment_date)
        self.assertTrue(process_payment_for_access(payment))
        payment.refresh_from_db()
        self.assertTrue(payment.processed_for_access)
        perm = AccessPermission.objects.get(person=self.person2, access_point=self.ap1)
        self.assertTrue(perm.is_active)
        self.assertEqual(perm.valid_from, payment_date)
        self.assertEqual(perm.valid_until, payment_date + timedelta(days=30))

    def test_existing_user_one_active_permission_extends_from_valid_until(self):
        payment_date = self.active_perm_p3_ap1.valid_from
        payment = Payment.objects.create(person=self.person3, amount=10.00, payment_date=payment_date)

        original_valid_from_ap1 = self.active_perm_p3_ap1.valid_from
        original_valid_until_ap1 = self.active_perm_p3_ap1.valid_until
        original_valid_from_ap2 = self.active_perm_p3_ap2.valid_from
        original_valid_until_ap2 = self.active_perm_p3_ap2.valid_until

        self.assertTrue(process_payment_for_access(payment))
        payment.refresh_from_db()
        self.assertTrue(payment.processed_for_access)

        perm_ap1 = AccessPermission.objects.get(pk=self.active_perm_p3_ap1.pk)
        self.assertTrue(perm_ap1.is_active)
        self.assertEqual(perm_ap1.valid_from, original_valid_from_ap1)
        self.assertEqual(perm_ap1.valid_until, original_valid_until_ap1 + timedelta(days=30))

        perm_ap2 = AccessPermission.objects.get(pk=self.active_perm_p3_ap2.pk)
        self.assertTrue(perm_ap2.is_active)
        self.assertEqual(perm_ap2.valid_from, payment_date)
        self.assertEqual(perm_ap2.valid_until, original_valid_until_ap2 + timedelta(days=30))

    def test_existing_user_permission_no_expiry_sets_from_payment_date(self):
        p, _ = Person.objects.get_or_create(identifier="PAY_USER_NOEXPIRY", defaults={'full_name': "User No Expiry"})
        perm = AccessPermission.objects.create(person=p, access_point=self.ap1, is_active=True, valid_until=None)
        payment_date = timezone.now()
        payment = Payment.objects.create(person=p, amount=10.00, payment_date=payment_date)
        self.assertTrue(process_payment_for_access(payment))
        perm.refresh_from_db()
        self.assertTrue(perm.is_active)
        self.assertEqual(perm.valid_until, payment_date + timedelta(days=30))

# --- Admin Action Tests ---
class PaymentAdminActionTest(TestCase):
    def setUp(self):
        self.site = admin.AdminSite()
        self.payment_admin = PaymentAdmin(Payment, self.site)
        self.person1 = Person.objects.create(full_name="AdminAction User1", identifier="AAU001")
        self.person2 = Person.objects.create(full_name="AdminAction User2", identifier="AAU002")
        self.person3 = Person.objects.create(full_name="AdminAction User3", identifier="AAU003")
        AccessPoint.objects.get_or_create(name="Main Entrance")

        self.payment1_new_pk = Payment.objects.create(person=self.person1, amount=20.00, processed_for_access=False).pk
        self.payment1_new = Payment.objects.get(pk=self.payment1_new_pk)

        self.payment2_processed_pk = Payment.objects.create(person=self.person2, amount=20.00, processed_for_access=True).pk
        self.payment2_processed = Payment.objects.get(pk=self.payment2_processed_pk)

        self.payment3_new_fail_pk = Payment.objects.create(person=self.person3, amount=20.00, processed_for_access=False).pk
        self.payment3_new_fail = Payment.objects.get(pk=self.payment3_new_fail_pk)

        self.request = MagicMock()
        setattr(self.request, 'session', 'session')
        messages_storage = FallbackStorage(self.request)
        setattr(self.request, '_messages', messages_storage)

    @patch('log_viewer_app.admin.process_payment_for_access')
    def test_process_selected_payments_action(self, mock_process_func):
        def side_effect_func(payment_instance):
            if payment_instance.pk == self.payment1_new.pk: return True
            elif payment_instance.pk == self.payment3_new_fail.pk: return False
            return True
        mock_process_func.side_effect = side_effect_func

        payments_list_for_action = [
            self.payment1_new,
            self.payment2_processed,
            self.payment3_new_fail
        ]

        self.assertFalse(self.payment1_new.processed_for_access)
        self.assertTrue(self.payment2_processed.processed_for_access)
        self.assertFalse(self.payment3_new_fail.processed_for_access)

        self.payment_admin.process_selected_payments_action(self.request, payments_list_for_action)

        self.assertEqual(mock_process_func.call_count, 2)
        mock_process_func.assert_any_call(self.payment1_new)
        mock_process_func.assert_any_call(self.payment3_new_fail)

        admin_messages = [m.message for m in list(self.request._messages)]
        self.assertIn("1 pago(s) procesado(s) exitosamente.", admin_messages) # Corrected message
        self.assertIn("1 pago(s) ya habían sido procesados.", admin_messages) # Corrected message
        self.assertIn("1 pago(s) no pudieron ser procesados.", admin_messages) # Corrected message

    @patch('log_viewer_app.admin.process_payment_for_access')
    def test_process_single_unprocessed_payment(self, mock_process_func):
        mock_process_func.return_value = True

        payment_to_process = self.payment1_new
        self.assertFalse(payment_to_process.processed_for_access)

        single_payment_list = [payment_to_process]

        self.payment_admin.process_selected_payments_action(self.request, single_payment_list)

        mock_process_func.assert_called_once_with(payment_to_process)
        admin_messages = [m.message for m in list(self.request._messages)]
        self.assertIn("1 pago(s) procesado(s) exitosamente.", admin_messages) # Corrected message
        self.assertEqual(len(admin_messages), 1)

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
        self.assertEqual(response.data['person_name'], self.person_allowed.full_name)
        self.assertEqual(response.data['access_point_name'], self.ap_main.name)

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
        self.assertIsNone(response.data['person_name'])


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


class UserPermissionsListAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(username='user1perm', password='password1')
        self.person1 = Person.objects.create(full_name="User One Perms", identifier="U1P", user=self.user1)
        self.token1 = Token.objects.create(user=self.user1)
        self.ap1 = AccessPoint.objects.create(name="AP Test 1")
        self.ap2 = AccessPoint.objects.create(name="AP Test 2")
        AccessPermission.objects.create(person=self.person1, access_point=self.ap1, is_active=True)
        AccessPermission.objects.create(person=self.person1, access_point=self.ap2, is_active=False)

        self.user2 = User.objects.create_user(username='user2noperm', password='password2')
        self.person2 = Person.objects.create(full_name="User Two No Perms", identifier="U2NP", user=self.user2)
        self.token2 = Token.objects.create(user=self.user2)

        self.user3_no_profile = User.objects.create_user(username='user3noprofile', password='password3')
        self.token3 = Token.objects.create(user=self.user3_no_profile)

        self.url = reverse('log_viewer_app:api_user_permissions')

    def test_list_permissions_unauthenticated(self):
        unauth_client = APIClient()
        response = unauth_client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_permissions_user_with_permissions(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertContains(response, self.person1.full_name)
        self.assertContains(response, self.ap1.name)


    def test_list_permissions_user_no_permissions(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_list_permissions_user_no_person_profile(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token3.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)
