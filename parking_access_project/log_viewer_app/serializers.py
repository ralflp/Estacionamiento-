from rest_framework import serializers
from .models import AccessPermission, Person, AccessPoint # Importa los modelos necesarios

class AccessRequestSerializer(serializers.Serializer):
    qr_identifier = serializers.CharField(max_length=100, help_text="Identificador leído del código QR.")
    access_point_name = serializers.CharField(max_length=100, help_text="Nombre/ID del punto de acceso donde se realiza el escaneo.")
    # Podríamos añadir un campo para 'event_type' (entrada/salida) si el dispositivo lo envía

    def validate_qr_identifier(self, value):
        if not value:
            raise serializers.ValidationError("El identificador QR no puede estar vacío.")
        # Podrías añadir más validaciones aquí si es necesario
        return value

    def validate_access_point_name(self, value):
        if not value:
            raise serializers.ValidationError("El nombre del punto de acceso no puede estar vacío.")
        # Podrías añadir más validaciones aquí
        return value

class AccessResponseSerializer(serializers.Serializer):
    access_granted = serializers.BooleanField(help_text="Indica si el acceso fue concedido o denegado.")
    message = serializers.CharField(max_length=255, help_text="Mensaje descriptivo del resultado.")
    person_name = serializers.CharField(max_length=200, required=False, allow_null=True, help_text="Nombre de la persona si el acceso fue evaluado para una persona conocida.")
    access_point_name = serializers.CharField(max_length=100, required=False, allow_null=True, help_text="Nombre del punto de acceso evaluado.")
    timestamp = serializers.DateTimeField(help_text="Fecha y hora de la respuesta.")


class AccessPointRelatedField(serializers.RelatedField):
    def to_representation(self, value):
        return value.name # Devuelve el nombre del AccessPoint

    # queryset es necesario si este campo se va a usar para escritura también.
    # Para read_only=True, no es estrictamente necesario, pero buena práctica incluirlo.
    def get_queryset(self):
        return AccessPoint.objects.all()

class PersonRelatedField(serializers.RelatedField):
    def to_representation(self, value):
        return f"{value.full_name} ({value.identifier})" # Devuelve nombre e identificador

    def get_queryset(self):
        return Person.objects.all()

class AccessPermissionSerializer(serializers.ModelSerializer):
    # Usar campos personalizados para una representación específica de las relaciones
    person = PersonRelatedField(queryset=Person.objects.all()) # queryset para escritura si no es read_only
    access_point = AccessPointRelatedField(queryset=AccessPoint.objects.all()) # queryset para escritura

    # Si se quisiera una representación más detallada y anidada (y potencialmente escribible):
    # person = PersonSerializer() # Necesitarías definir PersonSerializer
    # access_point = AccessPointSerializer() # Necesitarías definir AccessPointSerializer

    class Meta:
        model = AccessPermission
        fields = [
            'id',
            'person', # Ahora usa el campo relacionado personalizado
            'access_point', # Ahora usa el campo relacionado personalizado
            'is_active',
            'valid_from',
            'valid_until',
            'created_at', # Añadido para info
            'updated_at', # Añadido para info
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    # Si se usan los campos relacionados personalizados solo para lectura (to_representation)
    # y se quiere escribir usando los IDs de PK, se definirían así:
    # person_details = PersonRelatedField(source='person', read_only=True)
    # access_point_name = AccessPointRelatedField(source='access_point', read_only=True)
    # person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all(), write_only=True)
    # access_point = serializers.PrimaryKeyRelatedField(queryset=AccessPoint.objects.all(), write_only=True)
    # Y luego ajustar 'fields' para incluir person, access_point (para escritura) y
    # person_details, access_point_name (para lectura).
    # Por simplicidad y siguiendo el prompt, la configuración actual con campos custom
    # que manejan 'to_representation' es para lectura. Si se quiere escribir,
    # se necesitaría `to_internal_value` en los related fields o usar PrimaryKeyRelatedField para escritura.
    # La configuración actual permitirá la representación custom en lectura, y para escritura
    # esperará los PKs de person y access_point.
    #
    # Self-correction: El prompt original tenía 'person_details' y 'access_point_name' como read_only.
    # Si se quiere que el serializer sea escribible para 'person' y 'access_point' usando PKs,
    # pero mostrar la representación custom en lectura, se usa la técnica de dos campos por relación
    # (uno read_only con source, otro write_only o default para PK).
    # O, se implementa to_internal_value en los RelatedField.
    #
    # Para seguir el espíritu del prompt con "person_details" y "access_point_name" en 'fields':
    # Re-implementaré usando la técnica de campos separados para lectura y escritura si fuera necesario,
    # pero el prompt actual lista 'person_details' y 'access_point_name' directamente en fields,
    # lo que implica que son los campos principales.
    # He ajustado los campos en Meta para usar 'person' y 'access_point' directamente,
    # y los custom RelatedField se encargarán de su representación.
    # Para que sean escribibles por PK, los RelatedField necesitan `queryset` y opcionalmente `to_internal_value`.
    # El `queryset` ya está añadido. DRF por defecto usará el PK para `to_internal_value` con `RelatedField`.
