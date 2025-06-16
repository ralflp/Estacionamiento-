import unittest
import os
from qr_utils import generate_qr, scan_qr
# Necesitarás Pillow para crear una imagen falsa para una de las pruebas de escaneo
from PIL import Image

class TestQRUtils(unittest.TestCase):

    def tearDown(self):
        # Limpiar archivos creados durante las pruebas
        # Usar una lista más específica basada en los archivos que realmente se usan.
        files_to_remove = ["test_qr.png", "test_qr_ret.png", "generated_for_scan_test.png", "dummy_image.png"]
        for f in files_to_remove:
            if os.path.exists(f):
                os.remove(f)

    def test_generate_qr_creates_file(self):
        filename = "test_qr.png"
        # Asegurarse que el archivo no existe antes de la prueba
        if os.path.exists(filename):
            os.remove(filename)
        self.assertTrue(generate_qr("test_data", filename), "generate_qr should return True on success")
        self.assertTrue(os.path.exists(filename), f"File {filename} was not created")
        # Limpieza se hará en tearDown, pero se puede hacer aquí si se prefiere aislamiento total

    def test_generate_qr_returns_true(self):
        filename = "test_qr_ret.png"
         # Asegurarse que el archivo no existe antes de la prueba
        if os.path.exists(filename):
            os.remove(filename)
        self.assertTrue(generate_qr("test_data_ret", filename), "generate_qr should return True on success")
        # Limpieza se hará en tearDown

    def test_scan_qr_reads_correct_data(self):
        filename = "generated_for_scan_test.png"
        test_data = "scan_me_123_!@#"
        # Asegurarse que el archivo no existe antes de la prueba
        if os.path.exists(filename):
            os.remove(filename)

        self.assertTrue(generate_qr(test_data, filename), "Failed to generate QR for scan test")
        self.assertEqual(scan_qr(filename), test_data, "Scanned data does not match original data")
        # Limpieza se hará en tearDown

    def test_scan_qr_non_existent_file(self):
        # scan_qr debería imprimir un error pero retornar None
        self.assertIsNone(scan_qr("non_existent_qr_image_file_123.png"), "scan_qr should return None for non-existent files")

    def test_scan_qr_not_a_qr_image(self):
        filename = "dummy_image.png"
        # Asegurarse que el archivo no existe antes de la prueba
        if os.path.exists(filename):
            os.remove(filename)

        try:
            # Crear una imagen falsa que no sea un QR
            img = Image.new('RGB', (100, 100), color = 'blue')
            img.save(filename)

            # scan_qr debería imprimir un error pero retornar None
            self.assertIsNone(scan_qr(filename), "scan_qr should return None for an image that is not a QR code")
        finally:
            # Limpieza específica aquí o confiar en tearDown. Hacerlo aquí es más robusto si setUp/tearDown fallan.
            if os.path.exists(filename):
                os.remove(filename)

if __name__ == '__main__':
    unittest.main()
