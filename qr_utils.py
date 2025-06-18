# qr_utils.py
import qrcode
"import cv2 # OpenCV para la lectura de imágenes y preprocesamiento si es necesario
from pyzbar.pyzbar import decode

def generate_qr(data, filename="qr_code.png"):
    """
    Genera un código QR con los datos proporcionados y lo guarda en un archivo.
    """
    try:
        img = qrcode.make(data)
        img.save(filename)
        print(f"Código QR generado y guardado como {filename}")
        return True
    except Exception as e:
        print(f"Error al generar el código QR: {e}")
        return False

def scan_qr(image_path):
    """
    Escanea un código QR desde una imagen y devuelve los datos decodificados.
    """
    try:
        # Cargar la imagen usando OpenCV
        img = cv2.imread(image_path)
        if img is None:
            print(f"Error: No se pudo cargar la imagen desde {image_path}")
            return None

        # Decodificar códigos QR en la imagen
        decoded_objects = decode(img)

        if decoded_objects:
            # Devolver los datos del primer código QR encontrado
            data = decoded_objects[0].data.decode("utf-8")
            print(f"Código QR escaneado con éxito. Datos: {data}")
            return data
        else:
            print(f"No se encontraron códigos QR en la imagen: {image_path}")
            return None
    except Exception as e:
        print(f"Error al escanear el código QR: {e}")
        return None

if __name__ == '__main__':
    # Ejemplo de uso para generación (ya existente)
    if generate_qr("ID_USUARIO_12345_TEST_SCAN", "test_scan_qr.png"):
        print("Ejemplo de QR generado para prueba de escaneo.")

        # Ejemplo de uso para escaneo
        print("\n--- Ejemplo de Escaneo de QR ---")
        datos_escaneados = scan_qr("test_scan_qr.png")
        if datos_escaneados:
            print(f"Datos recuperados del QR: {datos_escaneados}")
        else:
            print("No se pudieron obtener datos del QR escaneado.")
        print("------------------------------------")

    # Prueba con un QR que podría no existir para ver el manejo de errores
    print("\n--- Ejemplo de Escaneo de QR (archivo no existente) ---")
    scan_qr("qr_no_existente.png")
    print("-------------------------------------------------------")
