from django.test import TestCase, Client
from django.urls import reverse
from .models import (
    AccessLog, Person, Vehicle, AccessPoint, AccessPermission,
    ControlDevice, Payment, Service, UserSubscription, Invoice
)
from .forms import (
    PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm,
    GuestRegistrationForm, PersonProfileEditForm # Added PersonProfileEditForm
)
from .utils import verify_access_with_models, publish_mqtt_message, process_payment_for_access
from .billing_utils import generate_invoice_for_subscription, generate_all_due_invoices, get_due_cycle_start_date_for_subscription # Import the new function
from django.utils import timezone
from datetime import timedelta, date as dt_date, datetime as dt_datetime, date
from decimal import Decimal
from unittest.mock import patch, MagicMock, call as mock_call
from django.conf import settings
from django.contrib import admin, messages # Import messages
from django.contrib.auth.models import User, Group
from django.contrib.messages.storage.fallback import FallbackStorage
from .admin import PaymentAdmin, UserSubscriptionAdmin # Import UserSubscriptionAdmin
from django.contrib.admin.sites import AdminSite # Import AdminSite
from django.test.client import RequestFactory # Import RequestFactory


# DRF Test specific imports
from rest_framework.test import APIClient
from rest_framework.authtoken.models import Token
from rest_framework import status
from .serializers import AccessRequestSerializer, AccessResponseSerializer, AccessPermissionSerializer

# For management command testing
from io import StringIO
from django.core.management import call_command


# --- Model Tests ---
from django.db import IntegrityError # Required for uniqueness tests
from .models import Tenant, get_default_tenant_pk # Import Tenant and helper

class TenantModelTest(TestCase):
    def test_tenant_creation(self):
        """Test basic creation of a Tenant instance."""
        tenant = Tenant.objects.create(name="Test Corp", subdomain_prefix="testcorp")
        self.assertIsNotNone(tenant.pk)
        self.assertEqual(tenant.name, "Test Corp")
        self.assertEqual(tenant.subdomain_prefix, "testcorp")
        self.assertIsNotNone(tenant.created_at)
        self.assertIsNotNone(tenant.updated_at)
        self.assertEqual(str(tenant), "Test Corp")

    def test_tenant_name_unique(self):
        """Test that Tenant names are unique."""
        Tenant.objects.create(name="Unique Corp", subdomain_prefix="unique1")
        with self.assertRaises(IntegrityError):
            Tenant.objects.create(name="Unique Corp", subdomain_prefix="unique2")

    def test_tenant_subdomain_prefix_unique_for_non_null_values(self):
        """Test that non-null subdomain_prefix values are unique."""
        Tenant.objects.create(name="Subdomain Corp Alpha", subdomain_prefix="sub_alpha")
        with self.assertRaises(IntegrityError):
            Tenant.objects.create(name="Subdomain Corp Beta", subdomain_prefix="sub_alpha")

    def test_tenant_subdomain_prefix_allows_multiple_nulls(self):
        """Test that multiple tenants can have a subdomain_prefix of None."""
        # Ensure a clean slate for this specific test regarding NULL subdomains.
        Tenant.objects.filter(subdomain_prefix=None).delete()

        # Create the first tenant with subdomain_prefix=None.
        tenant_null_1 = Tenant.objects.create(name="Null Subdomain Corp Charlie", subdomain_prefix=None)
        self.assertIsNotNone(tenant_null_1.pk)
        self.assertEqual(Tenant.objects.filter(subdomain_prefix=None).count(), 1)

        # Create a second tenant with subdomain_prefix=None.
        # This is allowed by Django's model validation and most database backends (including SQLite apparently).
        tenant_null_2 = Tenant.objects.create(name="Null Subdomain Corp Delta", subdomain_prefix=None)
        self.assertIsNotNone(tenant_null_2.pk)

        # Ensure the count of tenants with subdomain_prefix=None is now 2.
        self.assertEqual(Tenant.objects.filter(subdomain_prefix=None).count(), 2)

class PersonModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="Person Test Tenant 1", subdomain_prefix="pmt1")
        cls.tenant2 = Tenant.objects.create(name="Person Test Tenant 2", subdomain_prefix="pmt2")
        cls.default_tenant = Tenant.objects.get(pk=get_default_tenant_pk()) # Default tenant

        cls.user_generic = User.objects.create_user(username='pm_user_generic', password='password')


    def test_person_creation(self):
        user_host = User.objects.create_user(username='pm_hostuser', password='password')
        # Explicitly assign tenant1 for clarity in this test
        host_person = Person.objects.create(tenant=self.tenant1, user=user_host, full_name="Host Person", identifier="HOST_PM_T1")
        person = Person.objects.create(tenant=self.tenant1, full_name="John Doe", identifier="JD001_PM_T1", is_temporary_guest=True, registered_by=host_person)
        self.assertIsInstance(person, Person)
        self.assertEqual(str(person), "John Doe (JD001_PM_T1) (Invitado Temp.)")
        self.assertEqual(person.tenant, self.tenant1)

    def test_person_str_not_guest(self):
        # Uses default tenant implicitly due to model default
        person = Person.objects.create(full_name="Regular Person", identifier="REG01_PM_DEF")
        self.assertEqual(str(person), "Regular Person (REG01_PM_DEF)")
        self.assertEqual(person.tenant, self.default_tenant)

    def test_person_creation_assigns_default_tenant(self):
        """Test that a Person gets the default tenant if none is specified."""
        user_for_person = User.objects.create_user(username='dtu_user_pm', password='password')
        person_no_tenant_specified = Person.objects.create(
            full_name="Default Tenant User PM",
            identifier="DTU01_PM",
            user=user_for_person
        )
        self.assertIsNotNone(person_no_tenant_specified.tenant)
        self.assertEqual(person_no_tenant_specified.tenant, self.default_tenant)

    def test_identifier_unique_within_tenant(self):
        """Test that 'identifier' is unique within the same tenant."""
        Person.objects.create(tenant=self.tenant1, full_name="Person A", identifier="ID_PM_001", user=self.user_generic)
        with self.assertRaises(IntegrityError):
            Person.objects.create(tenant=self.tenant1, full_name="Person B", identifier="ID_PM_001") # Same identifier, same tenant

    def test_identifier_can_be_same_across_tenants(self):
        """Test that 'identifier' can be the same across different tenants."""
        user_t2 = User.objects.create_user(username='pm_user_t2', password='password')
        Person.objects.create(tenant=self.tenant1, full_name="Person C", identifier="ID_PM_002", user=self.user_generic)
        try:
            Person.objects.create(tenant=self.tenant2, full_name="Person D", identifier="ID_PM_002", user=user_t2) # Same identifier, different tenant
        except IntegrityError:
            self.fail("IntegrityError raised unexpectedly for same identifier across different tenants.")


class VehicleModelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="Vehicle Test Tenant 1", subdomain_prefix="vmt1")
        cls.tenant2 = Tenant.objects.create(name="Vehicle Test Tenant 2", subdomain_prefix="vmt2")
        cls.default_tenant = Tenant.objects.get(pk=get_default_tenant_pk())

        cls.owner_t1_user = User.objects.create_user(username='owner_t1_user_vm', password='password')
        cls.owner_t1 = Person.objects.create(tenant=cls.tenant1, full_name="Owner T1 VM", identifier="OWNER_T1_VM", user=cls.owner_t1_user)

        cls.owner_t2_user = User.objects.create_user(username='owner_t2_user_vm', password='password')
        cls.owner_t2 = Person.objects.create(tenant=cls.tenant2, full_name="Owner T2 VM", identifier="OWNER_T2_VM", user=cls.owner_t2_user)

        cls.owner_default_tenant_user = User.objects.create_user(username='owner_def_user_vm', password='password')
        cls.owner_default_tenant = Person.objects.create(tenant=cls.default_tenant, full_name="Owner Default VM", identifier="OWNER_DEF_VM", user=cls.owner_default_tenant_user)


    def test_vehicle_creation(self):
        # Test creation with explicit tenant
        vehicle = Vehicle.objects.create(tenant=self.tenant1, owner=self.owner_t1, license_plate="XYZ123_VM_T1", description="Red Car T1")
        self.assertIsInstance(vehicle, Vehicle)
        self.assertEqual(str(vehicle), "XYZ123_VM_T1 (Owner T1 VM)")
        self.assertEqual(vehicle.tenant, self.tenant1)

    def test_vehicle_creation_assigns_default_tenant(self):
        """Test that a Vehicle gets the default tenant if none is specified."""
        vehicle_no_tenant = Vehicle.objects.create(owner=self.owner_default_tenant, license_plate="DEF_LP_VM", description="Default Tenant Car")
        self.assertIsNotNone(vehicle_no_tenant.tenant)
        self.assertEqual(vehicle_no_tenant.tenant, self.default_tenant)

    def test_license_plate_unique_within_tenant(self):
        """Test that 'license_plate' is unique within the same tenant."""
        Vehicle.objects.create(tenant=self.tenant1, owner=self.owner_t1, license_plate="LP_VM_001")
        with self.assertRaises(IntegrityError):
            Vehicle.objects.create(tenant=self.tenant1, owner=self.owner_t1, license_plate="LP_VM_001")

    def test_license_plate_can_be_same_across_tenants(self):
        """Test that 'license_plate' can be the same across different tenants."""
        Vehicle.objects.create(tenant=self.tenant1, owner=self.owner_t1, license_plate="LP_VM_002")
        try:
            Vehicle.objects.create(tenant=self.tenant2, owner=self.owner_t2, license_plate="LP_VM_002")
        except IntegrityError:
            self.fail("IntegrityError raised unexpectedly for same license_plate across different tenants.")


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
        cls.tenant1 = Tenant.objects.create(name="PLV Tenant 1", subdomain_prefix="plvt1")
        cls.tenant2 = Tenant.objects.create(name="PLV Tenant 2", subdomain_prefix="plvt2")

        cls.user_t1 = User.objects.create_user(username='user_t1_plv', password='password')
        cls.person_t1_user_profile = Person.objects.create(user=cls.user_t1, full_name="User T1 PLV", identifier="USER_T1_PLV_ID", tenant=cls.tenant1)

        cls.person1_t1 = Person.objects.create(tenant=cls.tenant1, full_name="Person 1 T1 PLV", identifier="P1_T1_PLV")
        cls.person2_t1 = Person.objects.create(tenant=cls.tenant1, full_name="Person 2 T1 PLV", identifier="P2_T1_PLV")

        cls.user_t2 = User.objects.create_user(username='user_t2_plv', password='password')
        cls.person_t2_user_profile = Person.objects.create(user=cls.user_t2, full_name="User T2 PLV", identifier="USER_T2_PLV_ID", tenant=cls.tenant2)
        cls.person1_t2 = Person.objects.create(tenant=cls.tenant2, full_name="Person 1 T2 PLV", identifier="P1_T2_PLV")

        cls.user_no_profile = User.objects.create_user(username='user_no_profile_plv', password='password')
        cls.list_url = reverse('log_viewer_app:person_list')
        cls.login_url = '/accounts/login/' # Hardcoded to avoid NoReverseMatch in setUpTestData

    def test_person_list_view_login_required(self):
        response = self.client.get(self.list_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.list_url}')

    def test_person_list_displays_tenant1_specific_data(self):
        self.client.login(username='user_t1_plv', password='password')
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/person_list.html')
        self.assertEqual(response.context['active_tenant'], self.tenant1)
        self.assertContains(response, self.person1_t1.full_name)
        self.assertContains(response, self.person2_t1.full_name)
        self.assertContains(response, self.person_t1_user_profile.full_name) # User's own profile
        self.assertNotContains(response, self.person1_t2.full_name) # Should not see Tenant 2 data

    def test_person_list_displays_tenant2_specific_data(self):
        self.client.login(username='user_t2_plv', password='password')
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tenant'], self.tenant2)
        self.assertContains(response, self.person1_t2.full_name)
        self.assertContains(response, self.person_t2_user_profile.full_name)
        self.assertNotContains(response, self.person1_t1.full_name) # Should not see Tenant 1 data

    def test_person_list_view_user_no_profile_redirects(self):
        self.client.login(username='user_no_profile_plv', password='password')
        response = self.client.get(self.list_url)
        self.assertRedirects(response, reverse('log_viewer_app:user_dashboard')) # As per view logic

class PersonCreateViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="PCV Tenant 1", subdomain_prefix="pcvt1")
        cls.user_t1 = User.objects.create_user(username='user_t1_pcv', password='password')
        cls.person_host_t1 = Person.objects.create(user=cls.user_t1, full_name="User T1 PCV", identifier="USER_T1_PCV_ID", tenant=cls.tenant1)

        cls.user_no_profile_pcv = User.objects.create_user(username='user_no_profile_pcv', password='password')

        cls.create_url = reverse('log_viewer_app:person_create')
        cls.list_url = reverse('log_viewer_app:person_list')
        cls.login_url = '/accounts/login/' # Hardcoded

    def test_person_create_view_login_required_get(self):
        response = self.client.get(self.create_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.create_url}')

    def test_person_create_view_get_shows_form_for_authorized_user(self):
        self.client.login(username='user_t1_pcv', password='password')
        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/person_form.html')
        self.assertIsInstance(response.context['form'], PersonForm)
        self.assertEqual(response.context['active_tenant'], self.tenant1)

    def test_person_create_view_post_assigns_correct_tenant(self):
        self.client.login(username='user_t1_pcv', password='password')
        person_data = {'full_name': 'New Person PCV', 'identifier': 'NEW_PCV_ID'}
        response = self.client.post(self.create_url, person_data)
        self.assertRedirects(response, self.list_url)
        created_person = Person.objects.get(identifier='NEW_PCV_ID')
        self.assertEqual(created_person.tenant, self.tenant1)

    def test_person_create_view_post_invalid_data(self):
        self.client.login(username='user_t1_pcv', password='password')
        person_data = {'full_name': '', 'identifier': 'INVALID_PCV_ID'} # Invalid: full_name is required
        response = self.client.post(self.create_url, person_data)
        self.assertEqual(response.status_code, 200) # Should re-render form
        self.assertFormError(response.context['form'], 'full_name', 'This field is required.')

    def test_person_create_view_user_no_profile_redirects(self):
        self.client.login(username='user_no_profile_pcv', password='password')
        response = self.client.get(self.create_url)
        self.assertRedirects(response, reverse('log_viewer_app:user_dashboard'))

        response_post = self.client.post(self.create_url, {'full_name': 'Fail Person', 'identifier': 'FAIL_ID'})
        self.assertRedirects(response_post, reverse('log_viewer_app:user_dashboard'))


class VehicleListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="VLV Tenant 1", subdomain_prefix="vlvt1")
        cls.tenant2 = Tenant.objects.create(name="VLV Tenant 2", subdomain_prefix="vlvt2")

        cls.user_t1_vlv = User.objects.create_user(username='user_t1_vlv', password='password')
        cls.owner_t1_vlv = Person.objects.create(user=cls.user_t1_vlv, full_name="Owner T1 VLV", identifier="OWNER_T1_VLV_ID", tenant=cls.tenant1)
        Vehicle.objects.create(tenant=cls.tenant1, owner=cls.owner_t1_vlv, license_plate="CAR1_T1_VLV")
        Vehicle.objects.create(tenant=cls.tenant1, owner=cls.owner_t1_vlv, license_plate="CAR2_T1_VLV")

        cls.user_t2_vlv = User.objects.create_user(username='user_t2_vlv', password='password')
        cls.owner_t2_vlv = Person.objects.create(user=cls.user_t2_vlv, full_name="Owner T2 VLV", identifier="OWNER_T2_VLV_ID", tenant=cls.tenant2)
        Vehicle.objects.create(tenant=cls.tenant2, owner=cls.owner_t2_vlv, license_plate="CAR1_T2_VLV")

        cls.list_url = reverse('log_viewer_app:vehicle_list')
        cls.login_url = '/accounts/login/' # Hardcoded

    def test_vehicle_list_login_required(self):
        response = self.client.get(self.list_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.list_url}')

    def test_vehicle_list_displays_tenant1_specific_data(self):
        self.client.login(username='user_t1_vlv', password='password')
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/vehicle_list.html')
        self.assertEqual(response.context['active_tenant'], self.tenant1)
        self.assertContains(response, "CAR1_T1_VLV")
        self.assertContains(response, "CAR2_T1_VLV")
        self.assertNotContains(response, "CAR1_T2_VLV")

    def test_vehicle_list_displays_tenant2_specific_data(self):
        self.client.login(username='user_t2_vlv', password='password')
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tenant'], self.tenant2)
        self.assertContains(response, "CAR1_T2_VLV")
        self.assertNotContains(response, "CAR1_T1_VLV")

class VehicleCreateViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="VCV Tenant 1", subdomain_prefix="vcvt1")
        cls.user_t1_vcv = User.objects.create_user(username='user_t1_vcv', password='password')
        cls.owner_person_t1_vcv = Person.objects.create(user=cls.user_t1_vcv, full_name="Owner T1 VCV", identifier="OWNER_T1_VCV_ID", tenant=cls.tenant1)

        cls.create_url = reverse('log_viewer_app:vehicle_create')
        cls.list_url = reverse('log_viewer_app:vehicle_list')
        cls.login_url = '/accounts/login/' # Hardcoded

    def test_vehicle_create_view_login_required_get(self):
        response = self.client.get(self.create_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.create_url}')

    def test_vehicle_create_view_get_shows_form_for_authorized_user(self):
        self.client.login(username='user_t1_vcv', password='password')
        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/vehicle_form.html')
        self.assertIsInstance(response.context['form'], VehicleForm)
        self.assertEqual(response.context['active_tenant'], self.tenant1)
        # Check if owner dropdown is filtered (advanced, requires form modification not in this subtask)
        # For now, we just check the view loads and context is right.

    def test_vehicle_create_view_post_assigns_correct_tenant(self):
        self.client.login(username='user_t1_vcv', password='password')
        vehicle_data = {'owner': self.owner_person_t1_vcv.pk, 'license_plate': 'NEWCAR_VCV', 'description': 'Test Car VCV'}
        response = self.client.post(self.create_url, vehicle_data)
        self.assertRedirects(response, self.list_url)
        created_vehicle = Vehicle.objects.get(license_plate='NEWCAR_VCV')
        self.assertEqual(created_vehicle.tenant, self.tenant1)
        self.assertEqual(created_vehicle.owner, self.owner_person_t1_vcv)

    def test_vehicle_create_view_post_invalid_data(self):
        self.client.login(username='user_t1_vcv', password='password')
        vehicle_data = {'owner': self.owner_person_t1_vcv.pk, 'license_plate': ''} # Invalid: license_plate required
        response = self.client.post(self.create_url, vehicle_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'license_plate', 'This field is required.')

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
        cls.tenant1 = Tenant.objects.create(name="VAL Tenant 1", subdomain_prefix="val1")
        cls.tenant2 = Tenant.objects.create(name="VAL Tenant 2", subdomain_prefix="val2")

        # Tenant 1 data
        cls.person_t1_allow = Person.objects.create(tenant=cls.tenant1, full_name="Allowed User T1", identifier="ALLOW_T1_ID")
        cls.person_t1_noperm = Person.objects.create(tenant=cls.tenant1, full_name="NoPerm User T1", identifier="NOPERM_T1_ID")
        cls.person_t1_inactive = Person.objects.create(tenant=cls.tenant1, full_name="InactivePerm User T1", identifier="INACTIVE_T1_ID")
        cls.person_t1_future = Person.objects.create(tenant=cls.tenant1, full_name="FuturePerm User T1", identifier="FUTURE_T1_ID")
        cls.person_t1_expired = Person.objects.create(tenant=cls.tenant1, full_name="ExpiredPerm User T1", identifier="EXPIRED_T1_ID")
        cls.person_t1_timevalid = Person.objects.create(tenant=cls.tenant1, full_name="TimeValid User T1", identifier="TIMEVALID_T1_ID")

        cls.ap_t1_main = AccessPoint.objects.create(tenant=cls.tenant1, name="MainDoorT1")
        cls.ap_t1_mqtt = AccessPoint.objects.create(tenant=cls.tenant1, name="MQTTDoorT1")

        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_t1_allow, access_point=cls.ap_t1_main, is_active=True)
        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_t1_inactive, access_point=cls.ap_t1_main, is_active=False)
        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_t1_future, access_point=cls.ap_t1_main, is_active=True, valid_from=timezone.now() + timedelta(days=1))
        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_t1_expired, access_point=cls.ap_t1_main, is_active=True, valid_until=timezone.now() - timedelta(days=1))
        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_t1_timevalid, access_point=cls.ap_t1_main, is_active=True, valid_from=timezone.now() - timedelta(hours=1), valid_until=timezone.now() + timedelta(hours=1))

        cls.device_t1_ap_mqtt = ControlDevice.objects.create(tenant=cls.tenant1, name="MQTT_Door_Ctrl_T1", device_id="CTRL_MQTT_T1", access_point=cls.ap_t1_mqtt, mqtt_topic="tenant1/door/open", is_active=True)
        cls.person_t1_mqtt = Person.objects.create(tenant=cls.tenant1, full_name="MQTT Access User T1", identifier="MQTT_ACCESS_T1_ID")
        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_t1_mqtt, access_point=cls.ap_t1_mqtt, is_active=True)

        # Tenant 2 data
        cls.person_t2_allow = Person.objects.create(tenant=cls.tenant2, full_name="Allowed User T2", identifier="ALLOW_T2_ID")
        cls.ap_t2_main = AccessPoint.objects.create(tenant=cls.tenant2, name="MainDoorT2")
        AccessPermission.objects.create(tenant=cls.tenant2, person=cls.person_t2_allow, access_point=cls.ap_t2_main, is_active=True)
        cls.device_t2_ap_main = ControlDevice.objects.create(tenant=cls.tenant2, name="Main_Door_Ctrl_T2", device_id="CTRL_MAIN_T2", access_point=cls.ap_t2_main, mqtt_topic="tenant2/door/open", is_active=True)


    def tearDown(self):
        AccessLog.objects.all().delete() # Keep if specific log checks are needed, otherwise default test rollback is fine.

    def test_access_allowed(self):
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="ALLOW_T1_ID", access_point_name="MainDoorT1"))

    def test_person_not_found(self):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="UNKNOWN_T1_ID", access_point_name="MainDoorT1"))

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_triggers_mqtt_publish_single_device(self, mock_publish):
        mock_publish.return_value=True
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="MQTT_ACCESS_T1_ID", access_point_name="MQTTDoorT1"))
        mock_publish.assert_called_once_with(topic=self.device_t1_ap_mqtt.mqtt_topic, payload="OPEN")

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_no_active_devices(self, mock_publish):
        self.device_t1_ap_mqtt.is_active = False; self.device_t1_ap_mqtt.save()
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="MQTT_ACCESS_T1_ID", access_point_name="MQTTDoorT1"))
        mock_publish.assert_not_called()
        self.device_t1_ap_mqtt.is_active = True; self.device_t1_ap_mqtt.save() # Reset state

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_denied_no_mqtt_publish(self, mock_publish):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="NOPERM_T1_ID", access_point_name="MQTTDoorT1"))
        mock_publish.assert_not_called()

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_multiple_active_devices_mqtt_publish(self, mock_publish):
        mock_publish.return_value=True
        dev_extra = ControlDevice.objects.create(tenant=self.tenant1, name="ExtraDevT1", device_id="EXTRA_T1_01", access_point=self.ap_t1_mqtt, mqtt_topic="tenant1/extra/topic", is_active=True)
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="MQTT_ACCESS_T1_ID", access_point_name="MQTTDoorT1"))
        self.assertEqual(mock_publish.call_count, 2)
        topics = [c.kwargs['topic'] for c in mock_publish.call_args_list]
        self.assertCountEqual(topics, [self.device_t1_ap_mqtt.mqtt_topic, dev_extra.mqtt_topic])
        dev_extra.delete()

    def test_access_point_not_found(self):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="ALLOW_T1_ID", access_point_name="NonExistentDoorT1"))

    def test_permission_not_found(self):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="NOPERM_T1_ID", access_point_name="MainDoorT1"))

    def test_permission_inactive(self):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="INACTIVE_T1_ID", access_point_name="MainDoorT1"))

    def test_permission_future_valid_from(self):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="FUTURE_T1_ID", access_point_name="MainDoorT1"))

    def test_permission_expired_valid_until(self):
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="EXPIRED_T1_ID", access_point_name="MainDoorT1"))

    def test_permission_time_valid(self):
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="TIMEVALID_T1_ID", access_point_name="MainDoorT1"))

    def test_permission_valid_from_only_no_end(self):
        p, _ = Person.objects.get_or_create(tenant=self.tenant1, identifier="NOEND_T1_ID", defaults={'full_name':"PermNoEnd User T1"})
        AccessPermission.objects.get_or_create(tenant=self.tenant1, person=p,access_point=self.ap_t1_main,defaults={'is_active':True,'valid_from':timezone.now()-timedelta(days=1),'valid_until':None})
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="NOEND_T1_ID", access_point_name="MainDoorT1"))

    def test_permission_default_valid_from_no_end(self):
        p, _ = Person.objects.get_or_create(tenant=self.tenant1, identifier="DEFAULTSTART_T1_ID", defaults={'full_name':"PermDefaultStart User T1"})
        AccessPermission.objects.get_or_create(tenant=self.tenant1, person=p,access_point=self.ap_t1_main,defaults={'is_active':True,'valid_until':None}) # valid_from defaults to now()
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier="DEFAULTSTART_T1_ID", access_point_name="MainDoorT1"))

    # Tenant Isolation Tests
    def test_access_denied_person_from_different_tenant(self):
        """Person from T1, AP from T1, but verification queried against T2."""
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant2, qr_identifier=self.person_t1_allow.identifier, access_point_name=self.ap_t1_main.name))

    def test_access_denied_ap_from_different_tenant(self):
        """Person from T1, AP from T2, verification queried against T1."""
        self.assertFalse(verify_access_with_models(active_tenant=self.tenant1, qr_identifier=self.person_t1_allow.identifier, access_point_name=self.ap_t2_main.name))

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_mqtt_publish_device_tenant_mismatch(self, mock_publish):
        """Access granted in tenant1, but control device is (incorrectly) in tenant2. MQTT should not publish."""
        # This setup is a bit artificial as data integrity should prevent this.
        # We'll simulate it by trying to use person_t1_allow (T1) at ap_t1_main (T1)
        # but imagine the device for ap_t1_main was wrongly assigned to tenant2.
        # The current verify_access_with_models filters ControlDevice by active_tenant, so this is implicitly tested.
        # To make it more explicit:
        # Grant permission for person_t1_allow at ap_t1_main (done in setup).
        # Ensure device_t1_ap_mqtt is for ap_t1_mqtt (also T1).
        # If we call verify_access_with_models with tenant1, it should find device_t1_ap_mqtt.
        # If we were to change device_t1_ap_mqtt.tenant to tenant2, it should NOT be found.

        original_device_tenant = self.device_t1_ap_mqtt.tenant
        self.device_t1_ap_mqtt.tenant = self.tenant2
        self.device_t1_ap_mqtt.save()

        # Try to access using tenant1. Person, AP, Permission are in tenant1.
        # But the device is now in tenant2. The filter should exclude it.
        self.assertTrue(verify_access_with_models(active_tenant=self.tenant1, qr_identifier=self.person_t1_mqtt.identifier, access_point_name=self.ap_t1_mqtt.name))
        mock_publish.assert_not_called() # Device is in wrong tenant, so it shouldn't be found/used.

        self.device_t1_ap_mqtt.tenant = original_device_tenant # Revert
        self.device_t1_ap_mqtt.save()


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
        admin_messages = [m.message for m in list(self.request._messages)]; self.assertIn("1 pago(s) procesado(s) exitosamente.", admin_messages); self.assertIn("1 pago(s) ya habían sido procesados.", admin_messages); self.assertIn("1 pago(s) no pudieron ser procesados (p.ej., persona no asignada al pago, o error al intentar actualizar/crear permisos). Revise los logs para detalles.", admin_messages)

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
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="API Tenant 1", subdomain_prefix="api1")
        cls.tenant2 = Tenant.objects.create(name="API Tenant 2", subdomain_prefix="api2")

        # API User for Tenant 1
        cls.api_user_t1 = User.objects.create_user(username='apiuser_t1', password='passwordt1')
        cls.person_api_t1 = Person.objects.create(user=cls.api_user_t1, full_name="API User T1", identifier="API_USER_T1_ID", tenant=cls.tenant1)
        cls.token_t1 = Token.objects.create(user=cls.api_user_t1)

        # API User for Tenant 2
        cls.api_user_t2 = User.objects.create_user(username='apiuser_t2', password='passwordt2')
        cls.person_api_t2 = Person.objects.create(user=cls.api_user_t2, full_name="API User T2", identifier="API_USER_T2_ID", tenant=cls.tenant2)
        cls.token_t2 = Token.objects.create(user=cls.api_user_t2)

        # API User with no person profile
        cls.api_user_no_profile = User.objects.create_user(username='api_no_profile', password='password_np')
        cls.token_no_profile = Token.objects.create(user=cls.api_user_no_profile)

        # Data for Tenant 1
        cls.person_qr_t1 = Person.objects.create(tenant=cls.tenant1, full_name="QR Person T1", identifier="QR_T1_ID")
        cls.ap_t1 = AccessPoint.objects.create(tenant=cls.tenant1, name="AP_T1_MainGate")
        AccessPermission.objects.create(tenant=cls.tenant1, person=cls.person_qr_t1, access_point=cls.ap_t1, is_active=True)

        # Data for Tenant 2 (Access Point)
        cls.ap_t2 = AccessPoint.objects.create(tenant=cls.tenant2, name="AP_T2_SideGate")

        cls.url = reverse('log_viewer_app:api_verify_access')

    def setUp(self):
        self.client = APIClient()

    def test_verify_access_unauthenticated(self):
        # No token provided
        response = self.client.post(self.url, {'qr_identifier': self.person_qr_t1.identifier, 'access_point_name': self.ap_t1.name}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify_access_authenticated_granted_t1(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_t1.key)
        data = {'qr_identifier': self.person_qr_t1.identifier, 'access_point_name': self.ap_t1.name}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['access_granted'])
        self.assertIn(self.tenant1.name, response.data['message'])

    def test_verify_access_authenticated_denied_no_permission_t1(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_t1.key)
        # Person from T1, AP from T1, but no permission record
        person_no_perm_t1 = Person.objects.create(tenant=self.tenant1, full_name="No Perm T1", identifier="QR_T1_NOPERM")
        data = {'qr_identifier': person_no_perm_t1.identifier, 'access_point_name': self.ap_t1.name}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK) # View still returns 200 for denied access
        self.assertFalse(response.data['access_granted'])
        self.assertIn(self.tenant1.name, response.data['message'])

    def test_verify_access_authenticated_denied_person_not_found_in_tenant_t1(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_t1.key)
        data = {'qr_identifier': 'QR_NON_EXISTENT_T1', 'access_point_name': self.ap_t1.name}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['access_granted'])
        self.assertIn(self.tenant1.name, response.data['message'])

    def test_verify_access_user_from_wrong_tenant(self):
        """API User from T1 tries to verify QR for person in T1 at an AP that is in T2."""
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_t1.key)
        data = {'qr_identifier': self.person_qr_t1.identifier, 'access_point_name': self.ap_t2.name} # ap_t2 is in Tenant 2
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK) # verify_access_models will deny due to AP not found in tenant1
        self.assertFalse(response.data['access_granted'])
        self.assertIn(self.tenant1.name, response.data['message']) # Message should reflect tenant1 context

    def test_verify_access_user_no_person_profile(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_no_profile.key)
        data = {'qr_identifier': self.person_qr_t1.identifier, 'access_point_name': self.ap_t1.name}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("El usuario API no tiene un perfil de persona asociado", response.data['message'])

    def test_verify_access_invalid_request_data_missing_qr(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_t1.key)
        data = {'access_point_name': self.ap_t1.name}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('qr_identifier', response.data)

    def test_verify_access_invalid_request_data_missing_ap(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_t1.key)
        data = {'qr_identifier': self.person_qr_t1.identifier}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('access_point_name', response.data)

class UserDashboardViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create Tenants
        cls.tenant1 = Tenant.objects.create(name="Tenant Alpha", subdomain_prefix="alpha")
        cls.tenant2 = Tenant.objects.create(name="Tenant Bravo", subdomain_prefix="bravo")

        # User 1 and their data (Tenant 1)
        cls.user1 = User.objects.create_user(username='user1_t1', password='password_t1')
        cls.person1 = Person.objects.create(user=cls.user1, full_name="User One Tenant1", identifier="U1T1_ID", tenant=cls.tenant1)

        cls.ap1_t1 = AccessPoint.objects.create(name="AP1 Tenant1", tenant=cls.tenant1)
        cls.ap2_t1 = AccessPoint.objects.create(name="AP2 Tenant1", tenant=cls.tenant1) # Expired/Inactive
        cls.perm1_t1_active = AccessPermission.objects.create(person=cls.person1, access_point=cls.ap1_t1, is_active=True, valid_from=timezone.now(), valid_until=timezone.now() + timedelta(days=5), tenant=cls.tenant1)
        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap2_t1, is_active=False, tenant=cls.tenant1) # Inactive perm

        cls.vehicle1_t1 = Vehicle.objects.create(owner=cls.person1, license_plate="CAR1T1", description="Car User1 T1", tenant=cls.tenant1)

        cls.service1_t1 = Service.objects.create(name="Service T1", price=Decimal("10.00"), tenant=cls.tenant1)
        cls.sub1_t1 = UserSubscription.objects.create(person=cls.person1, service=cls.service1_t1, start_date=timezone.now().date() - timedelta(days=10), is_active=True, tenant=cls.tenant1)

        cls.invoice1_t1_pending = Invoice.objects.create(person=cls.person1, user_subscription=cls.sub1_t1, invoice_number="INV001T1", amount_due=Decimal("10.00"), due_date=timezone.now().date() + timedelta(days=5), status='pending', tenant=cls.tenant1)
        cls.invoice2_t1_overdue = Invoice.objects.create(person=cls.person1, invoice_number="INV002T1", amount_due=Decimal("15.00"), due_date=timezone.now().date() - timedelta(days=1), status='overdue', tenant=cls.tenant1)
        cls.invoice3_t1_paid = Invoice.objects.create(person=cls.person1, invoice_number="INV003T1", amount_due=Decimal("5.00"), status='paid', due_date=timezone.now().date() - timedelta(days=1), tenant=cls.tenant1)
        cls.expected_total_due_tenant1 = cls.invoice1_t1_pending.amount_due + cls.invoice2_t1_overdue.amount_due

        # User 2 and their data (Tenant 2)
        cls.user2 = User.objects.create_user(username='user2_t2', password='password_t2')
        cls.person2 = Person.objects.create(user=cls.user2, full_name="User Two Tenant2", identifier="U2T2_ID", tenant=cls.tenant2)

        cls.ap1_t2 = AccessPoint.objects.create(name="AP1 Tenant2", tenant=cls.tenant2)
        cls.perm1_t2_active = AccessPermission.objects.create(person=cls.person2, access_point=cls.ap1_t2, is_active=True, tenant=cls.tenant2)

        cls.vehicle1_t2 = Vehicle.objects.create(owner=cls.person2, license_plate="CAR1T2", description="Car User2 T2", tenant=cls.tenant2)

        cls.service1_t2 = Service.objects.create(name="Service T2", price=Decimal("20.00"), tenant=cls.tenant2)
        cls.sub1_t2 = UserSubscription.objects.create(person=cls.person2, service=cls.service1_t2, is_active=True, tenant=cls.tenant2)

        cls.invoice1_t2_pending = Invoice.objects.create(person=cls.person2, user_subscription=cls.sub1_t2, invoice_number="INV001T2", amount_due=Decimal("20.00"), status='pending', due_date=timezone.now().date() + timedelta(days=5), tenant=cls.tenant2)
        cls.expected_total_due_tenant2 = cls.invoice1_t2_pending.amount_due

        # Other users for specific tests
        cls.user_no_profile = User.objects.create_user(username='nouserprofile_dash', password='password')

        cls.user_with_profile_no_data = User.objects.create_user(username='emptydashuser_dash', password='password')
        # This person is in tenant1 but will have no specific data items created for them directly in tests.
        cls.person_with_profile_no_data = Person.objects.create(user=cls.user_with_profile_no_data, full_name="Empty Dash User T1", identifier="EMPTY_DASH_ID_T1", tenant=cls.tenant1)

        cls.dashboard_url = reverse('log_viewer_app:user_dashboard')
        # LOGIN_URL is hardcoded to '/accounts/login/' in PersonProfileEditViewTest's setUp, use that for consistency if needed
        # For dashboard, @login_required will use settings.LOGIN_URL
        cls.login_url_setting = settings.LOGIN_URL


    def test_dashboard_redirects_if_not_logged_in(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        # Use cls.login_url_setting as defined in setUpTestData
        self.assertIn(self.login_url_setting, response.url)

    def test_dashboard_user_without_person_profile(self):
        self.client.login(username='nouserprofile_dash', password='password')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')
        self.assertIsNone(response.context['person_profile'])
        self.assertIsNone(response.context['active_tenant'])
        self.assertContains(response, "Tu usuario no está asociado a un perfil de persona")

    def test_dashboard_user1_displays_tenant1_data(self):
        self.client.login(username='user1_t1', password='password_t1')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')

        self.assertEqual(response.context['person_profile'], self.person1)
        self.assertEqual(response.context['active_tenant'], self.tenant1)

        # Permissions
        self.assertIn(self.perm1_t1_active, response.context['user_permissions'])
        self.assertEqual(len(response.context['user_permissions']), 1)
        self.assertNotContains(response, self.ap2_t1.name) # Inactive/Expired
        self.assertNotContains(response, self.ap1_t2.name) # Tenant 2's AP

        # Vehicles
        self.assertIn(self.vehicle1_t1, response.context['user_vehicles'])
        self.assertEqual(len(response.context['user_vehicles']), 1)
        self.assertNotContains(response, self.vehicle1_t2.license_plate) # Tenant 2's vehicle

        # Subscriptions
        self.assertIn(self.sub1_t1, response.context['user_subscriptions'])
        self.assertEqual(len(response.context['user_subscriptions']), 1)
        self.assertNotContains(response, self.service1_t2.name) # Tenant 2's service

        # Invoices
        self.assertIn(self.invoice1_t1_pending, response.context['user_invoices'])
        self.assertIn(self.invoice2_t1_overdue, response.context['user_invoices'])
        self.assertIn(self.invoice3_t1_paid, response.context['user_invoices'])
        self.assertEqual(len(response.context['user_invoices']), 3)
        self.assertNotContains(response, self.invoice1_t2_pending.invoice_number) # Tenant 2's invoice

        # Total Amount Due
        self.assertEqual(response.context['total_amount_due'], self.expected_total_due_tenant1)
        self.assertContains(response, f"{self.expected_total_due_tenant1:.2f}")


    def test_dashboard_user2_displays_tenant2_data(self):
        self.client.login(username='user2_t2', password='password_t2')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')

        self.assertEqual(response.context['person_profile'], self.person2)
        self.assertEqual(response.context['active_tenant'], self.tenant2)

        # Permissions
        self.assertIn(self.perm1_t2_active, response.context['user_permissions'])
        self.assertEqual(len(response.context['user_permissions']), 1)
        self.assertNotContains(response, self.ap1_t1.name) # Tenant 1's AP

        # Vehicles
        self.assertIn(self.vehicle1_t2, response.context['user_vehicles'])
        self.assertEqual(len(response.context['user_vehicles']), 1)
        self.assertNotContains(response, self.vehicle1_t1.license_plate) # Tenant 1's vehicle

        # Subscriptions
        self.assertIn(self.sub1_t2, response.context['user_subscriptions'])
        self.assertEqual(len(response.context['user_subscriptions']), 1)
        self.assertNotContains(response, self.service1_t1.name) # Tenant 1's service

        # Invoices
        self.assertIn(self.invoice1_t2_pending, response.context['user_invoices'])
        self.assertEqual(len(response.context['user_invoices']), 1)
        self.assertNotContains(response, self.invoice1_t1_pending.invoice_number) # Tenant 1's invoice

        # Total Amount Due
        self.assertEqual(response.context['total_amount_due'], self.expected_total_due_tenant2)
        self.assertContains(response, f"{self.expected_total_due_tenant2:.2f}")


    def test_dashboard_user_with_profile_no_specific_data(self):
        self.client.login(username='emptydashuser_dash', password='password')
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/user_dashboard.html')

        self.assertEqual(response.context['person_profile'], self.person_with_profile_no_data)
        self.assertEqual(response.context['active_tenant'], self.tenant1) # This user is in tenant1

        self.assertEqual(len(response.context['user_permissions']), 0)
        self.assertContains(response, "No tienes permisos de acceso activos o futuros asignados.")

        self.assertEqual(len(response.context['user_vehicles']), 0)
        self.assertContains(response, "No tienes vehículos registrados.")

        self.assertEqual(len(response.context['user_subscriptions']), 0)
        self.assertContains(response, "No tienes suscripciones registradas.")

        self.assertEqual(len(response.context['user_invoices']), 0)
        self.assertContains(response, "No tienes facturas generadas.")

        self.assertEqual(response.context['total_amount_due'], Decimal('0.00'))
        # Ensure no data from tenant2 is shown
        self.assertNotContains(response, self.ap1_t2.name)
        self.assertNotContains(response, self.vehicle1_t2.license_plate)
        self.assertNotContains(response, self.invoice1_t2_pending.invoice_number)


class UserPermissionsListAPITest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant1 = Tenant.objects.create(name="Perms API Tenant 1", subdomain_prefix="perms_api_t1")
        cls.tenant2 = Tenant.objects.create(name="Perms API Tenant 2", subdomain_prefix="perms_api_t2")

        # User 1 (Tenant 1)
        cls.user1_t1 = User.objects.create_user(username='perms_user1_t1', password='password1')
        cls.person1_t1 = Person.objects.create(full_name="Perms User One T1", identifier="P_U1T1_API", user=cls.user1_t1, tenant=cls.tenant1)
        cls.token1_t1 = Token.objects.create(user=cls.user1_t1)

        cls.ap1_t1 = AccessPoint.objects.create(name="P_AP1_T1", tenant=cls.tenant1)
        cls.ap2_t1 = AccessPoint.objects.create(name="P_AP2_T1", tenant=cls.tenant1)
        cls.perm1_p1_t1 = AccessPermission.objects.create(person=cls.person1_t1, access_point=cls.ap1_t1, is_active=True, tenant=cls.tenant1)
        cls.perm2_p1_t1 = AccessPermission.objects.create(person=cls.person1_t1, access_point=cls.ap2_t1, is_active=False, tenant=cls.tenant1) # Inactive

        # User 2 (Tenant 2)
        cls.user2_t2 = User.objects.create_user(username='perms_user2_t2', password='password2')
        cls.person2_t2 = Person.objects.create(full_name="Perms User Two T2", identifier="P_U2T2_API", user=cls.user2_t2, tenant=cls.tenant2)
        cls.token2_t2 = Token.objects.create(user=cls.user2_t2)
        cls.ap1_t2 = AccessPoint.objects.create(name="P_AP1_T2", tenant=cls.tenant2)
        cls.perm1_p2_t2 = AccessPermission.objects.create(person=cls.person2_t2, access_point=cls.ap1_t2, is_active=True, tenant=cls.tenant2)

        # User with no permissions (Tenant 1)
        cls.user_noperms_t1 = User.objects.create_user(username='perms_noperm_t1', password='password_np_t1')
        cls.person_noperms_t1 = Person.objects.create(full_name="No Perms User T1", identifier="P_NP_U1T1_API", user=cls.user_noperms_t1, tenant=cls.tenant1)
        cls.token_noperms_t1 = Token.objects.create(user=cls.user_noperms_t1)

        # User with no person profile
        cls.user_no_profile_perms = User.objects.create_user(username='perms_noprofile_api', password='password_np')
        cls.token_no_profile_perms = Token.objects.create(user=cls.user_no_profile_perms)

        cls.url = reverse('log_viewer_app:api_user_permissions')

    def setUp(self):
        self.client = APIClient()

    def test_list_permissions_unauthenticated(self):
        # Use a local APIClient for unauthenticated requests
        unauth_client = APIClient()
        response = unauth_client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_permissions_user1_t1_sees_only_t1_perms(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token1_t1.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2) # perm1_p1_t1 (active) and perm2_p1_t1 (inactive)

        response_data_str = str(response.data)
        self.assertIn(self.perm1_p1_t1.access_point.name, response_data_str)
        self.assertIn(self.perm2_p1_t1.access_point.name, response_data_str)
        self.assertNotIn(self.ap1_t2.name, response_data_str) # Ensure no Tenant 2 APs

    def test_list_permissions_user2_t2_sees_only_t2_perms(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token2_t2.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIn(self.perm1_p2_t2.access_point.name, str(response.data))
        self.assertNotIn(self.ap1_t1.name, str(response.data)) # Ensure no Tenant 1 APs

    def test_list_permissions_user_no_permissions(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_noperms_t1.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_list_permissions_user_no_person_profile(self):
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.token_no_profile_perms.key)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK) # View returns empty list
        self.assertEqual(len(response.data), 0)

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


class UserSubscriptionAdminActionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.person1 = Person.objects.create(full_name="AdminAction Person 1", identifier="AAP1")
        cls.person2 = Person.objects.create(full_name="AdminAction Person 2", identifier="AAP2")
        cls.service_monthly = Service.objects.create(name="AdminAction Monthly", price=Decimal("70.00"))

        cls.sub_due_new_invoice = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023, 1, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        cls.sub_due_existing_invoice = UserSubscription.objects.create(
            person=cls.person2, service=cls.service_monthly, start_date=date(2023, 1, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        # Assuming today is Feb 15 for the test, this invoice is for the current due cycle
        Invoice.objects.create(
            person=cls.person2, user_subscription=cls.sub_due_existing_invoice,
            cycle_start_date=date(2023, 2, 15),
            invoice_number="EXISTING001", amount_due=Decimal("70.00"), due_date=date(2023, 3, 2)
        )

        cls.sub_not_due_future_cycle = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023, 2, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=True
        )
        # Last invoice for sub_not_due_future_cycle was Feb 15, so next is Mar 15.
        Invoice.objects.create(
            person=cls.person1, user_subscription=cls.sub_not_due_future_cycle, cycle_start_date=date(2023, 2, 15),
            invoice_number="EXISTING002", amount_due=Decimal("70.00"), due_date=date(2023, 3, 2)
        )

        cls.sub_inactive = UserSubscription.objects.create(
            person=cls.person2, service=cls.service_monthly, start_date=date(2023, 1, 1),
            billing_cycle='monthly', billing_cycle_anchor_day=15, is_active=False
        )

        # This subscription's anchor day won't match the mocked 'today' in some tests
        cls.sub_not_due_anchor_day = UserSubscription.objects.create(
            person=cls.person1, service=cls.service_monthly, start_date=date(2023,1,1),
            billing_cycle='monthly', billing_cycle_anchor_day=16, is_active=True
        )


    def setUp(self):
        self.admin_user = User.objects.create_superuser('admin_test_user', 'admintest@example.com', 'password')
        self.request_factory = RequestFactory()
        self.request = self.request_factory.get('/') # Basic request
        self.request.user = self.admin_user
        self.request.session = MagicMock() # Mock the session object

        # Mock messages framework
        storage = FallbackStorage(self.request)
        setattr(self.request, '_messages', storage)

        self.model_admin = UserSubscriptionAdmin(model=UserSubscription, admin_site=AdminSite())

    @patch('log_viewer_app.admin.generate_invoice_for_subscription')
    @patch('log_viewer_app.admin.get_due_cycle_start_date_for_subscription')
    @patch('log_viewer_app.admin.timezone')
    def test_action_generates_new_invoice_successfully(self, mock_timezone, mock_get_due_date, mock_gen_invoice):
        mock_today = date(2023, 2, 15)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        # For sub_due_new_invoice, assume its last invoice was Jan 15, so Feb 15 is due.
        mock_get_due_date.return_value = date(2023, 2, 15)
        mock_invoice_instance = MagicMock(spec=Invoice); mock_invoice_instance.invoice_number = "NEW001"
        mock_gen_invoice.return_value = (mock_invoice_instance, True) # New invoice created

        queryset = UserSubscription.objects.filter(pk=self.sub_due_new_invoice.pk)
        self.model_admin.generate_invoices_for_selected_action(self.request, queryset)

        mock_get_due_date.assert_called_once_with(self.sub_due_new_invoice, mock_today)
        mock_gen_invoice.assert_called_once_with(self.sub_due_new_invoice, date(2023, 2, 15))

        messages_sent = [m.message for m in self.request._messages]
        self.assertIn("1 nueva(s) factura(s) generada(s) exitosamente.", messages_sent)

    @patch('log_viewer_app.admin.generate_invoice_for_subscription')
    @patch('log_viewer_app.admin.get_due_cycle_start_date_for_subscription')
    @patch('log_viewer_app.admin.timezone')
    def test_action_finds_existing_invoice(self, mock_timezone, mock_get_due_date, mock_gen_invoice):
        mock_today = date(2023, 2, 15)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        mock_get_due_date.return_value = date(2023, 2, 15)
        existing_invoice = Invoice.objects.get(user_subscription=self.sub_due_existing_invoice, cycle_start_date=mock_today)
        mock_gen_invoice.return_value = (existing_invoice, False) # Invoice already existed

        queryset = UserSubscription.objects.filter(pk=self.sub_due_existing_invoice.pk)
        self.model_admin.generate_invoices_for_selected_action(self.request, queryset)

        mock_get_due_date.assert_called_once_with(self.sub_due_existing_invoice, mock_today)
        mock_gen_invoice.assert_called_once_with(self.sub_due_existing_invoice, mock_today)
        messages_sent = [m.message for m in self.request._messages]
        self.assertIn("1 factura(s) ya existían para el ciclo actual y fueron omitidas por la generación.", messages_sent)

    @patch('log_viewer_app.admin.generate_invoice_for_subscription')
    @patch('log_viewer_app.admin.get_due_cycle_start_date_for_subscription')
    @patch('log_viewer_app.admin.timezone')
    def test_action_skips_not_due(self, mock_timezone, mock_get_due_date, mock_gen_invoice): # Covers future cycle and wrong anchor day via get_due_cycle returning None
        mock_today = date(2023, 2, 15)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        # For sub_not_due_future_cycle, next cycle is Mar 15.
        # For sub_not_due_anchor_day, admin action calls helper, helper returns date, but admin action does not have anchor day check.
        # The prompt's admin action code calls get_due_cycle_start_date_for_subscription, which does NOT check anchor day.
        # So, for sub_not_due_anchor_day, get_due_cycle_start_date_for_subscription might return a date if a cycle is otherwise due.
        # The admin action as per prompt *would* try to bill it if get_due_cycle_start_date_for_subscription returns a date.
        # Let's test sub_not_due_future_cycle where get_due_cycle_start_date_for_subscription returns None.
        mock_get_due_date.return_value = None

        queryset = UserSubscription.objects.filter(pk=self.sub_not_due_future_cycle.pk)
        self.model_admin.generate_invoices_for_selected_action(self.request, queryset)

        mock_get_due_date.assert_called_once_with(self.sub_not_due_future_cycle, mock_today)
        mock_gen_invoice.assert_not_called()
        messages_sent = [m.message for m in self.request._messages]
        self.assertIn("1 suscripciones fueron omitidas (no se cumplían criterios de facturación como ciclo/fechas o fallaron). Revise los logs para más detalles en caso de fallos.", messages_sent)


    @patch('log_viewer_app.admin.get_due_cycle_start_date_for_subscription') # Mock get_due_date
    @patch('log_viewer_app.admin.generate_invoice_for_subscription') # Mock gen_invoice
    @patch('log_viewer_app.admin.timezone')
    def test_action_skips_inactive_subscription(self, mock_timezone, mock_gen_invoice, mock_get_due_date): # Corrected order of mocks
        mock_today = date(2023, 2, 15)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        queryset = UserSubscription.objects.filter(pk=self.sub_inactive.pk)
        self.model_admin.generate_invoices_for_selected_action(self.request, queryset)

        # get_due_cycle_start_date_for_subscription should not be called because of the is_active check in the action
        mock_get_due_date.assert_not_called()
        mock_gen_invoice.assert_not_called()
        messages_sent = [m.message for m in self.request._messages]
        self.assertIn("1 suscripciones fueron omitidas (no se cumplían criterios de facturación como ciclo/fechas o fallaron). Revise los logs para más detalles en caso de fallos.", messages_sent)

    @patch('log_viewer_app.admin.generate_invoice_for_subscription')
    @patch('log_viewer_app.admin.get_due_cycle_start_date_for_subscription')
    @patch('log_viewer_app.admin.timezone')
    def test_action_handles_internal_failure_in_generation(self, mock_timezone, mock_get_due_date, mock_gen_invoice):
        mock_today = date(2023, 2, 15)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        mock_get_due_date.return_value = mock_today # This sub is due
        mock_gen_invoice.return_value = (None, False) # Simulate failure in generate_invoice_for_subscription

        queryset = UserSubscription.objects.filter(pk=self.sub_due_new_invoice.pk)
        self.model_admin.generate_invoices_for_selected_action(self.request, queryset)

        messages_sent = [m.message for m in self.request._messages]
        self.assertIn("1 suscripciones fueron omitidas (no se cumplían criterios de facturación como ciclo/fechas o fallaron). Revise los logs para más detalles en caso de fallos.", messages_sent)

    @patch('log_viewer_app.admin.generate_invoice_for_subscription')
    @patch('log_viewer_app.admin.get_due_cycle_start_date_for_subscription')
    @patch('log_viewer_app.admin.timezone')
    def test_action_handles_mixed_outcomes(self, mock_timezone, mock_get_due_date, mock_gen_invoice):
        mock_today = date(2023, 2, 15)
        mock_timezone.now.return_value = dt_datetime(mock_today.year, mock_today.month, mock_today.day)

        mock_new_invoice = MagicMock(spec=Invoice); mock_new_invoice.invoice_number = "MIXED_NEW"
        existing_invoice = Invoice.objects.get(user_subscription=self.sub_due_existing_invoice, cycle_start_date=mock_today)

        def get_due_date_side_effect(subscription, as_of_date_arg):
            if subscription == self.sub_due_new_invoice: return mock_today
            if subscription == self.sub_due_existing_invoice: return mock_today
            if subscription == self.sub_not_due_future_cycle: return None # Not due
            if subscription == self.sub_inactive: return None # is_active check in action should catch this first
            return None
        mock_get_due_date.side_effect = get_due_date_side_effect

        def gen_invoice_side_effect(subscription, cycle_start_date):
            if subscription == self.sub_due_new_invoice: return (mock_new_invoice, True)
            if subscription == self.sub_due_existing_invoice: return (existing_invoice, False)
            return (None, False)
        mock_gen_invoice.side_effect = gen_invoice_side_effect

        queryset = UserSubscription.objects.filter(
            pk__in=[
                self.sub_due_new_invoice.pk,
                self.sub_due_existing_invoice.pk,
                self.sub_not_due_future_cycle.pk,
                self.sub_inactive.pk
            ]
        ).order_by('pk')

        self.model_admin.generate_invoices_for_selected_action(self.request, queryset)

        messages_sent = [m.message for m in self.request._messages]
        self.assertTrue(any("1 nueva(s) factura(s) generada(s) exitosamente." in m for m in messages_sent))
        self.assertTrue(any("1 factura(s) ya existían para el ciclo actual y fueron omitidas por la generación." in m for m in messages_sent))
        # sub_not_due_future_cycle (get_due_cycle returns None) + sub_inactive (skipped by action's initial check) = 2 skips
        self.assertTrue(any("2 suscripciones fueron omitidas" in m for m in messages_sent))

# The OldGeneratePeriodicInvoicesCommandTest class is now removed.


# --- Tests for Person Profile Editing ---
class PersonProfileEditFormTest(TestCase):
    def test_form_valid_data(self):
        form = PersonProfileEditForm(data={'full_name': 'Test User Valid Name'})
        self.assertTrue(form.is_valid())

    def test_form_save_updates_person(self):
        user = User.objects.create_user(username='profileuser', password='password')
        person = Person.objects.create(user=user, full_name="Original Name", identifier="PU007")
        form = PersonProfileEditForm(instance=person, data={'full_name': 'Nuevo Nombre Completo'})
        self.assertTrue(form.is_valid())
        form.save()
        person.refresh_from_db()
        self.assertEqual(person.full_name, 'Nuevo Nombre Completo')

    def test_form_fields_are_correct(self):
        form = PersonProfileEditForm()
        self.assertEqual(list(form.fields.keys()), ['full_name'])
        self.assertEqual(form.Meta.fields, ['full_name'])

    def test_form_empty_full_name_invalid(self):
        form = PersonProfileEditForm(data={'full_name': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('full_name', form.errors)
        self.assertEqual(form.errors['full_name'][0], 'This field is required.')


class PersonProfileEditViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_with_profile = User.objects.create_user(username='userwithprofile', password='password123')
        cls.person_profile = Person.objects.create(user=cls.user_with_profile, full_name="Initial Profile Name", identifier="PROFILE01")

        cls.user_no_profile = User.objects.create_user(username='usernoprofile', password='password123')

        cls.edit_profile_url = reverse('log_viewer_app:person_profile_edit')
        cls.dashboard_url = reverse('log_viewer_app:user_dashboard')
        # cls.login_url will be set in setUp

    def setUp(self):
        self.login_url = '/accounts/login/' # Hardcoded path as a test

    def test_view_redirects_if_not_logged_in(self):
        response = self.client.get(self.edit_profile_url)
        self.assertRedirects(response, f'{self.login_url}?next={self.edit_profile_url}')

    def test_view_redirects_if_user_has_no_person_profile(self):
        self.client.login(username='usernoprofile', password='password123')
        response = self.client.get(self.edit_profile_url, follow=True) # follow=True to check final destination and messages
        self.assertRedirects(response, self.dashboard_url, status_code=302, target_status_code=200)

        messages_list = list(response.context.get('messages', []))
        self.assertTrue(any(message.level == messages.ERROR and "No se encontró un perfil de persona asociado" in message.message for message in messages_list))

    def test_view_get_shows_form_with_instance_data(self):
        self.client.login(username='userwithprofile', password='password123')
        response = self.client.get(self.edit_profile_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/person_profile_edit_form.html')
        self.assertIsInstance(response.context['form'], PersonProfileEditForm)
        self.assertEqual(response.context['form'].instance, self.person_profile)
        self.assertContains(response, self.person_profile.full_name) # Check if current name is in the form

    def test_view_post_valid_data_updates_profile_and_redirects(self):
        self.client.login(username='userwithprofile', password='password123')
        new_name = 'Nombre Actualizado Por Test'
        post_data = {'full_name': new_name}

        response = self.client.post(self.edit_profile_url, post_data, follow=True)

        self.assertRedirects(response, self.dashboard_url, status_code=302, target_status_code=200)

        self.person_profile.refresh_from_db()
        self.assertEqual(self.person_profile.full_name, new_name)

        messages_list = list(response.context.get('messages', []))
        self.assertTrue(any(message.level == messages.SUCCESS and "Tu perfil ha sido actualizado exitosamente." in message.message for message in messages_list))

    def test_view_post_invalid_data_rerenders_form(self):
        self.client.login(username='userwithprofile', password='password123')
        original_name = self.person_profile.full_name
        post_data = {'full_name': ''} # Invalid empty name

        response = self.client.post(self.edit_profile_url, post_data)

        self.assertEqual(response.status_code, 200) # Should re-render the form
        self.assertIsInstance(response.context['form'], PersonProfileEditForm)
        self.assertTrue(response.context['form'].errors)
        self.assertIn('full_name', response.context['form'].errors)

        self.person_profile.refresh_from_db()
        self.assertEqual(self.person_profile.full_name, original_name) # Name should not have changed
