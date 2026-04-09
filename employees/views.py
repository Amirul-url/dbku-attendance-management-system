import csv
import datetime
import json
import math
import os
import re
import threading
import uuid
import ipaddress
from io import BytesIO

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import cv2
import numpy as np
import pytesseract
import qrcode
from PIL import Image
from paddleocr import PaddleOCR

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.core.files import File
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt

from .models import (
    Attendance,
    Employee,
    Event,
    PassportAttendance,
    PassportVisitor,
    Visitor,
    VisitorAttendance,
)

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


NGROK_BASE_URL = "https://exospherical-kimberlie-unrefulgent.ngrok-free.dev"

PADDLE_OCR = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang='en'
)

PADDLE_OCR_LOCK = threading.Lock()

# Keep this map for display only
COUNTRY_CODE_MAP = {
    "MYS": "Malaysia",
    "JPN": "Japan",
    "IDN": "Indonesia",
    "SGP": "Singapore",
    "THA": "Thailand",
    "BRN": "Brunei",
    "PHL": "Philippines",
    "VNM": "Vietnam",
    "CHN": "China",
    "KOR": "South Korea",
    "PRK": "North Korea",
    "IND": "India",
    "PAK": "Pakistan",
    "BGD": "Bangladesh",
    "LKA": "Sri Lanka",
    "NPL": "Nepal",
    "MMR": "Myanmar",
    "KHM": "Cambodia",
    "LAO": "Laos",
    "USA": "United States",
    "CAN": "Canada",
    "GBR": "United Kingdom",
    "AUS": "Australia",
    "NZL": "New Zealand",
    "DEU": "Germany",
    "FRA": "France",
    "ITA": "Italy",
    "ESP": "Spain",
    "PRT": "Portugal",
    "NLD": "Netherlands",
    "BEL": "Belgium",
    "CHE": "Switzerland",
    "AUT": "Austria",
    "SWE": "Sweden",
    "NOR": "Norway",
    "DNK": "Denmark",
    "FIN": "Finland",
    "IRL": "Ireland",
    "POL": "Poland",
    "CZE": "Czech Republic",
    "TUR": "Turkey",
    "SAU": "Saudi Arabia",
    "ARE": "United Arab Emirates",
    "QAT": "Qatar",
    "KWT": "Kuwait",
    "OMN": "Oman",
    "BHR": "Bahrain",
    "EGY": "Egypt",
    "ZAF": "South Africa",
    "BRA": "Brazil",
    "MEX": "Mexico",
    "RUS": "Russia",
}

# For global passports: keep validation generic
GENERIC_PASSPORT_PATTERN = r"^[A-Z0-9]{6,12}$"

COUNTRY_PASSPORT_PATTERNS = {
    "JPN": r"^[A-Z]{2}\d{7}$",
    "KOR": r"^[A-Z]{1}[A-Z0-9]{8}$",
    "USA": r"^\d{9}$",
    "GBR": r"^\d{9}$",
    "IND": r"^[A-Z]{1}\d{7}$",
    "IDN": r"^[A-Z]{1,2}\d{6,8}$",
    "MYS": r"^[A-Z]{1}\d{8}$",
    "CHN": r"^[A-Z0-9]{8,9}$",
    "SGP": r"^[A-Z]\d{7}[A-Z]?$",
    "THA": r"^[A-Z]{1,2}\d{6,7}$",
}


def country_code_to_name(code):
    code = (code or "").strip().upper()
    return COUNTRY_CODE_MAP.get(code, code if code else "Unknown")


def validate_passport_number_by_country(passport_number, country_code_or_name):
    passport_number = re.sub(r'[^A-Z0-9]', '', (passport_number or '').upper())
    country_value = (country_code_or_name or '').strip()

    if not passport_number:
        return False, "Passport number cannot be empty"

    # generic minimum validation dulu
    if not re.match(GENERIC_PASSPORT_PATTERN, passport_number):
        return False, "Passport number format is invalid"

    # tukar country name → code kalau perlu
    country_code = ""
    upper_value = country_value.upper()

    if upper_value in COUNTRY_CODE_MAP:
        country_code = upper_value
    else:
        reverse_map = {v.upper(): k for k, v in COUNTRY_CODE_MAP.items()}
        country_code = reverse_map.get(upper_value, "")

    # country-specific validation
    pattern = COUNTRY_PASSPORT_PATTERNS.get(country_code)
    if pattern and not re.match(pattern, passport_number):
        country_label = COUNTRY_CODE_MAP.get(country_code, country_code)
        return False, f"Invalid passport format for {country_label}"

    return True, ""

def fix_common_ocr_errors(text, mode="general"):
    if not text:
        return ""

    text = text.strip().upper()

    if mode == "mrz":
        text = text.replace(" ", "")
        text = text.replace("«", "<").replace("‹", "<").replace("〈", "<")
        text = text.replace("|", "I")

        # keep only MRZ-safe chars
        text = re.sub(r'[^A-Z0-9<]', '', text)

        # normalize repeated noise
        text = text.replace("KKKK", "<<<<")
        text = text.replace("KKK", "<<<")
        text = text.replace("KK", "<<")

        # common OCR fixes inside MRZ
        text = text.replace("5PN", "JPN")
        text = text.replace("2PN", "JPN")
        text = text.replace("7PN", "JPN")
        text = text.replace("25PN", "JPN")
        text = text.replace("MYS:", "MYS")
        text = text.replace("MYSMA", "MYSMA")
        text = text.replace("P<MYSMA", "P<MYSMA")
        text = text.replace("P<JPNNA", "P<JPNNA")
        text = text.replace("O<", "0<")
        text = text.replace("<K<", "<<")

        return text

    if mode == "passport":
        text = re.sub(r'[^A-Z0-9]', '', text)
        if not text:
            return ""

        # OCR often confuses these in passport number
        text = (
            text.replace("O", "0")
                .replace("Q", "0")
                .replace("I", "1")
                .replace("L", "1")
                .replace("S", "5")
                .replace("B", "8")
        )
        return text

    if mode == "name":
        text = text.replace("0", "O")
        text = text.replace("1", "I")
        text = text.replace("5", "S")
        text = re.sub(r'[^A-Z< ]', '', text)
        return text

    return text

def rescue_mrz_lines(text):
    if not text:
        return []

    raw_lines = [x.strip().upper() for x in text.splitlines() if x.strip()]
    rescued = []

    for line in raw_lines:
        line = fix_common_ocr_errors(line, mode="mrz")
        line = re.sub(r'[^A-Z0-9<]', '', line)

        # passport MRZ lines usually long and contain <
        if len(line) >= 25 and '<' in line:
            rescued.append(line)

    return rescued


def parse_mrz_rescue(text):
    mrz_lines = rescue_mrz_lines(text)
    if len(mrz_lines) < 2:
        return None

    best_pair = None
    best_score = -1

    for i in range(len(mrz_lines) - 1):
        l1 = mrz_lines[i]
        l2 = mrz_lines[i + 1]

        score = 0
        if l1.startswith('P<'):
            score += 2
        if len(l1) >= 35:
            score += 1
        if len(l2) >= 35:
            score += 1
        if '<' in l1 and '<' in l2:
            score += 1

        if score > best_score:
            best_score = score
            best_pair = (l1, l2)

    if not best_pair:
        return None

    return parse_two_line_passport_mrz(best_pair[0], best_pair[1], rescue_mode=True)

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

    today = datetime.date.today()

    total_employees = Employee.objects.count()
    total_visitors = Visitor.objects.count()
    total_events = Event.objects.count()
    active_events = Event.objects.filter(start_date__lte=today, end_date__gte=today).count()
    total_staff_attendance = Attendance.objects.count()
    total_visitor_attendance = VisitorAttendance.objects.count()
    total_attendance = total_staff_attendance + total_visitor_attendance

    context = {
        'total_employees': total_employees,
        'total_visitors': total_visitors,
        'total_events': total_events,
        'active_events': active_events,
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

    events = Event.objects.all().order_by('-start_date', '-id')

    if event_name:
        events = events.filter(name__icontains=event_name)

    if event_month:
        events = events.filter(start_date__month=event_month)

    if event_year:
        events = events.filter(start_date__year=event_year)

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

            name = (data.get('name') or '').strip()
            location = (data.get('location') or '').strip()
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            start_time = data.get('start_time') or None
            end_time = data.get('end_time') or None

            if not name or not location or not start_date or not end_date:
                return JsonResponse({'error': 'Name, location, start date and end date are required'}, status=400)

            start_date_obj = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()

            if end_date_obj < start_date_obj:
                return JsonResponse({'error': 'End date cannot be earlier than start date'}, status=400)

            if start_date == end_date and start_time and end_time:
                start_time_obj = datetime.datetime.strptime(start_time, "%H:%M").time()
                end_time_obj = datetime.datetime.strptime(end_time, "%H:%M").time()

                if end_time_obj <= start_time_obj:
                    return JsonResponse({'error': 'End time must be later than start time'}, status=400)

            radius = data.get('radius_meter')

            try:
                radius = int(radius)
                if radius <= 0:
                    radius = 100
            except (TypeError, ValueError):
                radius = 100

            event = Event.objects.create(
                name=name,
                location=location,
                start_date=start_date,
                end_date=end_date,
                start_time=start_time,
                end_time=end_time,
                description=data.get('description'),
                latitude=data.get('latitude') if data.get('latitude') not in ['', None] else None,
                longitude=data.get('longitude') if data.get('longitude') not in ['', None] else None,
                radius_meter=radius
            )

            visitor_qr_data = f"{NGROK_BASE_URL}/api/employees/visitor-attendance/{event.id}/"
            visitor_qr = qrcode.make(visitor_qr_data)
            visitor_buffer = BytesIO()
            visitor_qr.save(visitor_buffer, format='PNG')
            visitor_buffer.seek(0)
            event.visitor_qr_code.save(
                f'visitor_event_{event.id}.png',
                File(visitor_buffer),
                save=True
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

            passport_qr_data = f"{NGROK_BASE_URL}/api/employees/passport-attendance/{event.id}/"
            passport_qr = qrcode.make(passport_qr_data)
            passport_buffer = BytesIO()
            passport_qr.save(passport_buffer, format='PNG')
            passport_buffer.seek(0)
            event.passport_qr_code.save(
                f'passport_event_{event.id}.png',
                File(passport_buffer),
                save=True
            )

            return JsonResponse({
                'message': 'Event created successfully',
                'visitor_qr_url': event.visitor_qr_code.url if event.visitor_qr_code else '',
                'staff_qr_url': event.staff_qr_code.url if event.staff_qr_code else ''
            })

        except ValueError:
            return JsonResponse({'error': 'Invalid date or time format'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


def events_page(request):
    login_check = require_login_page(request)
    if login_check:
        return login_check

    events = Event.objects.all().order_by('-start_date', '-id')

    search_name = request.GET.get('name')
    search_location = request.GET.get('location')
    search_date = request.GET.get('date')

    if search_name:
        events = events.filter(name__icontains=search_name)

    if search_location:
        events = events.filter(location__icontains=search_location)

    if search_date:
        events = events.filter(start_date__lte=search_date, end_date__gte=search_date)

    context = {
        'events': events,
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

            new_start_date = data.get('start_date') or str(event.start_date)
            new_end_date = data.get('end_date') or str(event.end_date)
            new_start_time = data.get('start_time') if 'start_time' in data else (event.start_time.strftime("%H:%M") if event.start_time else None)
            new_end_time = data.get('end_time') if 'end_time' in data else (event.end_time.strftime("%H:%M") if event.end_time else None)

            start_date_obj = datetime.datetime.strptime(new_start_date, "%Y-%m-%d").date()
            end_date_obj = datetime.datetime.strptime(new_end_date, "%Y-%m-%d").date()

            if end_date_obj < start_date_obj:
                return JsonResponse({'error': 'End date cannot be earlier than start date'}, status=400)

            if new_start_date == new_end_date and new_start_time and new_end_time:
                start_time_obj = datetime.datetime.strptime(new_start_time, "%H:%M").time()
                end_time_obj = datetime.datetime.strptime(new_end_time, "%H:%M").time()

                if end_time_obj <= start_time_obj:
                    return JsonResponse({'error': 'End time must be later than start time'}, status=400)

            event.name = data.get('name') or event.name
            event.location = data.get('location') or event.location
            event.start_date = new_start_date
            event.end_date = new_end_date
            event.start_time = new_start_time or None
            event.end_time = new_end_time or None
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
        except ValueError:
            return JsonResponse({'error': 'Invalid date or time format'}, status=400)
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

def normalize_ip_value(raw_ip):
    if not raw_ip:
        return None

    raw_ip = raw_ip.strip()

    # contoh: [2001:db8::1]:443
    if raw_ip.startswith('[') and ']' in raw_ip:
        raw_ip = raw_ip[1:raw_ip.index(']')]

    # contoh: 192.168.0.10:8000
    elif raw_ip.count(':') == 1 and '.' in raw_ip.split(':')[0]:
        raw_ip = raw_ip.split(':')[0]

    # buang scope id kalau ada, contoh fe80::1%eth0
    raw_ip = raw_ip.split('%')[0]

    try:
        return str(ipaddress.ip_address(raw_ip))
    except ValueError:
        return None


def get_client_ips(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')

    candidates = []
    if x_forwarded_for:
        candidates = [ip.strip() for ip in x_forwarded_for.split(',') if ip.strip()]
    else:
        remote_addr = request.META.get('REMOTE_ADDR')
        if remote_addr:
            candidates = [remote_addr]

    ipv4_address = None
    ipv6_address = None

    for raw_ip in candidates:
        clean_ip = normalize_ip_value(raw_ip)
        if not clean_ip:
            continue

        parsed_ip = ipaddress.ip_address(clean_ip)

        if parsed_ip.version == 4 and not ipv4_address:
            ipv4_address = clean_ip
        elif parsed_ip.version == 6 and not ipv6_address:
            ipv6_address = clean_ip

    return ipv4_address, ipv6_address

def visitor_attendance_page(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    return render(request, 'visitor_attendance_form.html', {'event': event})


@csrf_exempt
def submit_visitor_attendance(request, event_id):
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Invalid request'}, status=400)

        data = json.loads(request.body)

        full_name = (data.get('full_name') or '').strip()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip().lower()
        organization = (data.get('organization') or '').strip()
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if not full_name or not phone or not email or not organization:
            return JsonResponse({'error': 'All fields are required'}, status=400)

        if not phone.isdigit() or len(phone) < 9:
            return JsonResponse({'error': 'Invalid phone number'}, status=400)        

        if latitude in [None, ''] or longitude in [None, '']:
            return JsonResponse({'error': 'Please enable GPS/location first'}, status=400)

        event = get_object_or_404(Event, id=event_id)

        if event.latitude is None or event.longitude is None:
            return JsonResponse({'error': 'Event location not set'}, status=400)

        distance = calculate_distance_meters(latitude, longitude, event.latitude, event.longitude)

        if distance > event.radius_meter:
            return JsonResponse({
                'error': f'Attendance rejected. Outside allowed area ({round(distance, 2)}m)'
            }, status=400)

        visitor, created_visitor = Visitor.objects.get_or_create(
            email=email,
            defaults={
                'full_name': full_name,
                'phone_number': phone,
                'organization': organization
            }
        )

        if not created_visitor:
            visitor.full_name = full_name
            visitor.phone_number = phone
            visitor.organization = organization
            visitor.save()

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
            'distance_meter': round(distance, 2),
            'event': event.name
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def staff_attendance_page(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    return render(request, 'staff_attendance_form.html', {'event': event})


@csrf_exempt
def submit_staff_attendance(request, event_id):
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Invalid request'}, status=400)

        data = json.loads(request.body)

        full_name = (data.get('full_name') or '').strip()
        employee_id = (data.get('employee_id') or '').strip().upper()
        phone = (data.get('phone') or '').strip()
        email = (data.get('email') or '').strip().lower()
        department = (data.get('department') or '').strip()
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        ipv4_address, ipv6_address = get_client_ips(request)
        submitted_ipv4 = (data.get('ipv4_address') or '').strip()

        # fallback: guna IPv4 dari browser kalau header tak ada
        if not ipv4_address and submitted_ipv4:
            try:
                parsed = ipaddress.ip_address(submitted_ipv4)
                if parsed.version == 4:
                    ipv4_address = str(parsed)
            except ValueError:
                pass        
        
        print("=== STAFF ATTENDANCE IP DEBUG ===")
        print("HTTP_X_FORWARDED_FOR:", request.META.get('HTTP_X_FORWARDED_FOR'))
        print("REMOTE_ADDR:", request.META.get('REMOTE_ADDR'))
        print("IPv4 detected:", ipv4_address)
        print("IPv6 detected:", ipv6_address)

        if not all([full_name, employee_id, phone, email, department]):
            return JsonResponse({'error': 'All fields are required'}, status=400)

        if not phone.isdigit() or len(phone) < 9:
            return JsonResponse({'error': 'Invalid phone number'}, status=400)

        # ✅ GPS CHECK
        if latitude in [None, ''] or longitude in [None, '']:
            return JsonResponse({'error': 'Please enable GPS/location first'}, status=400)

        # ✅ EVENT CHECK (SAFE)
        event = get_object_or_404(Event, id=event_id)

        if event.latitude is None or event.longitude is None:
            return JsonResponse({'error': 'Event location not configured by admin'}, status=400)

        # ✅ VALIDATE EMPLOYEE EXIST
        employee = Employee.objects.filter(employee_id=employee_id).first()

        if not employee:
            return JsonResponse({'error': 'Employee ID not found. Please register first.'}, status=404)

        # OPTIONAL STRICT CHECK (email match)
        if employee.email.lower() != email:
            return JsonResponse({'error': 'Email does not match registered employee'}, status=400)

        # ✅ GEOFENCE CHECK
        distance = calculate_distance_meters(
            latitude, longitude,
            event.latitude, event.longitude
        )

        if distance > event.radius_meter:
            return JsonResponse({
                'error': f'Attendance rejected. Outside allowed area ({round(distance, 2)}m)'
            }, status=400)

        # ✅ SAVE ATTENDANCE (ANTI DUPLICATE)
        attendance, created = Attendance.objects.get_or_create(
            employee_id=employee_id,
            event=event,
            defaults={
                'full_name': employee.full_name,
                'phone_number': phone,
                'email': employee.email,
                'department': employee.department,
                'ipv4_address': ipv4_address,
                'ipv6_address': ipv6_address,
                'latitude': latitude,
                'longitude': longitude
            }
        )

        if not created:
            return JsonResponse({'error': 'Attendance already recorded'}, status=400)

        return JsonResponse({
            'message': 'Attendance successful',
            'distance_meter': round(distance, 2),
            'event': event.name
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

    # =========================
    # STAFF ATTENDANCE
    # =========================
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

    # =========================
    # VISITOR (MALAYSIAN)
    # =========================
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

    # =========================
    # VISITOR (NON-MALAYSIAN)
    # =========================
    passport_search = request.GET.get('passport_search', '').strip()
    passport_country = request.GET.get('passport_country', '').strip()
    passport_sort = request.GET.get('passport_sort', 'date')
    passport_page_num = request.GET.get('passport_page', 1)

    passport_qs = PassportAttendance.objects.filter(event=event).select_related('passport_visitor')

    if passport_search:
        passport_qs = passport_qs.filter(passport_visitor__full_name__icontains=passport_search)

    if passport_country:
        passport_qs = passport_qs.filter(passport_visitor__country__iexact=passport_country)

    if passport_sort == 'name':
        passport_qs = passport_qs.order_by('passport_visitor__full_name')
    elif passport_sort == 'time':
        passport_qs = passport_qs.order_by('time')
    else:
        passport_qs = passport_qs.order_by('date', 'time')

    passport_countries = (
        PassportAttendance.objects.filter(event=event)
        .select_related('passport_visitor')
        .exclude(passport_visitor__country__isnull=True)
        .exclude(passport_visitor__country__exact='')
        .values_list('passport_visitor__country', flat=True)
        .distinct()
        .order_by('passport_visitor__country')
    )

    passport_paginator = Paginator(passport_qs, 5)
    passport_page_obj = passport_paginator.get_page(passport_page_num)

    # =========================
    # TOTAL
    # =========================
    total_attendance = (
        Attendance.objects.filter(event=event).count()
        + VisitorAttendance.objects.filter(event=event).count()
        + PassportAttendance.objects.filter(event=event).count()
    )

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

        'passport_attendances': passport_page_obj.object_list,
        'passport_page_obj': passport_page_obj,
        'passport_countries': passport_countries,
        'passport_search': passport_search,
        'passport_country': passport_country,
        'passport_sort': passport_sort,
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
    writer.writerow(['Name', 'Employee ID', 'Phone', 'Email', 'Department', 'IPv4', 'IPv6', 'Date', 'Time', 'Latitude', 'Longitude'])

    for att in employee_attendances:
        writer.writerow([
            att.full_name,
            att.employee_id,
            f"'{att.phone_number}",
            att.email,
            att.department,
            att.ipv4_address or '-',
            att.ipv6_address or '-',
            att.date.strftime("%d/%m/%Y"),
            att.time.strftime("%H:%M:%S"),
            att.latitude,
            att.longitude
        ])

    writer.writerow([])
    writer.writerow(['VISITOR ATTENDANCE (MALAYSIAN)'])
    writer.writerow(['Name', 'Phone', 'Email', 'Organization', 'Date', 'Time', 'Latitude', 'Longitude'])

    for att in visitor_attendances:
        writer.writerow([
            att.visitor.full_name,
            f"'{att.visitor.phone_number}",
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
    writer.writerow(['Start Date', event.start_date.strftime("%d/%m/%Y")])
    writer.writerow(['End Date', event.end_date.strftime("%d/%m/%Y")])
    writer.writerow(['Start Time', event.start_time.strftime("%H:%M") if event.start_time else '-'])
    writer.writerow(['End Time', event.end_time.strftime("%H:%M") if event.end_time else '-'])
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

def ensure_media_dirs():
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'passport_images'), exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'passport_processed'), exist_ok=True)

def get_country_choices():
    return sorted(set(COUNTRY_CODE_MAP.values()))


def normalize_date_for_html(date_str):
    if not date_str:
        return ""
    parsed = parse_passport_date(date_str)
    if not parsed:
        return ""
    return parsed.strftime("%Y-%m-%d")


def parse_passport_date(date_str):
    if not date_str:
        return None

    cleaned = date_str.strip().upper().replace("/", "-").replace(".", "-")
    cleaned = re.sub(r'\s+', ' ', cleaned)

    for fmt in [
        "%d %b %Y",
        "%d %B %Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d-%m-%y",
        "%d %b %y",
        "%d-%b-%Y",
        "%d-%b-%y",
    ]:
        try:
            return datetime.datetime.strptime(cleaned, fmt)
        except ValueError:
            pass

    return None


def is_expiry_valid(expiry_date_str):
    expiry_dt = parse_passport_date(expiry_date_str)
    if not expiry_dt:
        return False
    return expiry_dt.date() >= datetime.datetime.today().date()


def normalize_mrz_name(name):
    if not name:
        return ""

    name = fix_common_ocr_errors(name, mode="name")
    name = name.replace("<", " ")
    name = re.sub(r'\s+', ' ', name).strip()

    # split joined Malay/Japanese/English style chunks more safely
    name = re.sub(r'\bBIN(?=[A-Z])', 'BIN ', name)
    name = re.sub(r'\bBINTI(?=[A-Z])', 'BINTI ', name)

    return name.title()

def repair_mrz_line2(line2):
    if not line2:
        return ""

    line2 = fix_common_ocr_errors(line2, mode="mrz")

    # common nationality OCR repair
    line2 = line2.replace("5PN", "JPN")
    line2 = line2.replace("7PN", "JPN")
    line2 = line2.replace("25PN", "JPN")
    line2 = line2.replace("MYS", "MYS")

    # try repair first 9 chars as passport no
    first9 = line2[:9]
    rest = line2[9:]

    first9 = re.sub(r'[^A-Z0-9<]', '', first9)
    first9 = first9.replace("O", "0").replace("Q", "0")
    first9 = first9.replace("I", "1").replace("L", "1")

    return first9 + rest

def parse_two_line_passport_mrz(line1, line2, rescue_mode=False):
    try:
        line1 = fix_common_ocr_errors(line1, mode="mrz")
        line2 = repair_mrz_line2(line2)

        line1 = re.sub(r'[^A-Z0-9<]', '', line1)
        line2 = re.sub(r'[^A-Z0-9<]', '', line2)

        if len(line1) < 40:
            line1 = line1.ljust(44, '<')
        else:
            line1 = line1[:44]

        if len(line2) < 40:
            line2 = line2.ljust(44, '<')
        else:
            line2 = line2[:44]

        if not line1.startswith("P<"):
            return None

        issuing_country = line1[2:5]
        names_part = line1[5:]

        surname_part = ""
        given_part = ""

        if "<<" in names_part:
            surname_part, given_part = names_part.split("<<", 1)
        else:
            repaired_names = names_part

            # OCR sometimes breaks the separator between surname and given name
            # example: NAKAMOTO<K<SATOSHI
            repaired_names = repaired_names.replace("<K<", "<<")

            # fallback: if still no proper separator, convert first single separator only
            if "<<" not in repaired_names and "<" in repaired_names:
                repaired_names = repaired_names.replace("<", "<<", 1)

            if "<<" in repaired_names:
                surname_part, given_part = repaired_names.split("<<", 1)
            else:
                surname_part, given_part = repaired_names, ""

        surname_clean = normalize_mrz_name(surname_part)
        given_clean = normalize_mrz_name(given_part)

        # extra fallback: if given name still blank but surname has multiple tokens,
        # split first token as surname and the rest as given name
        if surname_clean and not given_clean:
            parts = surname_clean.split()
            if len(parts) >= 2:
                surname_clean = parts[0]
                given_clean = " ".join(parts[1:])

        full_name = f"{surname_clean} {given_clean}".strip()

        passport_raw = line2[0:9]
        passport_check = line2[9]
        nationality = line2[10:13]
        dob_raw = line2[13:19]
        dob_check = line2[19]
        gender_char = line2[20]
        expiry_raw = line2[21:27]
        expiry_check = line2[27]

        passport_number = passport_raw.replace("<", "")
        passport_number = fix_common_ocr_errors(passport_number, mode="passport")

        passport_valid = mrz_check_digit(passport_raw) == passport_check
        dob_valid = mrz_check_digit(dob_raw) == dob_check
        expiry_valid = mrz_check_digit(expiry_raw) == expiry_check

        def yyMMdd_to_ddmmyyyy(raw):
            if not raw.isdigit() or len(raw) != 6:
                return ""

            yy = int(raw[:2])
            mm = raw[2:4]
            dd = raw[4:6]

            current_year_2 = int(datetime.datetime.now().strftime("%y"))
            if yy <= current_year_2:
                year = 2000 + yy
            else:
                year = 1900 + yy

            return f"{dd}-{mm}-{year}"

        dob = yyMMdd_to_ddmmyyyy(dob_raw)
        expiry = yyMMdd_to_ddmmyyyy(expiry_raw)

        gender = ""
        if gender_char == "M":
            gender = "Male"
        elif gender_char == "F":
            gender = "Female"

        valid_score = sum([passport_valid, dob_valid, expiry_valid])

        country_code = nationality if nationality in COUNTRY_CODE_MAP else issuing_country

        return {
            "type": "P",
            "surname": surname_clean,
            "given_name": given_clean,
            "full_name": full_name,
            "passport_number": passport_number,
            "country": country_code_to_name(country_code),
            "country_code": issuing_country,
            "nationality": country_code_to_name(nationality),
            "nationality_code": nationality,
            "date_of_birth": dob,
            "expiry_date": expiry,
            "sex": gender,
            "gender": gender,
            "mrz_valid_score": valid_score,
            "mrz_total_checks": 3,
            "issuing_country_code": issuing_country,
            "raw_mrz_line1": line1,
            "raw_mrz_line2": line2,
            "rescue_mode": rescue_mode,
        }

    except Exception:
        return None

def correct_image_rotation(image):
    if image is None:
        return image

    # keep simple and safe first
    h, w = image.shape[:2]
    if h > w * 1.35:
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    return image


def preprocess_passport_image(image_path, output_path):
    image = cv2.imread(image_path)
    if image is None:
        raise Exception("Failed to read uploaded passport image")

    image = correct_image_rotation(image)
    h, w = image.shape[:2]

    # light crop only
    cropped = image[int(h * 0.02):int(h * 0.98), int(w * 0.02):int(w * 0.98)]
    resized = cv2.resize(cropped, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    denoise = cv2.bilateralFilter(gray, 7, 50, 50)
    enhanced = cv2.convertScaleAbs(denoise, alpha=1.25, beta=10)

    cv2.imwrite(output_path, enhanced)

    blur_value = cv2.Laplacian(gray, cv2.CV_64F).var()
    image_quality_note = None
    if blur_value < 60:
        image_quality_note = "Image may be too blurry. Please upload a clearer passport image."

    return enhanced, image_quality_note


def extract_passport_data_from_text(text):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    upper_lines = [line.upper() for line in lines]
    full_upper = "\n".join(upper_lines)

    result = {
        'type': 'P',
        'full_name': '',
        'surname': '',
        'given_name': '',
        'passport_number': '',
        'country': '',
        'country_code': '',
        'nationality': '',
        'date_of_birth': '',
        'date_of_issue': '',
        'expiry_date': '',
        'gender': '',
        'sex': '',
        'registered_domicile': '',
        'issuing_authority': '',
    }

    # passport number visual fallback
    passport_match = re.search(r'\b[A-Z]{1,2}\d{6,8}\b', full_upper)
    if passport_match:
        result['passport_number'] = fix_common_ocr_errors(passport_match.group(0), mode="passport")

    # country code
    for code in COUNTRY_CODE_MAP.keys():
        if f" {code} " in f" {full_upper} ":
            result['country_code'] = code
            result['country'] = country_code_to_name(code)
            result['nationality'] = country_code_to_name(code)
            break

    # safer label parsing
    for i, line in enumerate(upper_lines):
        next_line = upper_lines[i + 1] if i + 1 < len(upper_lines) else ""

        if ('SURNAME' in line or 'S/SURNAME' in line) and next_line:
            candidate = re.sub(r'[^A-Z\s]', ' ', next_line).strip()
            candidate = re.sub(r'\s+', ' ', candidate)
            if candidate and len(candidate.split()) <= 3:
                result['surname'] = normalize_mrz_name(candidate)

        if ('GIVEN NAME' in line or 'G/GIVEN NAME' in line or 'GIVENNAME' in line) and next_line:
            candidate = re.sub(r'[^A-Z\s]', ' ', next_line).strip()
            candidate = re.sub(r'\s+', ' ', candidate)
            if candidate and len(candidate.split()) <= 4:
                result['given_name'] = normalize_mrz_name(candidate)

        if 'REGISTERED DOMICILE' in line and next_line:
            candidate = re.sub(r'[^A-Z\s]', ' ', next_line).strip()
            candidate = re.sub(r'\s+', ' ', candidate)
            if candidate:
                result['registered_domicile'] = normalize_mrz_name(candidate)

        if 'AUTHORITY' in line and next_line:
            candidate = re.sub(r'[^A-Z\s]', ' ', next_line).strip()
            candidate = re.sub(r'\s+', ' ', candidate)
            if candidate:
                result['issuing_authority'] = normalize_mrz_name(candidate)

    # dates visible area
    dates = re.findall(r'\b\d{1,2}\s+[A-Z]{3}\s+\d{4}\b', full_upper)
    unique_dates = []
    for d in dates:
        if d not in unique_dates:
            unique_dates.append(d)

    if len(unique_dates) >= 1:
        result['date_of_birth'] = unique_dates[0]
    if len(unique_dates) >= 2:
        result['date_of_issue'] = unique_dates[1]
    if len(unique_dates) >= 3:
        result['expiry_date'] = unique_dates[2]

    # sex visual fallback
    if re.search(r'\bSEX\b', full_upper):
        if re.search(r'\bF\b', full_upper):
            result['gender'] = 'Female'
            result['sex'] = 'Female'
        elif re.search(r'\bM\b', full_upper):
            result['gender'] = 'Male'
            result['sex'] = 'Male'

    if not result['issuing_authority'] and 'MINISTRY OF FOREIGN AFFAIRS' in full_upper:
        result['issuing_authority'] = 'Ministry of Foreign Affairs'

    result['full_name'] = f"{result['surname']} {result['given_name']}".strip()

    return result

def merge_passport_results(mrz_result, visual_result):
    final_result = {}

    mrz_result = mrz_result or {}
    visual_result = visual_result or {}

    # MRZ first for reliable fields
    final_result["type"] = mrz_result.get("type") or visual_result.get("type") or "P"
    final_result["passport_number"] = mrz_result.get("passport_number") or visual_result.get("passport_number", "")
    final_result["country"] = mrz_result.get("country") or visual_result.get("country", "")
    final_result["country_code"] = mrz_result.get("country_code") or visual_result.get("country_code", "")
    final_result["nationality"] = mrz_result.get("nationality") or visual_result.get("nationality", "")
    final_result["nationality_code"] = mrz_result.get("nationality_code") or visual_result.get("nationality_code", "")
    final_result["date_of_birth"] = mrz_result.get("date_of_birth") or visual_result.get("date_of_birth", "")
    final_result["expiry_date"] = mrz_result.get("expiry_date") or visual_result.get("expiry_date", "")
    final_result["sex"] = mrz_result.get("sex") or visual_result.get("sex", "")
    final_result["gender"] = mrz_result.get("gender") or visual_result.get("gender", "")

    # Name: use MRZ split if available
    final_result["surname"] = mrz_result.get("surname") or visual_result.get("surname", "")
    final_result["given_name"] = mrz_result.get("given_name") or visual_result.get("given_name", "")

    # visual-only fields
    final_result["date_of_issue"] = visual_result.get("date_of_issue", "")
    final_result["registered_domicile"] = visual_result.get("registered_domicile", "")
    final_result["issuing_authority"] = visual_result.get("issuing_authority", "")

    final_result["full_name"] = f"{final_result.get('surname', '')} {final_result.get('given_name', '')}".strip()

    # keep raw / score info
    final_result["mrz_valid_score"] = mrz_result.get("mrz_valid_score", 0)
    final_result["mrz_total_checks"] = mrz_result.get("mrz_total_checks", 0)
    final_result["raw_mrz_line1"] = mrz_result.get("raw_mrz_line1", "")
    final_result["raw_mrz_line2"] = mrz_result.get("raw_mrz_line2", "")
    final_result["rescue_mode"] = mrz_result.get("rescue_mode", False)

    return final_result

def score_extraction_result(result):
    if not result:
        return -1

    score = 0

    if result.get("passport_number"):
        score += 4
    if result.get("surname"):
        score += 3
    if result.get("given_name"):
        score += 3
    if result.get("nationality"):
        score += 2
    if result.get("date_of_birth"):
        score += 2
    if result.get("expiry_date"):
        score += 2
    if result.get("sex"):
        score += 1
    if result.get("date_of_issue"):
        score += 1
    if result.get("registered_domicile"):
        score += 1
    if result.get("issuing_authority"):
        score += 1

    score += result.get("mrz_valid_score", 0) * 6
    score += int(result.get("avg_confidence", 0) * 5)

    # penalize obvious junk
    for field in ["passport_number", "surname", "given_name", "nationality"]:
        val = str(result.get(field, "")).strip().upper()
        if val and re.search(r'\d{3,}', val):
            score -= 3

    return score

def run_paddleocr_retry_variants(input_img):
    results = []
    unique = uuid.uuid4().hex

    # Full passport OCR for visual fields
    full_lines = paddleocr_lines_from_image(input_img, f"full_passport_{unique}.jpg")
    full_text = "\n".join([x["text"] for x in full_lines])
    full_avg = sum([x["score"] for x in full_lines]) / len(full_lines) if full_lines else 0

    visual_result = extract_passport_data_from_text(full_text)
    visual_result["raw_text"] = full_text
    visual_result["avg_confidence"] = full_avg

    # MRZ variants
    for filename, candidate_img in get_mrz_variants(input_img):
        mrz_lines = paddleocr_lines_from_image(candidate_img, filename)
        mrz_text = "\n".join([x["text"] for x in mrz_lines])
        mrz_avg = sum([x["score"] for x in mrz_lines]) / len(mrz_lines) if mrz_lines else 0

        mrz_data = extract_mrz_data(mrz_text)
        if mrz_data:
            merged = merge_passport_results(mrz_data, visual_result)
            merged["raw_text"] = full_text
            merged["avg_confidence"] = max(mrz_avg, full_avg)
            results.append(merged)

    # rescue from full text
    rescue_full = parse_mrz_rescue(full_text)
    if rescue_full:
        merged_rescue = merge_passport_results(rescue_full, visual_result)
        merged_rescue["raw_text"] = full_text
        merged_rescue["avg_confidence"] = full_avg
        results.append(merged_rescue)

    # visual only fallback
    visual_result["raw_text"] = full_text
    results.append(visual_result)

    if not results:
        return visual_result, score_extraction_result(visual_result)

    best_result = max(results, key=score_extraction_result)
    best_score = score_extraction_result(best_result)
    return best_result, best_score

def process_passport_ocr(image_path, processed_path):
    image_quality_note = None

    original_img = cv2.imread(image_path)
    if original_img is None:
        raise Exception("Failed to read uploaded passport image")

    original_img = correct_image_rotation(original_img)

    best_result, best_score = run_paddleocr_retry_variants(original_img)

    processed_img, image_quality_note = preprocess_passport_image(image_path, processed_path)
    processed_result, processed_score = run_paddleocr_retry_variants(processed_img)

    if processed_score > best_score:
        best_result = processed_result
        best_score = processed_score

    if not best_result:
        raise Exception("OCR could not detect any text from the passport image")

    status = 'pending verification'
    if best_result.get("mrz_valid_score", 0) >= 2:
        status = 'auto-extracted'

    best_result['status'] = status
    best_result['image_quality_note'] = image_quality_note
    best_result['confidence_score'] = best_score
    best_result['date_of_birth'] = normalize_date_for_html(best_result.get('date_of_birth'))
    best_result['date_of_issue'] = normalize_date_for_html(best_result.get('date_of_issue'))
    best_result['expiry_date'] = normalize_date_for_html(best_result.get('expiry_date'))

    return best_result

def paddleocr_lines_from_image(image, temp_name=None):
    lines = []

    try:
        ensure_media_dirs()

        if not temp_name:
            temp_name = f"temp_{uuid.uuid4().hex}.jpg"

        temp_path = os.path.join(settings.MEDIA_ROOT, "passport_processed", temp_name)

        if isinstance(image, np.ndarray):
            cv2.imwrite(temp_path, image)
            predict_input = temp_path
        else:
            predict_input = image

        # TRY 1: predict()
        try:
            with PADDLE_OCR_LOCK:
                result = PADDLE_OCR.predict(input=predict_input)

            for item in result:
                item_json = None

                if hasattr(item, "json"):
                    raw_json = item.json
                    if isinstance(raw_json, str):
                        try:
                            item_json = json.loads(raw_json)
                        except Exception:
                            item_json = None
                    elif isinstance(raw_json, dict):
                        item_json = raw_json
                elif isinstance(item, dict):
                    item_json = item

                if not item_json:
                    continue

                rec_texts = item_json.get("rec_texts", []) or []
                rec_scores = item_json.get("rec_scores", []) or []

                for i, txt in enumerate(rec_texts):
                    score = rec_scores[i] if i < len(rec_scores) else 0.0
                    if txt and str(txt).strip():
                        lines.append({
                            "text": str(txt).strip(),
                            "score": float(score) if score is not None else 0.0
                        })
        except Exception:
            pass

        # TRY 2: ocr() fallback
        if not lines:
            try:
                with PADDLE_OCR_LOCK:
                    ocr_result = PADDLE_OCR.ocr(predict_input, cls=False)

                if isinstance(ocr_result, list):
                    for block in ocr_result:
                        if not block:
                            continue

                        for line in block:
                            if isinstance(line, list) and len(line) >= 2:
                                rec_part = line[1]

                                if isinstance(rec_part, (list, tuple)) and len(rec_part) >= 2:
                                    text = rec_part[0]
                                    score = rec_part[1]

                                    if text and str(text).strip():
                                        lines.append({
                                            "text": str(text).strip(),
                                            "score": float(score) if score is not None else 0.0
                                        })
            except Exception:
                pass

        # TRY 3: TESSERACT fallback
        if not lines:
            try:
                if isinstance(image, np.ndarray):
                    text = pytesseract.image_to_string(image)
                else:
                    text = pytesseract.image_to_string(cv2.imread(predict_input))

                if text and text.strip():
                    for row in text.split("\n"):
                        row = row.strip()
                        if row:
                            lines.append({
                                "text": row,
                                "score": 0.5
                            })
            except Exception:
                pass

    except Exception:
        return []

    return lines

def extract_mrz_data(text):
    text = fix_common_ocr_errors(text, mode="mrz")
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    normalized = []
    for line in lines:
        clean_line = re.sub(r'[^A-Z0-9<]', '', line.upper())
        if len(clean_line) >= 25:
            normalized.append(clean_line)

    # try adjacent pairs
    for i in range(len(normalized) - 1):
        parsed = parse_two_line_passport_mrz(normalized[i], normalized[i + 1])
        if parsed:
            return parsed

    rescue = parse_mrz_rescue(text)
    if rescue:
        return rescue

    return None


def crop_mrz_region(image):
    h, w = image.shape[:2]
    return image[int(h * 0.72):h, 0:w]

def get_mrz_variants(image):
    mrz = crop_mrz_region(image)
    unique = uuid.uuid4().hex

    variants = []

    variants.append((f"mrz_raw_{unique}.jpg", mrz))

    gray = cv2.cvtColor(mrz, cv2.COLOR_BGR2GRAY) if len(mrz.shape) == 3 else mrz
    variants.append((f"mrz_gray_{unique}.jpg", gray))

    big = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    variants.append((f"mrz_big_{unique}.jpg", big))

    _, thresh = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append((f"mrz_thresh_{unique}.jpg", thresh))

    inv = cv2.bitwise_not(thresh)
    variants.append((f"mrz_inv_{unique}.jpg", inv))

    return variants

def passport_attendance_page(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    return render(request, 'passport_attendance_form.html', {
        'event': event,
        'country_choices': get_country_choices(),
    })


@csrf_exempt
def upload_passport(request):
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Invalid request method'}, status=400)

        if 'image' not in request.FILES:
            return JsonResponse({'error': 'Please choose a passport image first'}, status=400)

        ensure_media_dirs()

        image = request.FILES['image']
        ext = os.path.splitext(image.name)[1].lower() or ".jpg"
        unique_id = uuid.uuid4().hex

        original_filename = f"passport_{unique_id}{ext}"
        processed_filename = f"processed_{unique_id}.jpg"

        original_path = os.path.join(settings.MEDIA_ROOT, 'passport_images', original_filename)
        processed_path = os.path.join(settings.MEDIA_ROOT, 'passport_processed', processed_filename)

        with open(original_path, 'wb+') as f:
            for chunk in image.chunks():
                f.write(chunk)

        extracted = process_passport_ocr(original_path, processed_path)
        ui_result = build_universal_passport_fields(extracted)

        status = extracted.get('status', 'pending verification')
        if not extracted.get('passport_number'):
            status = 'pending verification'

        return JsonResponse({
            'message': 'Passport scanned successfully',
            'type': ui_result.get('type', 'P'),
            'country_code': ui_result.get('country_code', ''),
            'passport_number': ui_result.get('passport_number', ''),
            'nationality': ui_result.get('nationality', ''),
            'surname': ui_result.get('surname', ''),
            'given_name': ui_result.get('given_name', ''),
            'date_of_birth': ui_result.get('date_of_birth', ''),
            'sex': ui_result.get('sex', ''),
            'date_of_issue': ui_result.get('date_of_issue', ''),
            'date_of_expiry': ui_result.get('date_of_expiry', ''),
            'dynamic_fields': ui_result.get('dynamic_fields', []),

            'full_name': extracted.get('full_name', ''),
            'country': extracted.get('country', ''),
            'gender': extracted.get('gender', extracted.get('sex', '')),
            'expiry_date': extracted.get('expiry_date', ''),
            'raw_text': extracted.get('raw_text', ''),
            'image_quality_note': extracted.get('image_quality_note', ''),
            'status': status,
            'confidence_score': extracted.get('confidence_score', 0),

            'original_image_name': original_filename,
            'processed_image_name': processed_filename,
            'original_image_url': f"{settings.MEDIA_URL}passport_images/{original_filename}",
            'processed_image_url': f"{settings.MEDIA_URL}passport_processed/{processed_filename}",
        })

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'status': 'pending verification'
        }, status=500)

@csrf_exempt
def submit_passport_attendance(request, event_id):
    try:
        if request.method != 'POST':
            return JsonResponse({'error': 'Invalid request'}, status=400)

        data = json.loads(request.body)

        passport_type = (data.get('type') or 'P').strip()
        country_code = (data.get('country_code') or '').strip().upper()
        passport_number = fix_common_ocr_errors(data.get('passport_number', ''), mode="passport")
        nationality = (data.get('nationality') or '').strip()
        surname = (data.get('surname') or '').strip()
        given_name = (data.get('given_name') or '').strip()
        full_name = f"{surname} {given_name}".strip()
        date_of_birth = (data.get('date_of_birth') or '').strip()
        sex = (data.get('sex') or data.get('gender') or '').strip()
        date_of_issue = (data.get('date_of_issue') or '').strip()
        date_of_expiry = (data.get('date_of_expiry') or data.get('expiry_date') or '').strip()
        raw_text = (data.get('raw_text') or '').strip()
        status = (data.get('status') or 'pending verification').strip()

        original_image_name = (data.get('original_image_name') or '').strip()
        processed_image_name = (data.get('processed_image_name') or '').strip()

        latitude = data.get('latitude')
        longitude = data.get('longitude')

        dynamic_fields = data.get('dynamic_fields', [])
        if not isinstance(dynamic_fields, list):
            dynamic_fields = []

        if not passport_number:
            return JsonResponse({'error': 'Passport number cannot be empty'}, status=400)

        valid, passport_error = validate_passport_number_by_country(passport_number, country_code or nationality)
        if not valid:
            return JsonResponse({'error': passport_error}, status=400)

        if latitude in [None, ''] or longitude in [None, '']:
            return JsonResponse({'error': 'Please enable GPS/location first'}, status=400)

        event = get_object_or_404(Event, id=event_id)

        if event.latitude is None or event.longitude is None:
            return JsonResponse({'error': 'Event location not configured by admin'}, status=400)

        distance = calculate_distance_meters(latitude, longitude, event.latitude, event.longitude)

        if distance > event.radius_meter:
            return JsonResponse({
                'error': f'Attendance rejected. Outside allowed area ({round(distance, 2)}m)'
            }, status=400)

        visitor, created = PassportVisitor.objects.get_or_create(
            passport_number=passport_number,
            defaults={
                'full_name': full_name or passport_number,
                'country': nationality or country_code_to_name(country_code),
                'date_of_birth': date_of_birth,
                'expiry_date': date_of_expiry,
                'gender': sex,
                'ocr_raw_text': raw_text,
                'status': status or 'pending verification',
                'extra_data': {
                    'type': passport_type,
                    'country_code': country_code,
                    'nationality': nationality,
                    'surname': surname,
                    'given_name': given_name,
                    'date_of_issue': date_of_issue,
                }
            }
        )

        if not created:
            visitor.full_name = full_name or visitor.full_name
            visitor.country = nationality or country_code_to_name(country_code) or visitor.country
            visitor.date_of_birth = date_of_birth or visitor.date_of_birth
            visitor.expiry_date = date_of_expiry or visitor.expiry_date
            visitor.gender = sex or visitor.gender
            visitor.ocr_raw_text = raw_text or visitor.ocr_raw_text

            if status:
                visitor.status = status

            merged_extra = visitor.extra_data or {}
            merged_extra.update({
                'type': passport_type,
                'country_code': country_code,
                'nationality': nationality,
                'surname': surname,
                'given_name': given_name,
                'date_of_issue': date_of_issue,
            })

            for item in dynamic_fields:
                key = (item.get('key') or '').strip()
                value = item.get('value')
                if key:
                    merged_extra[key] = value

            visitor.extra_data = merged_extra

        else:
            extra_data = visitor.extra_data or {}
            for item in dynamic_fields:
                key = (item.get('key') or '').strip()
                value = item.get('value')
                if key:
                    extra_data[key] = value
            visitor.extra_data = extra_data

        if original_image_name and not visitor.image:
            original_path = os.path.join(settings.MEDIA_ROOT, 'passport_images', original_image_name)
            if os.path.exists(original_path):
                with open(original_path, 'rb') as f:
                    visitor.image.save(original_image_name, File(f), save=False)

        if processed_image_name and not visitor.extracted_image:
            processed_path = os.path.join(settings.MEDIA_ROOT, 'passport_processed', processed_image_name)
            if os.path.exists(processed_path):
                with open(processed_path, 'rb') as f:
                    visitor.extracted_image.save(processed_image_name, File(f), save=False)

        visitor.save()

        attendance, attendance_created = PassportAttendance.objects.get_or_create(
            passport_visitor=visitor,
            event=event,
            defaults={
                'latitude': latitude,
                'longitude': longitude
            }
        )

        if not attendance_created:
            return JsonResponse({'error': 'You have already registered for this event'}, status=400)

        return JsonResponse({
            'message': 'Successfully Registered',
            'distance_meter': round(distance, 2),
            'event': event.name,
            'status': visitor.status
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def mrz_char_value(c):
    if c.isdigit():
        return int(c)
    if 'A' <= c <= 'Z':
        return ord(c) - 55
    if c == '<':
        return 0
    return 0


def mrz_check_digit(data):
    weights = [7, 3, 1]
    total = 0
    for i, char in enumerate(data):
        total += mrz_char_value(char) * weights[i % 3]
    return str(total % 10)

def build_universal_passport_fields(extracted):
    dynamic_fields = []

    result = {
        "type": extracted.get("type", "P"),
        "country_code": extracted.get("country_code", extracted.get("nationality_code", "")),
        "passport_number": extracted.get("passport_number", ""),
        "surname": extracted.get("surname", ""),
        "given_name": extracted.get("given_name", ""),
        "nationality": extracted.get("nationality", extracted.get("country", "")),
        "date_of_birth": normalize_date_for_html(extracted.get("date_of_birth")),
        "sex": extracted.get("sex", extracted.get("gender", "")),
        "date_of_issue": normalize_date_for_html(extracted.get("date_of_issue")),
        "date_of_expiry": normalize_date_for_html(extracted.get("expiry_date")),
    }

    if extracted.get("registered_domicile"):
        dynamic_fields.append({
            "key": "registered_domicile",
            "label": "Registered Domicile",
            "type": "text",
            "value": extracted.get("registered_domicile", "")
        })

    if extracted.get("issuing_authority"):
        dynamic_fields.append({
            "key": "issuing_authority",
            "label": "Issuing Authority",
            "type": "text",
            "value": extracted.get("issuing_authority", "")
        })

    result["dynamic_fields"] = dynamic_fields
    return result

def merge_passport_results(primary_result, fallback_result):
    if not primary_result:
        return fallback_result or {}

    final_result = dict(primary_result)

    fields_from_fallback = [
        "surname",
        "given_name",
        "full_name",
        "date_of_issue",
        "registered_domicile",
        "issuing_authority",
        "country_code",
        "nationality",
    ]

    for field in fields_from_fallback:
        if not final_result.get(field) and fallback_result.get(field):
            final_result[field] = fallback_result.get(field)

    if not final_result.get("full_name"):
        final_result["full_name"] = f"{final_result.get('surname', '')} {final_result.get('given_name', '')}".strip()

    return final_result