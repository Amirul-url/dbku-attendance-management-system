from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Count
from .models import Employee, Event, Attendance, Visitor, VisitorAttendance
import json
import qrcode
from django.core.files import File
from io import BytesIO
import re
import csv
import math


NGROK_BASE_URL = "https://exospherical-kimberlie-unrefulgent.ngrok-free.dev"


def get_current_employee(request):
    if not request.user.is_authenticated:
        return None
    return Employee.objects.filter(user=request.user).first()


def is_admin_user(request):
    employee = get_current_employee(request)
    return bool(employee and employee.role == 'admin')


def is_editor_user(request):
    employee = get_current_employee(request)
    return bool(employee and employee.role == 'editor')


def can_manage_user(request):
    employee = get_current_employee(request)
    return bool(employee and employee.role in ['admin', 'editor'])


def role_context(request):
    current_employee = get_current_employee(request)
    return {
        'current_employee': current_employee,
        'is_admin': bool(current_employee and current_employee.role == 'admin'),
        'is_editor': bool(current_employee and current_employee.role == 'editor'),
        'is_viewer': bool(current_employee and current_employee.role == 'viewer'),
        'can_manage': bool(current_employee and current_employee.role in ['admin', 'editor']),
    }


def require_login_page(request):
    if not request.user.is_authenticated:
        return redirect('/login-page/')
    return None


def require_admin_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required'}, status=401)
    if not is_admin_user(request):
        return JsonResponse({'error': 'Only admin can perform this action'}, status=403)
    return None


def require_manage_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required'}, status=401)
    if not can_manage_user(request):
        return JsonResponse({'error': 'You do not have permission for this action'}, status=403)
    return None


def require_manage_page(request):
    if not request.user.is_authenticated:
        return redirect('/login-page/')
    if not can_manage_user(request):
        return HttpResponse('Forbidden', status=403)
    return None


@csrf_exempt
def register_manual(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            full_name = data.get('full_name')
            employee_id = data.get('employee_id')
            email = data.get('email')
            department = data.get('department')
            registration_method = data.get('registration_method', 'manual')
            password = data.get('password')
            confirm_password = data.get('confirm_password')

            if not full_name or not employee_id or not email or not department or not password or not confirm_password:
                return JsonResponse({'error': 'All fields are required'}, status=400)

            if password != confirm_password:
                return JsonResponse({'error': 'Password and confirm password do not match'}, status=400)

            if len(password) < 8:
                return JsonResponse({'error': 'Password must be at least 8 characters'}, status=400)

            if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
                return JsonResponse({'error': 'Password must contain letters and numbers'}, status=400)

            if User.objects.filter(username=employee_id).exists():
                return JsonResponse({'error': 'Employee ID already exists as login user'}, status=400)

            if Employee.objects.filter(employee_id=employee_id).exists():
                return JsonResponse({'error': 'Employee ID already exists'}, status=400)

            if Employee.objects.filter(email=email).exists():
                return JsonResponse({'error': 'Email already exists'}, status=400)

            user = User.objects.create_user(
                username=employee_id,
                email=email,
                password=password
            )

            Employee.objects.create(
                user=user,
                full_name=full_name,
                employee_id=employee_id,
                email=email,
                department=department,
                registration_method=registration_method,
                role='viewer'
            )

            return JsonResponse({'message': f'Employee registered via {registration_method}'})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


def register_page(request):
    return render(request, 'register.html')


@csrf_exempt
def login_user(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            identifier = data.get('username')
            password = data.get('password')

            if not identifier or not password:
                return JsonResponse({'error': 'Username/Email and password required'}, status=400)

            user = None

            if '@' in identifier:
                try:
                    user_obj = User.objects.get(email=identifier)
                    user = authenticate(request, username=user_obj.username, password=password)
                except User.DoesNotExist:
                    return JsonResponse({'error': 'User not found'}, status=404)
            else:
                user = authenticate(request, username=identifier, password=password)

            if user is not None:
                login(request, user)
                return JsonResponse({'message': 'Login successful'})
            else:
                return JsonResponse({'error': 'Invalid credentials'}, status=401)

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


def login_page(request):
    return render(request, 'login.html')


def logout_user(request):
    logout(request)
    return redirect('/login-page/')


def dashboard(request):
    login_check = require_login_page(request)
    if login_check:
        return login_check

    total_employees = Employee.objects.count()
    total_visitors = Visitor.objects.count()
    total_events = Event.objects.count()
    total_staff_attendance = Attendance.objects.count()
    total_visitor_attendance = VisitorAttendance.objects.count()
    total_attendance = total_staff_attendance + total_visitor_attendance

    context = {
        'total_employees': total_employees,
        'total_visitors': total_visitors,
        'total_events': total_events,
        'total_staff_attendance': total_staff_attendance,
        'total_visitor_attendance': total_visitor_attendance,
        'total_attendance': total_attendance,
    }
    context.update(role_context(request))

    return render(request, 'dashboard.html', context)


def analytics_page(request):
    login_check = require_login_page(request)
    if login_check:
        return login_check

    event_name = request.GET.get('name', '').strip()
    event_month = request.GET.get('month', '').strip()
    event_year = request.GET.get('year', '').strip()
    event_location = request.GET.get('location', '').strip()

    events = Event.objects.all().order_by('-date', '-id')

    if event_name:
        events = events.filter(name__icontains=event_name)

    if event_month:
        events = events.filter(date__month=event_month)

    if event_year:
        events = events.filter(date__year=event_year)

    if event_location:
        events = events.filter(location__icontains=event_location)

    event_analytics = []

    for event in events:
        staff_group = (
            Attendance.objects.filter(event=event)
            .exclude(department__isnull=True)
            .exclude(department__exact='')
            .values('department')
            .annotate(total=Count('id'))
            .order_by('-total', 'department')
        )

        visitor_group = (
            VisitorAttendance.objects.filter(event=event)
            .select_related('visitor')
            .exclude(visitor__organization__isnull=True)
            .exclude(visitor__organization__exact='')
            .values('visitor__organization')
            .annotate(total=Count('id'))
            .order_by('-total', 'visitor__organization')
        )

        staff_labels = [item['department'] for item in staff_group]
        staff_data = [item['total'] for item in staff_group]

        visitor_labels = [item['visitor__organization'] for item in visitor_group]
        visitor_data = [item['total'] for item in visitor_group]

        event_analytics.append({
            'event': event,
            'staff_labels_json': json.dumps(staff_labels),
            'staff_data_json': json.dumps(staff_data),
            'visitor_labels_json': json.dumps(visitor_labels),
            'visitor_data_json': json.dumps(visitor_data),
            'staff_total': sum(staff_data),
            'visitor_total': sum(visitor_data),
        })

    context = {
        'event_analytics': event_analytics,
        'filter_name': event_name,
        'filter_month': event_month,
        'filter_year': event_year,
        'filter_location': event_location,
    }
    context.update(role_context(request))

    return render(request, 'analytics.html', context)


def employees_page(request):
    login_check = require_login_page(request)
    if login_check:
        return login_check

    employees = Employee.objects.all().order_by('full_name')

    search_name = request.GET.get('name')
    department = request.GET.get('department')

    if search_name:
        employees = employees.filter(full_name__icontains=search_name)

    if department:
        employees = employees.filter(department__icontains=department)

    context = {
        'employees': employees
    }
    context.update(role_context(request))

    return render(request, 'employees.html', context)


@csrf_exempt
def add_employee(request):
    permission_check = require_admin_api(request)
    if permission_check:
        return permission_check

    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            full_name = data.get('full_name')
            employee_id = data.get('employee_id')
            email = data.get('email')
            department = data.get('department')
            registration_method = data.get('registration_method', 'manual')
            role = data.get('role', 'viewer')

            if not full_name or not employee_id or not email or not department:
                return JsonResponse({'error': 'All fields are required'}, status=400)

            if role not in ['editor', 'viewer', 'admin']:
                return JsonResponse({'error': 'Invalid role'}, status=400)

            if User.objects.filter(username=employee_id).exists():
                return JsonResponse({'error': 'Employee ID already exists as login user'}, status=400)

            if Employee.objects.filter(employee_id=employee_id).exists():
                return JsonResponse({'error': 'Employee ID already exists'}, status=400)

            if Employee.objects.filter(email=email).exists():
                return JsonResponse({'error': 'Email already exists'}, status=400)

            user = User.objects.create_user(
                username=employee_id,
                email=email,
                password='Password123'
            )

            Employee.objects.create(
                user=user,
                full_name=full_name,
                employee_id=employee_id,
                email=email,
                department=department,
                registration_method=registration_method,
                role=role
            )

            return JsonResponse({
                'message': 'Employee added successfully',
                'default_password': 'Password123'
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def delete_employee(request, id):
    permission_check = require_admin_api(request)
    if permission_check:
        return permission_check

    try:
        emp = Employee.objects.get(id=id)

        if emp.user:
            emp.user.delete()
        else:
            emp.delete()

        return JsonResponse({'message': 'Deleted successfully'})
    except Employee.DoesNotExist:
        return JsonResponse({'error': 'Employee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def update_employee(request, id):
    permission_check = require_admin_api(request)
    if permission_check:
        return permission_check

    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            emp = Employee.objects.get(id=id)

            full_name = data.get('full_name')
            employee_id = data.get('employee_id')
            email = data.get('email')
            department = data.get('department')
            registration_method = data.get('registration_method')
            role = data.get('role', emp.role)

            if not full_name or not employee_id or not email or not department:
                return JsonResponse({'error': 'All fields are required'}, status=400)

            if role not in ['editor', 'viewer', 'admin']:
                return JsonResponse({'error': 'Invalid role'}, status=400)

            if Employee.objects.exclude(id=id).filter(employee_id=employee_id).exists():
                return JsonResponse({'error': 'Employee ID already exists'}, status=400)

            if Employee.objects.exclude(id=id).filter(email=email).exists():
                return JsonResponse({'error': 'Email already exists'}, status=400)

            emp.full_name = full_name
            emp.employee_id = employee_id
            emp.email = email
            emp.department = department
            emp.registration_method = registration_method
            emp.role = role
            emp.save()

            if emp.user:
                emp.user.username = employee_id
                emp.user.email = email
                emp.user.save()

            return JsonResponse({'message': 'Updated successfully'})

        except Employee.DoesNotExist:
            return JsonResponse({'error': 'Employee not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def create_event(request):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            if not data.get('name') or not data.get('location') or not data.get('date'):
                return JsonResponse({'error': 'Name, location and date are required'}, status=400)

            event = Event.objects.create(
                name=data.get('name'),
                location=data.get('location'),
                date=data.get('date'),
                description=data.get('description'),
                latitude=data.get('latitude') if data.get('latitude') not in ['', None] else None,
                longitude=data.get('longitude') if data.get('longitude') not in ['', None] else None,
                radius_meter=data.get('radius_meter') or 100
            )

            visitor_qr_data = f"{NGROK_BASE_URL}/api/employees/visitor-attendance/{event.id}/"
            visitor_qr = qrcode.make(visitor_qr_data)
            visitor_buffer = BytesIO()
            visitor_qr.save(visitor_buffer, format='PNG')
            visitor_buffer.seek(0)
            event.visitor_qr_code.save(
                f'visitor_event_{event.id}.png',
                File(visitor_buffer),
                save=False
            )

            staff_qr_data = f"{NGROK_BASE_URL}/api/employees/staff-attendance/{event.id}/"
            staff_qr = qrcode.make(staff_qr_data)
            staff_buffer = BytesIO()
            staff_qr.save(staff_buffer, format='PNG')
            staff_buffer.seek(0)
            event.staff_qr_code.save(
                f'staff_event_{event.id}.png',
                File(staff_buffer),
                save=True
            )

            return JsonResponse({
                'message': 'Event created successfully',
                'visitor_qr_url': event.visitor_qr_code.url if event.visitor_qr_code else '',
                'staff_qr_url': event.staff_qr_code.url if event.staff_qr_code else ''
            })

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


def events_page(request):
    login_check = require_login_page(request)
    if login_check:
        return login_check

    events = Event.objects.all().order_by('-date', '-id')

    search_name = request.GET.get('name')
    search_location = request.GET.get('location')
    search_date = request.GET.get('date')

    if search_name:
        events = events.filter(name__icontains=search_name)

    if search_location:
        events = events.filter(location__icontains=search_location)

    if search_date:
        events = events.filter(date=search_date)

    context = {
        'events': events
    }
    context.update(role_context(request))

    return render(request, 'events.html', context)


@csrf_exempt
def update_event(request, id):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            event = Event.objects.get(id=id)

            event.name = data.get('name') or event.name
            event.location = data.get('location') or event.location
            event.date = data.get('date') or event.date
            event.description = data.get('description') if data.get('description') is not None else event.description

            if 'latitude' in data:
                event.latitude = data.get('latitude') if data.get('latitude') not in ['', None] else None

            if 'longitude' in data:
                event.longitude = data.get('longitude') if data.get('longitude') not in ['', None] else None

            if 'radius_meter' in data and data.get('radius_meter') not in ['', None]:
                event.radius_meter = data.get('radius_meter')

            event.save()

            return JsonResponse({'message': 'Updated successfully'})

        except Event.DoesNotExist:
            return JsonResponse({'error': 'Event not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@csrf_exempt
def delete_event(request, id):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    try:
        event = Event.objects.get(id=id)
        event.delete()
        return JsonResponse({'message': 'Deleted successfully'})
    except Event.DoesNotExist:
        return JsonResponse({'error': 'Event not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    lat1 = float(lat1)
    lon1 = float(lon1)
    lat2 = float(lat2)
    lon2 = float(lon2)

    r = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return r * c


def visitor_attendance_page(request, event_id):
    event = Event.objects.get(id=event_id)
    return render(request, 'visitor_attendance_form.html', {'event': event})


@csrf_exempt
def submit_visitor_attendance(request, event_id):
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Invalid request'}, status=400)

        data = json.loads(request.body)

        full_name = data.get('full_name')
        phone = data.get('phone')
        email = data.get('email')
        organization = data.get('organization')
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if not full_name or not phone or not email or not organization:
            return JsonResponse({'error': 'All fields are required'}, status=400)

        if latitude in [None, ''] or longitude in [None, '']:
            return JsonResponse({'error': 'Please enable GPS/location first'}, status=400)

        event = Event.objects.get(id=event_id)

        if event.latitude is None or event.longitude is None:
            return JsonResponse({'error': 'Event location not set'}, status=400)

        distance = calculate_distance_meters(latitude, longitude, event.latitude, event.longitude)

        if distance > event.radius_meter:
            return JsonResponse({
                'error': f'Attendance rejected. Outside allowed area ({round(distance, 2)}m)'
            }, status=400)

        visitor, _ = Visitor.objects.get_or_create(
            email=email,
            defaults={
                'full_name': full_name,
                'phone_number': phone,
                'organization': organization
            }
        )

        attendance, created = VisitorAttendance.objects.get_or_create(
            visitor=visitor,
            event=event,
            defaults={
                'latitude': latitude,
                'longitude': longitude
            }
        )

        if not created:
            return JsonResponse({'error': 'You have already registered for this event'}, status=400)

        return JsonResponse({
            'message': 'Successfully Registered',
            'distance_meter': round(distance, 2)
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def staff_attendance_page(request, event_id):
    event = Event.objects.get(id=event_id)
    return render(request, 'staff_attendance_form.html', {'event': event})


@csrf_exempt
def submit_staff_attendance(request, event_id):
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Invalid request'}, status=400)

        data = json.loads(request.body)

        full_name = data.get('full_name')
        employee_id = data.get('employee_id')
        phone = data.get('phone')
        email = data.get('email')
        department = data.get('department')
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if not full_name or not employee_id or not phone or not email or not department:
            return JsonResponse({'error': 'All fields are required'}, status=400)

        if latitude in [None, ''] or longitude in [None, '']:
            return JsonResponse({'error': 'Please enable GPS/location first'}, status=400)

        event = Event.objects.get(id=event_id)

        if event.latitude is None or event.longitude is None:
            return JsonResponse({'error': 'Event location not set'}, status=400)

        distance = calculate_distance_meters(latitude, longitude, event.latitude, event.longitude)

        if distance > event.radius_meter:
            return JsonResponse({
                'error': f'Attendance rejected. Outside allowed area ({round(distance, 2)}m)'
            }, status=400)

        attendance, created = Attendance.objects.get_or_create(
            employee_id=employee_id,
            event=event,
            defaults={
                'full_name': full_name,
                'phone_number': phone,
                'email': email,
                'department': department,
                'latitude': latitude,
                'longitude': longitude
            }
        )

        if not created:
            return JsonResponse({'error': 'You have already registered for this event'}, status=400)

        return JsonResponse({
            'message': 'Successfully Registered',
            'distance_meter': round(distance, 2)
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def update_staff_attendance(request, id):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        data = json.loads(request.body)
        att = Attendance.objects.get(id=id)

        att.full_name = data.get('full_name', att.full_name)
        att.employee_id = data.get('employee_id', att.employee_id)
        att.phone_number = data.get('phone_number', att.phone_number)
        att.email = data.get('email', att.email)
        att.department = data.get('department', att.department)
        att.save()

        return JsonResponse({'message': 'Staff attendance updated successfully'})
    except Attendance.DoesNotExist:
        return JsonResponse({'error': 'Staff attendance not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def delete_staff_attendance(request, id):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    try:
        att = Attendance.objects.get(id=id)
        att.delete()
        return JsonResponse({'message': 'Staff attendance deleted successfully'})
    except Attendance.DoesNotExist:
        return JsonResponse({'error': 'Staff attendance not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def update_visitor_attendance(request, id):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    try:
        data = json.loads(request.body)
        att = VisitorAttendance.objects.select_related('visitor').get(id=id)
        visitor = att.visitor

        visitor.full_name = data.get('full_name', visitor.full_name)
        visitor.phone_number = data.get('phone_number', visitor.phone_number)
        visitor.email = data.get('email', visitor.email)
        visitor.organization = data.get('organization', visitor.organization)
        visitor.save()

        return JsonResponse({'message': 'Visitor attendance updated successfully'})
    except VisitorAttendance.DoesNotExist:
        return JsonResponse({'error': 'Visitor attendance not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def delete_visitor_attendance(request, id):
    permission_check = require_manage_api(request)
    if permission_check:
        return permission_check

    try:
        att = VisitorAttendance.objects.get(id=id)
        att.delete()
        return JsonResponse({'message': 'Visitor attendance deleted successfully'})
    except VisitorAttendance.DoesNotExist:
        return JsonResponse({'error': 'Visitor attendance not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def event_detail(request, id):
    login_check = require_login_page(request)
    if login_check:
        return login_check

    event = get_object_or_404(Event, id=id)

    staff_search = request.GET.get('staff_search', '').strip()
    staff_department = request.GET.get('staff_department', '').strip()
    staff_sort = request.GET.get('staff_sort', 'date')
    staff_page_num = request.GET.get('staff_page', 1)

    staff_qs = Attendance.objects.filter(event=event)

    if staff_search:
        staff_qs = staff_qs.filter(full_name__icontains=staff_search)

    if staff_department:
        staff_qs = staff_qs.filter(department__iexact=staff_department)

    if staff_sort == 'name':
        staff_qs = staff_qs.order_by('full_name')
    elif staff_sort == 'time':
        staff_qs = staff_qs.order_by('time')
    else:
        staff_qs = staff_qs.order_by('date', 'time')

    staff_departments = (
        Attendance.objects.filter(event=event)
        .exclude(department__isnull=True)
        .exclude(department__exact='')
        .values_list('department', flat=True)
        .distinct()
        .order_by('department')
    )

    staff_paginator = Paginator(staff_qs, 5)
    staff_page_obj = staff_paginator.get_page(staff_page_num)

    visitor_search = request.GET.get('visitor_search', '').strip()
    visitor_organization = request.GET.get('visitor_organization', '').strip()
    visitor_sort = request.GET.get('visitor_sort', 'date')
    visitor_page_num = request.GET.get('visitor_page', 1)

    visitor_qs = VisitorAttendance.objects.filter(event=event).select_related('visitor')

    if visitor_search:
        visitor_qs = visitor_qs.filter(visitor__full_name__icontains=visitor_search)

    if visitor_organization:
        visitor_qs = visitor_qs.filter(visitor__organization__iexact=visitor_organization)

    if visitor_sort == 'name':
        visitor_qs = visitor_qs.order_by('visitor__full_name')
    elif visitor_sort == 'time':
        visitor_qs = visitor_qs.order_by('time')
    else:
        visitor_qs = visitor_qs.order_by('date', 'time')

    visitor_organizations = (
        VisitorAttendance.objects.filter(event=event)
        .select_related('visitor')
        .exclude(visitor__organization__isnull=True)
        .exclude(visitor__organization__exact='')
        .values_list('visitor__organization', flat=True)
        .distinct()
        .order_by('visitor__organization')
    )

    visitor_paginator = Paginator(visitor_qs, 5)
    visitor_page_obj = visitor_paginator.get_page(visitor_page_num)

    total_attendance = Attendance.objects.filter(event=event).count() + VisitorAttendance.objects.filter(event=event).count()

    context = {
        'event': event,
        'total_attendance': total_attendance,

        'employee_attendances': staff_page_obj.object_list,
        'staff_page_obj': staff_page_obj,
        'staff_departments': staff_departments,
        'staff_search': staff_search,
        'staff_department': staff_department,
        'staff_sort': staff_sort,

        'visitor_attendances': visitor_page_obj.object_list,
        'visitor_page_obj': visitor_page_obj,
        'visitor_organizations': visitor_organizations,
        'visitor_search': visitor_search,
        'visitor_organization': visitor_organization,
        'visitor_sort': visitor_sort,
    }
    context.update(role_context(request))

    return render(request, 'event_detail.html', context)


def export_attendance_csv(request, id):
    manage_check = require_manage_page(request)
    if manage_check:
        return manage_check

    event = Event.objects.get(id=id)
    employee_attendances = Attendance.objects.filter(event=event)
    visitor_attendances = VisitorAttendance.objects.filter(event=event).select_related('visitor')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{event.name}_attendance.csv"'

    writer = csv.writer(response)

    writer.writerow(['EMPLOYEE ATTENDANCE'])
    writer.writerow(['Name', 'Employee ID', 'Phone', 'Email', 'Department', 'Date', 'Time', 'Latitude', 'Longitude'])

    for att in employee_attendances:
        writer.writerow([
            att.full_name,
            att.employee_id,
            att.phone_number,
            att.email,
            att.department,
            att.date.strftime("%d/%m/%Y"),
            att.time.strftime("%H:%M:%S"),
            att.latitude,
            att.longitude
        ])

    writer.writerow([])
    writer.writerow(['VISITOR ATTENDANCE'])
    writer.writerow(['Name', 'Phone', 'Email', 'Organization', 'Date', 'Time', 'Latitude', 'Longitude'])

    for att in visitor_attendances:
        writer.writerow([
            att.visitor.full_name,
            att.visitor.phone_number,
            att.visitor.email,
            att.visitor.organization,
            att.date.strftime("%d/%m/%Y"),
            att.time.strftime("%H:%M:%S"),
            att.latitude,
            att.longitude
        ])

    return response


def export_event_summary_csv(request, id):
    manage_check = require_manage_page(request)
    if manage_check:
        return manage_check

    event = get_object_or_404(Event, id=id)

    staff_group = (
        Attendance.objects.filter(event=event)
        .exclude(department__isnull=True)
        .exclude(department__exact='')
        .values('department')
        .annotate(total=Count('id'))
        .order_by('-total', 'department')
    )

    visitor_group = (
        VisitorAttendance.objects.filter(event=event)
        .select_related('visitor')
        .exclude(visitor__organization__isnull=True)
        .exclude(visitor__organization__exact='')
        .values('visitor__organization')
        .annotate(total=Count('id'))
        .order_by('-total', 'visitor__organization')
    )

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{event.name}_summary.csv"'

    writer = csv.writer(response)

    writer.writerow(['EVENT SUMMARY'])
    writer.writerow(['Event Name', event.name])
    writer.writerow(['Date', event.date.strftime("%d/%m/%Y")])
    writer.writerow(['Location', event.location])
    writer.writerow(['Description', event.description if event.description else '-'])
    writer.writerow(['Latitude', event.latitude if event.latitude is not None else '-'])
    writer.writerow(['Longitude', event.longitude if event.longitude is not None else '-'])
    writer.writerow(['Radius (meter)', event.radius_meter])
    writer.writerow([])

    writer.writerow(['STAFF / EMPLOYEE BY DEPARTMENT'])
    writer.writerow(['Department', 'Total'])
    for item in staff_group:
        writer.writerow([item['department'], item['total']])

    writer.writerow([])
    writer.writerow(['VISITOR BY ORGANIZATION'])
    writer.writerow(['Organization', 'Total'])
    for item in visitor_group:
        writer.writerow([item['visitor__organization'], item['total']])

    return response