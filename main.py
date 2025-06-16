# main.py
from qr_utils import generate_qr, scan_qr

# Lista simulada de QRs autorizados (podría estar en una base de datos o configuración)
AUTORIZADOS_QRS = ["PARKING_SPOT_A1", "ID_USUARIO_12345_TEST_SCAN", "ACCESO_PUERTA_PRINCIPAL"]

def check_access(qr_data):
    """
    Verifica si los datos del QR escaneado conceden acceso.
    """
    if qr_data in AUTORIZADOS_QRS:
        print(f"Acceso PERMITIDO para: {qr_data}")
        return True
    else:
        print(f"Acceso DENEGADO para: {qr_data}")
        return False

def main_cli():
    """
    Función principal para la interfaz de línea de comandos interactiva.
    """
    print("Aplicación de Control de Acceso Interactiva")

    while True:
        print("\nSeleccione una opción:")
        print("1. Generar Código QR")
        print("2. Escanear Código QR y Verificar Acceso")
        print("3. Salir")

        opcion = input("Opción: ")

        if opcion == '1':
            data = input("Ingrese los datos para el QR: ")
            filename = input("Ingrese el nombre del archivo para guardar el QR (ej: nuevo_qr.png): ")
            if generate_qr(data, filename):
                # Mensaje ya impreso por generate_qr
                pass
            else:
                # Mensaje ya impreso por generate_qr en caso de error
                pass
        elif opcion == '2':
            image_path = input("Ingrese la ruta del archivo de imagen QR a escanear: ")
            qr_data = scan_qr(image_path)
            if qr_data:
                print(f"Datos recuperados del QR '{image_path}': {qr_data}")
                check_access(qr_data)
            else:
                # Mensaje ya impreso por scan_qr si no se encuentran datos o hay error
                pass
        elif opcion == '3':
            print("Saliendo de la aplicación.")
            break
        else:
            print("Opción no válida. Por favor, intente de nuevo.")

if __name__ == "__main__":
    # Los ejemplos anteriores de ejecución automática se eliminan
    # para dar paso a la CLI interactiva.
    main_cli()
