from django.db import models

class AccessLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    qr_data = models.CharField(max_length=255)
    access_granted = models.BooleanField()
    event_type = models.CharField(max_length=100, default="acceso_general")
    user_id = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] QR: {self.qr_data}, Acceso: {'Permitido' if self.access_granted else 'Denegado'}"
