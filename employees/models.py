from django.db import models
from django.contrib.auth.models import User


class Employee(models.Model):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('editor', 'Editor'),
        ('viewer', 'Viewer'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    full_name = models.CharField(max_length=150)
    employee_id = models.CharField(max_length=50, unique=True)
    email = models.EmailField(unique=True)
    department = models.CharField(max_length=100)

    registration_method = models.CharField(max_length=20)  # manual / mykad
    ic_number = models.CharField(max_length=20, null=True, blank=True)

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class Event(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    date = models.DateField()
    description = models.TextField(null=True, blank=True)

    visitor_qr_code = models.ImageField(upload_to='qr_codes/', null=True, blank=True)
    staff_qr_code = models.ImageField(upload_to='qr_codes/', null=True, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_meter = models.PositiveIntegerField(default=100)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Attendance(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)

    full_name = models.CharField(max_length=150)
    employee_id = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    department = models.CharField(max_length=100)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        unique_together = ('employee_id', 'event')

    def __str__(self):
        return f"{self.full_name} - {self.event}"


class Visitor(models.Model):
    full_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    organization = models.CharField(max_length=150)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class VisitorAttendance(models.Model):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        unique_together = ('visitor', 'event')

    def __str__(self):
        return f"{self.visitor} - {self.event}"