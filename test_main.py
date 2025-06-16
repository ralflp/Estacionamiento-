import unittest
from datetime import datetime
# Importar directamente desde main.py (asumiendo que está en el mismo directorio o PYTHONPATH)
import main

class TestMainApp(unittest.TestCase):

    def setUp(self):
        # Limpiar la lista global de logs antes de cada prueba
        main.access_logs.clear()
        # Establecer una lista de QRs autorizados conocida para las pruebas
        # Esto es importante para evitar que las pruebas dependan del estado de AUTORIZADOS_QRS en main.py
        main.AUTORIZADOS_QRS = ["TEST_QR_PERMITIDO_1", "TEST_QR_PERMITIDO_2"]

    # --- Pruebas para AccessLogEntry ---
    def test_access_log_entry_creation(self):
        qr_data = "TEST_QR_DATA"
        access_granted = True
        event_type = "prueba_evento"
        user_id = "usuario_test_001"

        entry = main.AccessLogEntry(qr_data, access_granted, event_type=event_type, user_id=user_id)

        self.assertIsInstance(entry.timestamp, datetime, "Timestamp should be a datetime object")
        self.assertEqual(entry.qr_data, qr_data)
        self.assertEqual(entry.access_granted, access_granted)
        self.assertEqual(entry.event_type, event_type)
        self.assertEqual(entry.user_id, user_id)

    def test_access_log_entry_repr(self):
        qr_data = "REPR_TEST_QR"
        entry_permitido = main.AccessLogEntry(qr_data, True, user_id="user_repr")
        entry_denegado = main.AccessLogEntry(qr_data, False, event_type="special_event")

        repr_permitido = repr(entry_permitido)
        repr_denegado = repr(entry_denegado)

        self.assertIn(qr_data, repr_permitido)
        self.assertIn("Permitido", repr_permitido)
        self.assertIn("user_repr", repr_permitido)
        self.assertIn("acceso_general", repr_permitido) # Default event_type

        self.assertIn(qr_data, repr_denegado)
        self.assertIn("Denegado", repr_denegado)
        self.assertIn("N/A", repr_denegado) # Default user_id
        self.assertIn("special_event", repr_denegado)

        # Check timestamp format (basic check)
        self.assertRegex(repr_permitido, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")

    # --- Pruebas para check_access y el registro en access_logs ---
    def test_check_access_logs_permitido(self):
        qr_permitido = "TEST_QR_PERMITIDO_1"
        result = main.check_access(qr_permitido)

        self.assertTrue(result, "check_access should return True for an authorized QR")
        self.assertEqual(len(main.access_logs), 1, "One log entry should be added")

        log_entry = main.access_logs[0]
        self.assertIsInstance(log_entry, main.AccessLogEntry)
        self.assertTrue(log_entry.access_granted)
        self.assertEqual(log_entry.qr_data, qr_permitido)
        self.assertEqual(log_entry.event_type, "acceso_general") # Default
        self.assertIsNone(log_entry.user_id) # Default

    def test_check_access_logs_denegado(self):
        qr_denegado = "TEST_QR_DENEGADO_XYZ"
        result = main.check_access(qr_denegado)

        self.assertFalse(result, "check_access should return False for an unauthorized QR")
        self.assertEqual(len(main.access_logs), 1, "One log entry should be added")

        log_entry = main.access_logs[0]
        self.assertIsInstance(log_entry, main.AccessLogEntry)
        self.assertFalse(log_entry.access_granted)
        self.assertEqual(log_entry.qr_data, qr_denegado)

    def test_check_access_multiple_logs(self):
        qr_permitido = "TEST_QR_PERMITIDO_2"
        qr_denegado = "TEST_QR_DENEGADO_ABC"

        main.check_access(qr_permitido)
        main.check_access(qr_denegado)
        main.check_access(qr_permitido)

        self.assertEqual(len(main.access_logs), 3, "Should have three log entries")
        self.assertTrue(main.access_logs[0].access_granted)
        self.assertFalse(main.access_logs[1].access_granted)
        self.assertTrue(main.access_logs[2].access_granted)
        self.assertEqual(main.access_logs[0].qr_data, qr_permitido)
        self.assertEqual(main.access_logs[1].qr_data, qr_denegado)


if __name__ == '__main__':
    unittest.main()
