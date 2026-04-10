from django.urls import path
from .views import (
    add_employee,
    analytics_page,
    event_detail,
    export_attendance_csv,
    export_event_summary_csv,
    passport_attendance_page,
    register_manual,
    register_page,
    login_user,
    login_page,
    dashboard,
    logout_user,
    employees_page,
    delete_employee,
    staff_attendance_page,
    submit_staff_attendance,
    update_employee,
    create_event,
    events_page,
    update_event,
    delete_event,
    upload_passport,
    submit_passport_attendance,
    visitor_attendance_page,
    submit_visitor_attendance,
    update_staff_attendance,
    delete_staff_attendance,
    update_visitor_attendance,
    delete_visitor_attendance,
    update_passport_attendance,
    delete_passport_attendance,
)

urlpatterns = [
    path('register/manual/', register_manual),
    path('register/', register_page),

    path('login/', login_user),
    path('login-page/', login_page),
    path('logout/', logout_user),

    path('dashboard/', dashboard),
    path('analytics/', analytics_page),
    path('dashboard/export-event-summary/<int:id>/', export_event_summary_csv),

    path('employees/', employees_page),
    path('add/', add_employee),
    path('delete/<int:id>/', delete_employee),
    path('update/<int:id>/', update_employee),

    path('events/', events_page),
    path('events/<int:id>/', event_detail),
    path('events/<int:id>/export/', export_attendance_csv),

    path('event/create/', create_event),
    path('event/update/<int:id>/', update_event),
    path('event/delete/<int:id>/', delete_event),

    path('visitor-attendance/<int:event_id>/', visitor_attendance_page),
    path('visitor-attendance/submit/<int:event_id>/', submit_visitor_attendance),
    path('visitor-attendance/update/<int:id>/', update_visitor_attendance),
    path('visitor-attendance/delete/<int:id>/', delete_visitor_attendance),

    path('staff-attendance/<int:event_id>/', staff_attendance_page),
    path('staff-attendance/submit/<int:event_id>/', submit_staff_attendance),
    path('staff-attendance/update/<int:id>/', update_staff_attendance),
    path('staff-attendance/delete/<int:id>/', delete_staff_attendance),

    path('passport-attendance/<int:event_id>/', passport_attendance_page),
    path('passport/upload/', upload_passport),
    path('passport/submit/<int:event_id>/', submit_passport_attendance),

    path('passport-attendance/update/<int:id>/', update_passport_attendance),
    path('passport-attendance/delete/<int:id>/', delete_passport_attendance),
]