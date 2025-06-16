from django.test import TestCase
from django.urls import reverse
from .models import AccessLog, Person, Vehicle, AccessPoint, AccessPermission, ControlDevice # ControlDevice added
from .forms import PersonForm, VehicleForm, AccessPermissionForm, ControlDeviceForm # ControlDeviceForm added
from .utils import verify_access_with_models, publish_mqtt_message # publish_mqtt_message added
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock # For mocking
from django.conf import settings # To check MQTT settings


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

class ControlDeviceModelTest(TestCase):
    def setUp(self):
        self.ap = AccessPoint.objects.create(name="Garage Door AP")

    def test_control_device_creation(self):
        device = ControlDevice.objects.create(
            name="Garage Controller 1",
            device_id="GDCTRL001",
            access_point=self.ap,
            mqtt_topic="garage/door1/control",
            ip_address="192.168.1.100",
            is_active=True
        )
        self.assertIsInstance(device, ControlDevice)
        self.assertEqual(device.name, "Garage Controller 1")
        self.assertEqual(device.device_id, "GDCTRL001")
        self.assertEqual(device.access_point, self.ap)
        self.assertEqual(device.mqtt_topic, "garage/door1/control")
        self.assertEqual(str(device), "Garage Controller 1 (GDCTRL001) - AP: Garage Door AP")

    def test_control_device_str_no_ap(self):
        device = ControlDevice.objects.create(
            name="Unassigned Controller",
            device_id="UCTRL002",
            mqtt_topic="unassigned/control"
        )
        self.assertEqual(str(device), "Unassigned Controller (UCTRL002) - AP: No asignado")


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
            'valid_from': timezone.now().strftime('%Y-%m-%dT%H:%M'),
            'valid_until': (timezone.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        })
        self.assertTrue(form.is_valid())

    def test_access_permission_form_save(self):
        form = AccessPermissionForm(data={
            'person': self.person.pk,
            'access_point': self.ap.pk,
            'is_active': True
        })
        self.assertTrue(form.is_valid())
        permission = form.save()
        self.assertIsInstance(permission, AccessPermission)
        self.assertTrue(permission.is_active)

class ControlDeviceFormTest(TestCase):
    def setUp(self):
        self.ap = AccessPoint.objects.create(name="Device Form AP")

    def test_control_device_form_valid_data(self):
        form = ControlDeviceForm(data={
            'name': 'Test Device',
            'device_id': 'DEVFORM001',
            'access_point': self.ap.pk,
            'mqtt_topic': 'test/device/topic',
            'is_active': True
        })
        self.assertTrue(form.is_valid())

    def test_control_device_form_invalid_missing_device_id(self):
        form = ControlDeviceForm(data={'name': 'Test Device No ID'})
        self.assertFalse(form.is_valid())
        self.assertIn('device_id', form.errors)

    def test_control_device_form_save(self):
        form = ControlDeviceForm(data={
            'name': 'Save Device',
            'device_id': 'SDEV001',
            'access_point': self.ap.pk,
            'mqtt_topic': 'save/device/topic'
        })
        self.assertTrue(form.is_valid())
        device = form.save()
        self.assertIsInstance(device, ControlDevice)
        self.assertEqual(device.device_id, 'SDEV001')


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
        response = self.client.post(reverse('log_viewer_app:person_create'), {
            'full_name': 'Create Person Test', 'identifier': 'CPT01'
        })
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
        })
        self.assertEqual(response.status_code, 302, f"Form errors: {response.context.get('form').errors if response.context else 'No context'}")
        self.assertTrue(AccessPermission.objects.filter(person=self.person, access_point=self.ap).exists())

class AccessPermissionUpdateViewTest(TestCase):
    def setUp(self):
        self.person1 = Person.objects.create(full_name="Test Person Update", identifier="TPU01")
        self.ap1 = AccessPoint.objects.create(name="Test AP Update")
        self.permission1 = AccessPermission.objects.create(
            person=self.person1,
            access_point=self.ap1,
            is_active=True
        )
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
        # Initially active, try to make it inactive
        self.assertTrue(self.permission1.is_active)
        post_data = {
            'person': self.person1.pk,
            'access_point': self.ap1.pk,
            'is_active': False, # Changing this value
            'valid_from': self.permission1.valid_from.strftime('%Y-%m-%dT%H:%M') if self.permission1.valid_from else '',
            'valid_until': self.permission1.valid_until.strftime('%Y-%m-%dT%H:%M') if self.permission1.valid_until else ''
        }
        response = self.client.post(self.update_url, post_data)
        self.assertEqual(response.status_code, 302) # Should redirect
        self.assertRedirects(response, self.list_url)

        self.permission1.refresh_from_db()
        self.assertFalse(self.permission1.is_active) # Check if update was successful

    def test_permission_update_view_post_invalid_non_existent_person(self):
        non_existent_person_pk = 99999
        original_is_active = self.permission1.is_active
        post_data = {
            'person': non_existent_person_pk, # This person does not exist
            'access_point': self.ap1.pk,
            'is_active': not original_is_active, # Attempt to change something
        }
        response = self.client.post(self.update_url, post_data)
        self.assertEqual(response.status_code, 200) # Should re-render form
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('person', response.context['form'].errors) # Error should be on person field

        self.permission1.refresh_from_db()
        self.assertEqual(self.permission1.is_active, original_is_active) # Ensure no change

    def test_permission_update_view_get_not_found(self):
        non_existent_pk = 99999
        url = reverse('log_viewer_app:permission_update', kwargs={'pk': non_existent_pk})
        response = self.client.get(url)
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
        response = self.client.post(reverse('log_viewer_app:control_device_create'), {
            'name': 'New CD', 'device_id': 'NCD01', 'access_point': self.ap.pk, 'mqtt_topic': 'new/cd/topic'
        })
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
        response = self.client.post(reverse('log_viewer_app:control_device_update', kwargs={'pk': self.device.pk}), {
            'name': 'Updated CD Name', 'device_id': 'CDU01_updated',
            'access_point': self.ap.pk, 'mqtt_topic': 'updated/cd/topic', 'is_active': True
        })
        self.assertEqual(response.status_code, 302)
        updated_device = ControlDevice.objects.get(pk=self.device.pk)
        self.assertEqual(updated_device.name, "Updated CD Name")
        self.assertEqual(updated_device.device_id, "CDU01_updated")

    def test_cd_update_view_non_existent(self):
        response = self.client.get(reverse('log_viewer_app:control_device_update', kwargs={'pk': 9999}))
        self.assertEqual(response.status_code, 404)


# --- Logic Tests (verify_access_with_models & MQTT) ---
class MQTTUtilsTest(TestCase):
    @patch('log_viewer_app.utils.publish.single')
    def test_publish_mqtt_message_success(self, mock_publish_single):
        # Store original settings if they exist, or ensure they are not set
        original_mqtt_user = getattr(settings, 'MQTT_USERNAME', None)
        original_mqtt_pass = getattr(settings, 'MQTT_PASSWORD', None)
        if original_mqtt_user: delattr(settings, 'MQTT_USERNAME')
        if original_mqtt_pass: delattr(settings, 'MQTT_PASSWORD')

        settings.MQTT_BROKER_HOST = 'testbroker'
        settings.MQTT_BROKER_PORT = 18830
        settings.MQTT_CLIENT_ID = 'testclient'

        result = publish_mqtt_message("test/topic", "payload_test")
        self.assertTrue(result)
        mock_publish_single.assert_called_once_with(
            "test/topic",
            payload="payload_test",
            qos=1,
            retain=False,
            hostname='testbroker',
            port=18830,
            client_id='testclient',
            auth=None
        )
        # Restore original settings
        if original_mqtt_user: setattr(settings, 'MQTT_USERNAME', original_mqtt_user)
        if original_mqtt_pass: setattr(settings, 'MQTT_PASSWORD', original_mqtt_pass)


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
            "auth/topic",
            payload="auth_payload",
            qos=1,
            retain=False,
            hostname='authbroker',
            port=18831,
            client_id='authclient',
            auth={'username': 'user', 'password': 'pass'}
        )

    @patch('log_viewer_app.utils.publish.single', side_effect=ConnectionRefusedError("Test refuse"))
    @patch('log_viewer_app.utils.logger.error')
    def test_publish_mqtt_connection_refused(self, mock_logger_error, mock_publish_single):
        result = publish_mqtt_message("refuse/topic", "refuse_payload")
        self.assertFalse(result)
        mock_logger_error.assert_called_with(
            f"MQTT Error: Conexión rechazada al broker {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}. Verifica que el broker esté activo y accesible."
        )

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
        cls.ap2 = AccessPoint.objects.create(name="SecretDoor")
        cls.ap_mqtt = AccessPoint.objects.create(name="MQTT_Controlled_Door")

        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap1, is_active=True)
        AccessPermission.objects.create(person=cls.person1, access_point=cls.ap2, is_active=True)
        AccessPermission.objects.create(person=cls.person3, access_point=cls.ap1, is_active=False)
        AccessPermission.objects.create(person=cls.person4, access_point=cls.ap1, is_active=True, valid_from=timezone.now() + timedelta(days=1))
        AccessPermission.objects.create(person=cls.person5, access_point=cls.ap1, is_active=True, valid_until=timezone.now() - timedelta(days=1))
        AccessPermission.objects.create(person=cls.person6, access_point=cls.ap1, is_active=True, valid_from=timezone.now() - timedelta(hours=1), valid_until=timezone.now() + timedelta(hours=1))

        cls.device1_ap_mqtt = ControlDevice.objects.create(name="MQTT_Door_Ctrl1", device_id="CTRL_MQTT1", access_point=cls.ap_mqtt, mqtt_topic="door/mqtt1/open", is_active=True)
        cls.device2_ap_mqtt_inactive = ControlDevice.objects.create(name="MQTT_Door_Ctrl2_Inactive", device_id="CTRL_MQTT2", access_point=cls.ap_mqtt, mqtt_topic="door/mqtt2/open", is_active=False)
        cls.person_mqtt = Person.objects.create(full_name="MQTT Access User", identifier="MQTT_ACCESS_ID")
        AccessPermission.objects.create(person=cls.person_mqtt, access_point=cls.ap_mqtt, is_active=True)

    def tearDown(self):
        AccessLog.objects.all().delete()

    def test_access_allowed(self):
        self.assertTrue(verify_access_with_models("ALLOW_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertTrue(log.access_granted)
        self.assertEqual(log.qr_data, "ALLOW_ID")

    def test_person_not_found(self):
        self.assertFalse(verify_access_with_models("UNKNOWN_ID", "MainDoor"))
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_triggers_mqtt_publish_single_device(self, mock_publish_mqtt_func):
        mock_publish_mqtt_func.return_value = True
        result = verify_access_with_models(qr_identifier="MQTT_ACCESS_ID", access_point_name="MQTT_Controlled_Door")
        self.assertTrue(result)
        mock_publish_mqtt_func.assert_called_once_with(topic=self.device1_ap_mqtt.mqtt_topic, payload="OPEN")
        log = AccessLog.objects.latest('timestamp')
        self.assertTrue(log.access_granted)
        self.assertEqual(log.qr_data, "MQTT_ACCESS_ID")

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_granted_no_active_devices(self, mock_publish_mqtt_func):
        active_device = ControlDevice.objects.get(device_id="CTRL_MQTT1") # self.device1_ap_mqtt
        active_device.is_active = False
        active_device.save()

        result = verify_access_with_models(qr_identifier="MQTT_ACCESS_ID", access_point_name="MQTT_Controlled_Door")

        self.assertTrue(result)
        mock_publish_mqtt_func.assert_not_called()

        active_device.is_active = True # Restore
        active_device.save()

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_access_denied_no_mqtt_publish(self, mock_publish_mqtt_func):
        result = verify_access_with_models(qr_identifier="NOPERM_ID", access_point_name="MQTT_Controlled_Door")
        self.assertFalse(result)
        mock_publish_mqtt_func.assert_not_called()
        log = AccessLog.objects.latest('timestamp')
        self.assertFalse(log.access_granted)

    @patch('log_viewer_app.utils.publish_mqtt_message')
    def test_multiple_active_devices_mqtt_publish(self, mock_publish_mqtt_func):
        mock_publish_mqtt_func.return_value = True
        device_extra = ControlDevice.objects.create(
            name="MQTT_Door_Ctrl_Extra", device_id="CTRL_MQTT_EXTRA",
            access_point=self.ap_mqtt, mqtt_topic="door/mqttextra/open", is_active=True
        )
        result = verify_access_with_models(qr_identifier="MQTT_ACCESS_ID", access_point_name="MQTT_Controlled_Door")
        self.assertTrue(result)
        self.assertEqual(mock_publish_mqtt_func.call_count, 2)
        actual_call_topics = [call.kwargs['topic'] for call in mock_publish_mqtt_func.call_args_list]
        expected_topics = [self.device1_ap_mqtt.mqtt_topic, device_extra.mqtt_topic]
        self.assertCountEqual(actual_call_topics, expected_topics)
        device_extra.delete()

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
        person_perm_no_end, _ = Person.objects.get_or_create(full_name="PermNoEnd User", identifier="NOEND_ID")
        AccessPermission.objects.get_or_create(
            person=person_perm_no_end,
            access_point=self.ap1,
            defaults={
                'is_active':True,
                'valid_from':timezone.now() - timedelta(days=1),
                'valid_until':None
            }
        )
        self.assertTrue(verify_access_with_models("NOEND_ID", "MainDoor"))

    def test_permission_default_valid_from_no_end(self):
        person_perm_default_start, _ = Person.objects.get_or_create(full_name="PermDefaultStart User", identifier="DEFAULTSTART_ID")
        AccessPermission.objects.get_or_create(
            person=person_perm_default_start,
            access_point=self.ap1,
            defaults={'is_active':True, 'valid_until':None}
        )
        self.assertTrue(verify_access_with_models("DEFAULTSTART_ID", "MainDoor"))
