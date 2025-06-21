import unittest
import os
from qr_utils import generate_qr, scan_qr
# PIL (Pillow) es necesario para crear imágenes dummy y es usado por qr_utils internamente.
from PIL import Image

class TestQRUtils(unittest.TestCase):

    # Nombres de archivo de prueba definidos como variables de clase para consistencia
    test_qr_filename = "test_qr_image_generated.png"
    dummy_image_filename = "dummy_non_qr_image.png"

    def setUp(self):
        # Asegurar que los archivos de prueba no existan antes de cada prueba
        self.remove_test_files()

    def tearDown(self):
        # Limpiar archivos creados durante las pruebas después de cada prueba
        self.remove_test_files()

    def remove_test_files(self):
        files_to_remove = [self.test_qr_filename, self.dummy_image_filename]
        for f in files_to_remove:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError as e:
                    # Imprimir error si la eliminación falla, pero no detener las pruebas
                    print(f"Advertencia: No se pudo eliminar el archivo de prueba {f}: {e}")

    def test_generate_qr_creates_file_and_returns_true(self):
        """
        Prueba que generate_qr crea un archivo y retorna True en caso de éxito.
        """
        data_to_encode = "test_data_for_generation"
        self.assertTrue(generate_qr(data_to_encode, self.test_qr_filename),
                        "generate_qr should return True on successful generation.")
        self.assertTrue(os.path.exists(self.test_qr_filename),
                        f"El archivo QR '{self.test_qr_filename}' no fue creado por generate_qr.")

    def test_scan_qr_reads_correct_data_from_generated_qr(self):
        """
        Prueba que scan_qr lee correctamente los datos de un QR generado por generate_qr.
        """
        original_data = "test_data_for_scanning_123!@#XYZ"

        # 1. Generar el código QR
        self.assertTrue(generate_qr(original_data, self.test_qr_filename),
                        "Fallo al generar QR para la prueba de escaneo.")
        self.assertTrue(os.path.exists(self.test_qr_filename),
                        "El archivo QR no fue creado para la prueba de escaneo.")

        # 2. Escanear el código QR y verificar los datos
        scanned_data = scan_qr(self.test_qr_filename)
        self.assertEqual(scanned_data, original_data,
                         "Los datos escaneados no coinciden con los datos originales.")

    def test_scan_qr_non_existent_file_returns_none(self):
        """
        Prueba que scan_qr retorna None cuando el archivo de imagen no existe.
        """
        non_existent_filename = "this_qr_image_definitely_does_not_exist.png"
        # Asegurarse de que realmente no existe, por si acaso
        if os.path.exists(non_existent_filename):
            os.remove(non_existent_filename)

        self.assertIsNone(scan_qr(non_existent_filename),
                          "scan_qr should return None for a non-existent file.")

    def test_scan_qr_not_a_qr_image_returns_none(self):
        """
        Prueba que scan_qr retorna None cuando la imagen no es un QR o no contiene uno.
        """
        try:
            # Crear una imagen dummy que definitivamente no es un QR (ej. una imagen completamente azul)
            img = Image.new('RGB', (100, 100), color='blue')
            img.save(self.dummy_image_filename)

            self.assertIsNone(scan_qr(self.dummy_image_filename),
                              "scan_qr should return None for an image that is not a valid QR code or contains no QR.")
        finally:
            # La limpieza se hace en tearDown, pero por si acaso algo falla antes.
            if os.path.exists(self.dummy_image_filename):
                os.remove(self.dummy_image_filename)

    def test_generate_qr_handles_failure(self):
        """
        Prueba que generate_qr retorna False si no puede crear el archivo
        (ej. por permisos, aunque esto es difícil de simular directamente sin afectar el entorno).
        Aquí probamos con un nombre de archivo inválido que podría causar un error.
        """
        # Un nombre de archivo que probablemente cause un error en la mayoría de los OS
        # al intentar crear un directorio y archivo al mismo tiempo sin que el directorio exista.
        # Nota: Esto podría no fallar en todos los OS o configuraciones de la misma manera.
        # Una prueba más robusta requeriría mockear 'qrcode.make' o 'img.save' para lanzar una excepción.
        invalid_filename = "/non_existent_directory/test.png"
        self.assertFalse(generate_qr("test_data", invalid_filename),
                         "generate_qr should return False when file saving fails.")

if __name__ == '__main__':
    unittest.main()
