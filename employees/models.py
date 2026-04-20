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
    registration_method = models.CharField(max_length=20)
    ic_number = models.CharField(max_length=20, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='viewer')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name


class Event(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    description = models.TextField(null=True, blank=True)

    visitor_qr_code = models.ImageField(upload_to='qr_codes/', null=True, blank=True)
    staff_qr_code = models.ImageField(upload_to='qr_codes/', null=True, blank=True)
    passport_qr_code = models.ImageField(upload_to='qr_codes/', null=True, blank=True)

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

    ipv4_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
    ipv6_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv6')

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

    ipv4_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
    ipv6_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv6')

    class Meta:
        unique_together = ('visitor', 'event')

    def __str__(self):
        return f"{self.visitor} - {self.event}"


class PassportVisitor(models.Model):
    STATUS_CHOICES = [
        ('auto-extracted', 'Auto Extracted'),
        ('manually-corrected', 'Manually Corrected'),
        ('pending verification', 'Pending Verification'),
    ]

    full_name = models.CharField(max_length=150)
    passport_number = models.CharField(max_length=50, unique=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.CharField(max_length=50, null=True, blank=True)
    expiry_date = models.CharField(max_length=50, null=True, blank=True)
    gender = models.CharField(max_length=20, null=True, blank=True)

    extra_data = models.JSONField(default=dict, blank=True)

    image = models.ImageField(upload_to='passport_images/', null=True, blank=True)
    extracted_image = models.ImageField(upload_to='passport_processed/', null=True, blank=True)

    ocr_raw_text = models.TextField(null=True, blank=True)
    image_quality_note = models.CharField(max_length=255, null=True, blank=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending verification')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.passport_number})"

    def get_additional_fields(self):
        extra = self.extra_data or {}
        additional_fields = extra.get("additional_fields", [])
        if not isinstance(additional_fields, list):
            return []

        cleaned_fields = []
        for field in additional_fields:
            if not isinstance(field, dict):
                continue
            label = str(field.get("label", "")).strip()
            value = str(field.get("value", "")).strip()
            if label and value:
                cleaned_fields.append({
                    "label": label,
                    "value": value,
                })
        return cleaned_fields


class PassportAttendance(models.Model):
    passport_visitor = models.ForeignKey(PassportVisitor, on_delete=models.CASCADE)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    ipv4_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv4')
    ipv6_address = models.GenericIPAddressField(null=True, blank=True, protocol='IPv6')
    
    class Meta:
        unique_together = ('passport_visitor', 'event')

    def __str__(self):
        return f"{self.passport_visitor.full_name} - {self.event.name}"


# =========================
# NEW: EVENT STAFF ASSIGNMENT
# =========================
class EventAssignment(models.Model):
    STATUS_CHOICES = [
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='assignments'
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='event_assignments'
    )

    task_title = models.CharField(max_length=150)
    task_description = models.TextField(blank=True, null=True)
    assignment_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='assigned'
    )

    qr_code = models.ImageField(
        upload_to='assignment_qr_codes/',
        null=True,
        blank=True
    )

    assigned_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_assignments'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'employee', 'task_title'],
                name='unique_event_employee_task'
            )
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.task_title} ({self.event.name})"


class AssignmentAttendance(models.Model):
    assignment = models.OneToOneField(
        EventAssignment,
        on_delete=models.CASCADE,
        related_name='attendance'
    )

    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    notes = models.TextField(blank=True, null=True)

    ipv4_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        protocol='IPv4'
    )
    ipv6_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        protocol='IPv6'
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    date = models.DateField(auto_now_add=True)
    time = models.TimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.assignment.employee.full_name} - {self.assignment.task_title}"