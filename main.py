# main.py
from qr_utils import generate_qr, scan_qr
from datetime import datetime

class AccessLogEntry:
    def __init__(self, qr_data, access_granted, event_type="acceso_general", user_id=None):
        self.timestamp = datetime.now()
        self.qr_data = qr_data
        self.access_granted = access_granted
        self.event_type = event_type
        self.user_id = user_id

    def __repr__(self):
        access_status = 'Permitido' if self.access_granted else 'Denegado'
        user_display = self.user_id or 'N/A'
        return (f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"QR: {self.qr_data}, Acceso: {access_status}, "
                f"Evento: {self.event_type}, Usuario: {user_display}")

# Lista simulada de QRs autorizados (podría estar en una base de datos o configuración)
AUTORIZADOS_QRS = ["PARKING_SPOT_A1", "ID_USUARIO_12345_TEST_SCAN", "ACCESO_PUERTA_PRINCIPAL"]
access_logs = [] # Nueva lista para almacenar los registros

def check_access(qr_data):
    """
    Verifica si los datos del QR escaneado conceden acceso y registra el evento.
    """
    access_granted_status = False # Asumir denegado inicialmente
    if qr_data in AUTORIZADOS_QRS:
        print(f"Acceso PERMITIDO para: {qr_data}")
        access_granted_status = True
    else:
        print(f"Acceso DENEGADO para: {qr_data}")
        access_granted_status = False # Ya está así, pero explícito por claridad

    # Crear y almacenar el registro del evento de acceso
    log_entry = AccessLogEntry(qr_data=qr_data, access_granted=access_granted_status)
    access_logs.append(log_entry)
    # Opcionalmente, imprimir una confirmación de que se añadió el log (para depuración)
    # print(f"Registro añadido: {log_entry}")

    return access_granted_status

def main_cli():
    """
    Función principal para la interfaz de línea de comandos interactiva.
    """
    print("Aplicación de Control de Acceso Interactiva")

    while True:
        print("\nSeleccione una opción:")
        print("1. Generar Código QR")
        print("2. Escanear Código QR y Verificar Acceso")
        print("3. Ver Registros de Acceso")
        print("4. Salir")

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
                check_access(qr_data) # Esta llamada ahora también creará un log
            else:
                # Mensaje ya impreso por scan_qr si no se encuentran datos o hay error
                pass
        elif opcion == '3':
            if not access_logs:
                print("No hay registros de acceso todavía.")
            else:
                print("\n--- Registros de Acceso ---")
                for log_entry in access_logs:
                    print(log_entry) # __repr__ de AccessLogEntry se usa aquí
                print("---------------------------")
        elif opcion == '4':
            print("Saliendo de la aplicación.")
            break
        else:
            print("Opción no válida. Por favor, intente de nuevo.")

if __name__ == "__main__":
    # Los ejemplos anteriores de ejecución automática se eliminan
    # para dar paso a la CLI interactiva.
    main_cli()
