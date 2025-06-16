from django.test import TestCase
from django.urls import reverse
from .models import AccessLog, Person, Vehicle, AccessPoint, AccessPermission
from .forms import PersonForm, VehicleForm, AccessPermissionForm
from .utils import verify_access_with_models # For testing access logic
from django.utils import timezone
from datetime import timedelta

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
            owner=self.owner,
            license_plate="XYZ123",
            description="Red Car"
        )
        self.assertIsInstance(vehicle, Vehicle)
        self.assertEqual(vehicle.owner, self.owner)
        self.assertEqual(vehicle.license_plate, "XYZ123")
        self.assertEqual(vehicle.description, "Red Car")
        self.assertEqual(str(vehicle), "XYZ123 (Jane Smith)")

class AccessPointModelTest(TestCase):
    def test_access_point_creation(self):
        ap = AccessPoint.objects.create(name="Main Gate", description="Main entrance")
        self.assertIsInstance(ap, AccessPoint)
        self.assertEqual(ap.name, "Main Gate")
        self.assertEqual(ap.description, "Main entrance")
        self.assertEqual(str(ap), "Main Gate")

class AccessPermissionModelTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(full_name="Alice Wonderland", identifier="AW003")
        self.access_point = AccessPoint.objects.create(name="Wonderland Gate")

    def test_access_permission_creation(self):
        now = timezone.now()
        permission = AccessPermission.objects.create(
            person=self.person,
            access_point=self.access_point,
            is_active=True,
            valid_from=now,
            valid_until=now + timedelta(days=30)
        )
        self.assertIsInstance(permission, AccessPermission)
        self.assertEqual(permission.person, self.person)
        self.assertEqual(permission.access_point, self.access_point)
        self.assertTrue(permission.is_active)
        self.assertIn("Alice Wonderland", str(permission))
        self.assertIn("Wonderland Gate", str(permission))
        self.assertIn("Activo", str(permission))

    def test_access_permission_unique_together(self):
        AccessPermission.objects.create(person=self.person, access_point=self.access_point)
        with self.assertRaises(Exception): # django.db.utils.IntegrityError
            AccessPermission.objects.create(person=self.person, access_point=self.access_point)

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
        form = VehicleForm(data={
            'owner': self.owner.pk,
            'license_plate': 'VF123',
            'description': 'Test Vehicle'
        })
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
        form = AccessPermissionForm(data={
            'person': self.person.pk,
            'access_point': self.ap.pk,
            'is_active': True,
            'valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'), # Format for datetime-local
            'valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        })
        self.assertTrue(form.is_valid())

    def test_access_permission_form_save(self):
        form = AccessPermissionForm(data={
            'person': self.person.pk,
            'access_point': self.ap.pk,
            'is_active': True
        })
        self.assertTrue(form.is_valid()) # valid_from uses default, valid_until is blank
        permission = form.save()
        self.assertIsInstance(permission, AccessPermission)
        self.assertTrue(permission.is_active)


# --- View Tests (Original AccessLogListViewTest and new ones) ---
class AccessLogListViewTest(TestCase): # Renamed from previous subtask's example if needed
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
        response = self.client.post(reverse('log_viewer_app:person_create'), {
            'full_name': 'Create Person Test', 'identifier': 'CPT01'
        })
        self.assertEqual(response.status_code, 302) # Redirect on success
        self.assertRedirects(response, reverse('log_viewer_app:person_list'))
        self.assertEqual(Person.objects.count(), initial_count + 1)

    def test_person_create_view_post_invalid(self):
        response = self.client.post(reverse('log_viewer_app:person_create'), {'full_name': 'No ID'})
        self.assertEqual(response.status_code, 200) # Re-renders form
        self.assertFormError(response.context['form'], 'identifier', 'This field is required.')


class VehicleListViewTest(TestCase): # Similar structure for Vehicle and AccessPermission views
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
        response = self.client.post(reverse('log_viewer_app:vehicle_create'), {
            'owner': self.owner.pk, 'license_plate': 'VCV01', 'description': 'Created Vehicle'
        })
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
        response = self.client.post(reverse('log_viewer_app:permission_create'), {
            'person': self.person.pk,
            'access_point': self.ap.pk,
            'is_active': True,
            # valid_from and valid_until are optional or use defaults
        })
        self.assertEqual(response.status_code, 302, f"Form errors: {response.context.get('form').errors if response.context else 'No context'}")
        self.assertTrue(AccessPermission.objects.filter(person=self.person, access_point=self.ap).exists())


# --- Logic Tests (verify_access_with_models) ---
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
        cls.ap2 = AccessPoint.objects.create(name="SecretDoor")

        # Valid, active permission
        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap1, is_active=True)
        # Active permission for a different door
        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap2, is_active=True)
        # Inactive permission
        AccessPermission.objects.create(person=cls.person3, access_point=cls.ap1, is_active=False)
        # Future permission
        AccessPermission.objects.create(person=cls.person4, access_point=cls.ap1, is_active=True,
                                        valid_from=timezone.now() + timedelta(days=1))
        # Expired permission
        AccessPermission.objects.create(person=cls.person5, access_point=cls.ap1, is_active=True,
                                        valid_until=timezone.now() - timedelta(days=1))
        # Time-valid permission (valid_from in past, valid_until in future)
        AccessPermission.objects.create(person=cls.person6, access_point=cls.ap1, is_active=True,
                                        valid_from=timezone.now() - timedelta(hours=1),
                                        valid_until=timezone.now() + timedelta(hours=1))


    def tearDown(self):
        # Clean up AccessLog entries after each test if necessary,
        # or rely on test database rollback. For now, let's clear to be explicit.
        AccessLog.objects.all().delete()

    def test_access_allowed(self):
        self.assertTrue(verify_access_with_models("ALLOW_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertTrue(log.access_granted)
        self.assertEqual(log.qr_data, "ALLOW_ID")
        self.assertEqual(log.user_id, "ALLOW_ID")

    def test_person_not_found(self):
        self.assertFalse(verify_access_with_models("UNKNOWN_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)
        self.assertEqual(log.qr_data, "UNKNOWN_ID")
        self.assertEqual(log.user_id, "UNKNOWN_ID")


    def test_access_point_not_found(self):
        self.assertFalse(verify_access_with_models("ALLOW_ID", "NonExistentDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)
        self.assertEqual(log.user_id, "ALLOW_ID")


    def test_permission_not_found(self): # Person exists, AP exists, but no link
        self.assertFalse(verify_access_with_models("NOPERM_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)
        self.assertEqual(log.user_id, "NOPERM_ID")

    def test_permission_inactive(self):
        self.assertFalse(verify_access_with_models("INACTIVE_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)

    def test_permission_future_valid_from(self):
        self.assertFalse(verify_access_with_models("FUTURE_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)

    def test_permission_expired_valid_until(self):
        self.assertFalse(verify_access_with_models("EXPIRED_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)

    def test_permission_time_valid(self): # valid_from past, valid_until future
        self.assertTrue(verify_access_with_models("TIMEVALID_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertTrue(log.access_granted)

    def test_permission_valid_from_only_no_end(self): # Test case: valid_from is past, valid_until is None
        person_perm_no_end = Person.objects.create(full_name="PermNoEnd User", identifier="NOEND_ID")
        AccessPermission.objects.create(
            person=person_perm_no_end,
            access_point=self.ap1,
            is_active=True,
            valid_from=timezone.now() - timedelta(days=1), # Valid from yesterday
            valid_until=None # No expiry
        )
        self.assertTrue(verify_access_with_models("NOEND_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertTrue(log.access_granted)

    def test_permission_default_valid_from_no_end(self): # Test case: valid_from uses default (now), valid_until is None
        person_perm_default_start = Person.objects.create(full_name="PermDefaultStart User", identifier="DEFAULTSTART_ID")
        # valid_from will use default=timezone.now in the model
        AccessPermission.objects.create(
            person=person_perm_default_start,
            access_point=self.ap1,
            is_active=True,
            valid_until=None # No expiry
        )
        # This test might be flaky if execution time is very close to the second boundary.
        # A slight delay or using a time slightly in the past for valid_from would be more robust.
        # For now, we assume default=timezone.now makes it immediately valid.
        self.assertTrue(verify_access_with_models("DEFAULTSTART_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertTrue(log.access_granted)
