from django.test import TestCase
from django.urls import reverse
from .models import AccessLog
from django.utils import timezone # Para comparar datetimes si es necesario

class AccessLogModelTest(TestCase):
    def test_access_log_creation(self):
        log = AccessLog.objects.create(
            qr_data="QR_TEST_MODEL",
            access_granted=True,
            event_type="test_event",
            user_id="test_user"
        )
        self.assertIsInstance(log, AccessLog)
        self.assertEqual(log.qr_data, "QR_TEST_MODEL")
        self.assertTrue(log.access_granted)
        self.assertEqual(log.event_type, "test_event")
        self.assertEqual(log.user_id, "test_user")
        self.assertIsNotNone(log.timestamp)
        # Comprobar que __str__ funciona y devuelve el qr_data
        self.assertIn("QR_TEST_MODEL", str(log))
        self.assertIn("Permitido", str(log))

class AccessLogListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Crear datos de prueba una vez para toda la clase de prueba
        # si no se modifican por las pruebas.
        # Estos datos persistirán para todos los tests de esta clase a menos que se borren.
        AccessLog.objects.create(qr_data="QR_VIEW_TEST_1", access_granted=True, event_type="entrada_auto", user_id="user_A")
        AccessLog.objects.create(qr_data="QR_VIEW_TEST_2", access_granted=False, event_type="salida_manual", user_id="user_B")

    def test_view_url_exists_at_desired_location(self):
        response = self.client.get('/access/logs/') # Hardcoded URL
        self.assertEqual(response.status_code, 200)

    def test_view_url_accessible_by_name(self):
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(response.status_code, 200)

    def test_view_uses_correct_template(self):
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'log_viewer_app/access_log_list.html')

    def test_view_displays_logs_when_present(self):
        # Los datos de setUpTestData deberían estar presentes aquí.
        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.context['access_logs']) >= 2, "Should be at least 2 logs from setUpTestData")
        self.assertContains(response, "QR_VIEW_TEST_1")
        self.assertContains(response, "Permitido")
        self.assertContains(response, "entrada_auto")
        self.assertContains(response, "user_A")
        self.assertContains(response, "QR_VIEW_TEST_2")
        self.assertContains(response, "Denegado")
        self.assertContains(response, "salida_manual")
        self.assertContains(response, "user_B")

    def test_view_displays_no_logs_message_when_empty(self):
        # Borrar todos los logs para esta prueba específica para asegurar que la BD esté vacía
        AccessLog.objects.all().delete()

        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(response.status_code, 200)
        # Verificar que el contexto 'access_logs' esté vacío
        self.assertEqual(len(response.context['access_logs']), 0)
        # Verificar que el mensaje para "no logs" esté presente en el contenido
        self.assertContains(response, "No hay registros de acceso para mostrar.")

    def test_log_ordering(self):
        # Borrar logs existentes para asegurar un orden predecible
        AccessLog.objects.all().delete()
        log1 = AccessLog.objects.create(qr_data="OLDER_LOG", access_granted=True, timestamp=timezone.now() - timezone.timedelta(days=1))
        log2 = AccessLog.objects.create(qr_data="NEWER_LOG", access_granted=True, timestamp=timezone.now())

        response = self.client.get(reverse('log_viewer_app:access_log_list'))
        self.assertEqual(response.status_code, 200)
        logs_in_context = response.context['access_logs']
        self.assertEqual(len(logs_in_context), 2)
        # Verificar que el más nuevo (log2) venga primero
        self.assertEqual(logs_in_context[0].qr_data, "NEWER_LOG")
        self.assertEqual(logs_in_context[1].qr_data, "OLDER_LOG")
