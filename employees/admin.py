from django.contrib import admin
from .models import (
    Employee,
    Event,
    Attendance,
    Visitor,
    VisitorAttendance,
    PassportVisitor,
    PassportAttendance,
    EventAssignment,
    AssignmentAttendance,
)

admin.site.register(Employee)
admin.site.register(Event)
admin.site.register(Attendance)
admin.site.register(Visitor)
admin.site.register(VisitorAttendance)
admin.site.register(PassportVisitor)
admin.site.register(PassportAttendance)
admin.site.register(EventAssignment)
admin.site.register(AssignmentAttendance)