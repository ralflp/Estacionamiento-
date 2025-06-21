# qr_utils.py
import qrcode
from PIL import Image

def generate_qr(data, filename="qr_code.png"):
    """
    Genera un código QR con los datos proporcionados y lo guarda en un archivo.
    """
    try:
        img = qrcode.make(data)
        img.save(filename)
        print(f"QR generado y guardado como {filename}")
        return True
    except Exception as e:
        print(f"Error al generar QR: {e}")
        return False

from pyzbar.pyzbar import decode as pyzbar_decode

def scan_qr(image_path):
    """
    Escanea una imagen en busca de un código QR y devuelve los datos decodificados.
    """
    try:
        img = Image.open(image_path)
        decoded_objects = pyzbar_decode(img)

        if decoded_objects:
            # Devuelve los datos del primer QR encontrado
            data = decoded_objects[0].data.decode('utf-8')
            print(f"QR escaneado con éxito: {data}")
            return data
        else:
            print("No se encontraron códigos QR en la imagen.")
            return None
    except FileNotFoundError:
        print(f"Error: El archivo de imagen no fue encontrado en '{image_path}'")
        return None
    except Exception as e:
        print(f"Error al escanear QR: {e}")
        return None
