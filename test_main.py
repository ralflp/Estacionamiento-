import unittest
from datetime import datetime
import os
import main # Importar el módulo principal

class TestMainApp(unittest.TestCase):

    # Usar un nombre de archivo de prueba específico para QRs autorizados
    TEST_AUTORIZADOS_QRS_FILE = "test_autorizados_qrs.txt"
    # Guardar la ruta original del archivo de QRs para restaurarla después
    ORIGINAL_AUTORIZADOS_QRS_FILE = main.AUTORIZADOS_QRS_FILE

    @classmethod
    def setUpClass(cls):
        # Cambiar globalmente el archivo que usará main.py para las pruebas
        main.AUTORIZADOS_QRS_FILE = cls.TEST_AUTORIZADOS_QRS_FILE

    @classmethod
    def tearDownClass(cls):
        # Restaurar la ruta original del archivo de QRs
        main.AUTORIZADOS_QRS_FILE = cls.ORIGINAL_AUTORIZADOS_QRS_FILE

    def setUp(self):
        # Limpiar la lista global de logs antes de cada prueba
        main.access_logs.clear()
        # Limpiar la lista de QRs en memoria
        main.AUTORIZADOS_QRS.clear()
        # Asegurarse de que el archivo de QRs de prueba no exista al inicio de cada test,
        # para que cada prueba comience en un estado limpio.
        if os.path.exists(self.TEST_AUTORIZADOS_QRS_FILE):
            os.remove(self.TEST_AUTORIZADOS_QRS_FILE)
        # Crear un archivo vacío para algunas pruebas, o dejar que cargar_qrs_autorizados() lo maneje
        open(self.TEST_AUTORIZADOS_QRS_FILE, 'w').close()


    def tearDown(self):
        # Limpiar el archivo de QRs de prueba después de cada test
        if os.path.exists(self.TEST_AUTORIZADOS_QRS_FILE):
            os.remove(self.TEST_AUTORIZADOS_QRS_FILE)

    # --- Pruebas para AccessLogEntry (sin cambios, ya eran robustas) ---
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
        # ... (resto de aserciones de repr sin cambios)
        self.assertRegex(repr_permitido, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


    # --- Pruebas para cargar_qrs_autorizados ---
    def test_cargar_qrs_autorizados_archivo_vacio(self):
        main.cargar_qrs_autorizados()
        self.assertEqual(len(main.AUTORIZADOS_QRS), 0, "Debería haber 0 QRs si el archivo está vacío.")

    def test_cargar_qrs_autorizados_con_datos(self):
        qrs_de_prueba = ["QR1", "QR2_COMPLEJO", "QR3 CON ESPACIOS"]
        with open(self.TEST_AUTORIZADOS_QRS_FILE, 'w') as f:
            for qr in qrs_de_prueba:
                f.write(qr + "\n")

        main.cargar_qrs_autorizados()
        self.assertEqual(len(main.AUTORIZADOS_QRS), len(qrs_de_prueba))
        for qr in qrs_de_prueba:
            self.assertIn(qr, main.AUTORIZADOS_QRS)

    def test_cargar_qrs_autorizados_archivo_no_existente(self):
        if os.path.exists(self.TEST_AUTORIZADOS_QRS_FILE):
            os.remove(self.TEST_AUTORIZADOS_QRS_FILE) # Asegurar que no existe
        main.cargar_qrs_autorizados() # No debería lanzar error, solo imprimir mensaje
        self.assertEqual(len(main.AUTORIZADOS_QRS), 0)


    # --- Pruebas para guardar_qr_autorizado ---
    def test_guardar_qr_autorizado_nuevo_qr(self):
        qr_nuevo = "NUEVO_QR_GUARDADO"
        self.assertTrue(main.guardar_qr_autorizado(qr_nuevo), "Debería retornar True para un QR nuevo.")
        self.assertIn(qr_nuevo, main.AUTORIZADOS_QRS)
        # Verificar que se guardó en el archivo
        with open(self.TEST_AUTORIZADOS_QRS_FILE, 'r') as f:
            content = f.read()
            self.assertIn(qr_nuevo, content)

    def test_guardar_qr_autorizado_qr_existente(self):
        qr_existente = "QR_YA_EXISTE"
        # Guardarlo una vez
        main.guardar_qr_autorizado(qr_existente)
        num_qrs_antes = len(main.AUTORIZADOS_QRS)
        # Intentar guardarlo de nuevo
        self.assertFalse(main.guardar_qr_autorizado(qr_existente), "Debería retornar False para un QR existente.")
        self.assertEqual(len(main.AUTORIZADOS_QRS), num_qrs_antes, "No debería añadir un QR duplicado a la lista.")
        # Verificar que no se duplicó en el archivo (contando líneas)
        with open(self.TEST_AUTORIZADOS_QRS_FILE, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), num_qrs_antes) # Asumiendo 1 QR por línea


    # --- Pruebas para check_access (ahora dependen de la carga/guardado) ---
    def test_check_access_permitido_desde_archivo(self):
        qr_permitido = "QR_PERMITIDO_EN_ARCHIVO"
        main.guardar_qr_autorizado(qr_permitido) # Esto lo guarda en el archivo de prueba

        # Limpiar AUTORIZADOS_QRS en memoria y recargar desde archivo para simular inicio de app
        main.AUTORIZADOS_QRS.clear()
        main.cargar_qrs_autorizados()

        result = main.check_access(qr_permitido)
        self.assertTrue(result, "check_access debería permitir un QR cargado desde archivo.")
        self.assertEqual(len(main.access_logs), 1)
        self.assertTrue(main.access_logs[0].access_granted)
        self.assertEqual(main.access_logs[0].qr_data, qr_permitido)

    def test_check_access_denegado_no_en_archivo(self):
        qr_denegado = "QR_DENEGADO_NO_EXISTE"
        # Asegurarse de que AUTORIZADOS_QRS está vacío o no contiene este QR
        main.cargar_qrs_autorizados() # Carga desde archivo vacío o sin este QR

        result = main.check_access(qr_denegado)
        self.assertFalse(result, "check_access debería denegar un QR no existente en archivo.")
        self.assertEqual(len(main.access_logs), 1)
        self.assertFalse(main.access_logs[0].access_granted)

    def test_check_access_multiple_logs_con_archivo(self):
        qr_p1 = "QR_P_UNO"
        qr_p2 = "QR_P_DOS"
        qr_d1 = "QR_D_UNO"

        main.guardar_qr_autorizado(qr_p1)
        main.guardar_qr_autorizado(qr_p2)

        # Recargar para asegurar que solo los guardados están
        main.AUTORIZADOS_QRS.clear()
        main.cargar_qrs_autorizados()

        main.check_access(qr_p1)
        main.check_access(qr_d1)
        main.check_access(qr_p2)

        self.assertEqual(len(main.access_logs), 3)
        self.assertTrue(main.access_logs[0].access_granted) # qr_p1
        self.assertFalse(main.access_logs[1].access_granted) # qr_d1
        self.assertTrue(main.access_logs[2].access_granted) # qr_p2
        self.assertEqual(main.access_logs[0].qr_data, qr_p1)
        self.assertEqual(main.access_logs[1].qr_data, qr_d1)


if __name__ == '__main__':
    unittest.main()
