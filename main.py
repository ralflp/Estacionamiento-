# main.py
from datetime import datetime
import os

# Variables globales
AUTORIZADOS_QRS_FILE = "autorizados_qrs.txt"
AUTORIZADOS_QRS = []
access_logs = []

class AccessLogEntry:
    def __init__(self, qr_data, access_granted, event_type="acceso_general", user_id=None, timestamp=None):
        self.timestamp = timestamp or datetime.now()
        self.qr_data = qr_data
        self.access_granted = access_granted
        self.event_type = event_type
        self.user_id = user_id

    def __repr__(self):
        status = "Permitido" if self.access_granted else "Denegado"
        user_info = f"Usuario: {self.user_id}" if self.user_id else "Usuario: N/A"
        event_info = f"Evento: {self.event_type}"
        return (f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"QR: '{self.qr_data}', Estado: {status}, {user_info}, {event_info}")

def cargar_qrs_autorizados():
    """
    Carga los QRs autorizados desde AUTORIZADOS_QRS_FILE a la lista global AUTORIZADOS_QRS.
    """
    global AUTORIZADOS_QRS
    AUTORIZADOS_QRS = [] # Limpiar la lista antes de cargar para evitar duplicados si se llama múltiples veces
    if not os.path.exists(AUTORIZADOS_QRS_FILE):
        print(f"Archivo de QRs autorizados '{AUTORIZADOS_QRS_FILE}' no encontrado. Se iniciará con una lista vacía.")
        return
    try:
        with open(AUTORIZADOS_QRS_FILE, 'r') as f:
            for line in f:
                qr = line.strip()
                if qr: # Asegurarse de no añadir líneas vacías
                    AUTORIZADOS_QRS.append(qr)
        print(f"QRs autorizados cargados desde '{AUTORIZADOS_QRS_FILE}'. Total: {len(AUTORIZADOS_QRS)}")
    except IOError as e:
        print(f"Error al leer el archivo de QRs autorizados '{AUTORIZADOS_QRS_FILE}': {e}")

def guardar_qr_autorizado(qr_data):
    """
    Añade un nuevo QR a la lista AUTORIZADOS_QRS y actualiza el archivo AUTORIZADOS_QRS_FILE.
    Retorna True si el QR fue añadido (nuevo), False si ya existía.
    """
    global AUTORIZADOS_QRS
    if qr_data not in AUTORIZADOS_QRS:
        AUTORIZADOS_QRS.append(qr_data)
        try:
            # Reescribir el archivo con la lista actualizada
            with open(AUTORIZADOS_QRS_FILE, 'w') as f:
                for qr in AUTORIZADOS_QRS:
                    f.write(qr + "\n")
            print(f"QR '{qr_data}' añadido y lista guardada en '{AUTORIZADOS_QRS_FILE}'.")
            return True
        except IOError as e:
            print(f"Error al guardar la lista de QRs autorizados en '{AUTORIZADOS_QRS_FILE}': {e}")
            # Opcional: revertir la adición a la lista en memoria si falla el guardado
            # AUTORIZADOS_QRS.remove(qr_data)
            return False # Indicar que no se pudo guardar aunque se añadió a memoria.
    else:
        print(f"QR '{qr_data}' ya está en la lista de autorizados.")
        return False # Ya existía

def check_access(qr_data, event_type="acceso_general", user_id=None):
    """
    Verifica si el qr_data está en la lista de AUTORIZADOS_QRS.
    Registra el intento de acceso en access_logs.
    Retorna True si el acceso es permitido, False en caso contrario.
    """
    access_granted = qr_data in AUTORIZADOS_QRS
    log_entry = AccessLogEntry(qr_data, access_granted, event_type=event_type, user_id=user_id)
    access_logs.append(log_entry)

    if access_granted:
        print(f"Acceso PERMITIDO para QR: '{qr_data}'")
    else:
        print(f"Acceso DENEGADO para QR: '{qr_data}'")
    return access_granted

def main_app_placeholder(): # Renombrada para evitar conflicto con la función main de prueba si se importara todo
    print("Aplicación de Control de Acceso (Aún no implementada la interfaz principal)")
    # Cargar QRs al inicio (esto se moverá al bucle principal en el siguiente paso)
    # cargar_qrs_autorizados()

# Importar funciones de qr_utils
import qr_utils

def mostrar_menu():
    print("\n--- Sistema de Control de Acceso a Estacionamiento ---")
    print("1. Generar QR para nuevo usuario/vehículo")
    print("2. Simular entrada de vehículo (Escanear QR)")
    print("3. Ver logs de acceso")
    print("4. Ver QRs Autorizados")
    print("5. Salir")
    return input("Seleccione una opción: ")

def main():
    cargar_qrs_autorizados()

    while True:
        opcion = mostrar_menu()

        if opcion == '1':
            qr_data = input("Ingrese los datos para el QR (ej. ID de usuario/vehículo): ")
            if not qr_data:
                print("Los datos para el QR no pueden estar vacíos.")
                continue

            filename_suggestion = f"qr_{qr_data.replace(' ', '_')}.png"
            filename = input(f"Ingrese el nombre del archivo para guardar el QR (ej. {filename_suggestion}): ")
            if not filename:
                filename = filename_suggestion # Usar sugerencia si no se ingresa nada

            if qr_utils.generate_qr(qr_data, filename):
                print(f"QR generado como '{filename}'.")
                if guardar_qr_autorizado(qr_data):
                    print(f"QR '{qr_data}' añadido a la lista de autorizados.")
                else:
                    # Ya estaba autorizado o hubo un error al guardar, guardar_qr_autorizado ya imprimió el mensaje.
                    pass
            else:
                print("Fallo al generar el código QR.")

        elif opcion == '2':
            image_path = input("Ingrese la ruta de la imagen del QR a escanear: ")
            if not os.path.exists(image_path):
                print(f"Error: El archivo '{image_path}' no fue encontrado.")
                continue

            datos_qr_escaneado = qr_utils.scan_qr(image_path)
            if datos_qr_escaneado:
                check_access(datos_qr_escaneado)
            else:
                print("No se pudo obtener datos del QR escaneado o el QR no es válido.")

        elif opcion == '3':
            print("\n--- Logs de Acceso ---")
            if not access_logs:
                print("No hay logs de acceso registrados.")
            else:
                for log in access_logs:
                    print(log)
            print("--------------------")

        elif opcion == '4':
            print("\n--- QRs Autorizados ---")
            if not AUTORIZADOS_QRS:
                print("No hay QRs autorizados actualmente.")
            else:
                for i, qr in enumerate(AUTORIZADOS_QRS):
                    print(f"{i+1}. {qr}")
            print("-----------------------")

        elif opcion == '5':
            print("Saliendo de la aplicación...")
            break
        else:
            print("Opción no válida. Por favor, intente de nuevo.")

if __name__ == "__main__":
    main()
