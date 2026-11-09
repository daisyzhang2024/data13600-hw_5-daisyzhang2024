"""
views.py — HTTP request handlers for AttendanceChimp.

Each view corresponds to one URL endpoint.  Views receive an HTTP request,
interact with the database via models.py, and return an HTTP response.
"""

from django.shortcuts import render, redirect
from django.http import (HttpResponse, HttpResponseForbidden,
                         HttpResponseBadRequest, JsonResponse)
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login
from datetime import datetime
from django.utils import timezone
import zoneinfo
import json
import io

from .models import (InstructorProfile, StudentProfile, Course, Enrollment,
                     Lecture, QRCodeUpload, is_instructor, is_student)

CDT = zoneinfo.ZoneInfo("America/Chicago")


# ---------------------------------------------------------------------------
# HW2 — time, sum 
# ---------------------------------------------------------------------------

@csrf_exempt
def time_view(request):
    """Return the current Chicago time as HH:MM."""
    if request.method != "GET":
        return HttpResponse("Error: only GET is allowed", status=405)
    now = datetime.now().astimezone(CDT)
    return HttpResponse(now.strftime("%H:%M"))


@csrf_exempt
def sum_view(request):
    """Return the sum of query parameters n1 and n2."""
    if request.method != "GET":
        return HttpResponse("Error: only GET is allowed", status=405)
    try:
        n1 = float(request.GET['n1'])
        n2 = float(request.GET['n2'])
    except (KeyError, ValueError):
        return HttpResponse("Error: provide numeric n1 and n2", status=400)
    result = n1 + n2
    if result == int(result):
        return HttpResponse(str(int(result)))
    return HttpResponse(str(result))


# ---------------------------------------------------------------------------
# HW4  — index, user creation
# ---------------------------------------------------------------------------

def new(request):
    """Render the sign-up form (GET only)."""
    if request.method != "GET":
        return HttpResponse("Error: only GET is allowed", status=405)
    return render(request, 'app/new.html')

def index(request):
    """Render the home page (index.html)."""
    now = datetime.now().astimezone(CDT)
    context = {
        'current_time': now.strftime("%H:%M"),
        'user': request.user,
    }
    return render(request, 'app/index.html', context)

@csrf_exempt
def createUser(request):
    """Create a new student or instructor user (POST only)."""
    if request.method != "POST":
        return HttpResponse("Error: only POST is allowed", status=405)
    try:
        user_name = request.POST['user_name']
        password = request.POST['password']
        email = request.POST['email']
        is_student_flag = request.POST.get('is_student', '1')
    except KeyError:
        return HttpResponse("Error: missing required fields", status=400)

    if User.objects.filter(email=email).exists():
        return HttpResponse("Error: email already in use", status=400)
    if User.objects.filter(username=user_name).exists():
        return HttpResponse("Error: user name already in use", status=400)

    user = User.objects.create_user(username=user_name, password=password,
                                    email=email)
    if str(is_student_flag) in ('1', 'true', 'True', 'on'):
        StudentProfile.objects.create(user=user)
    else:
        InstructorProfile.objects.create(user=user)

    user = authenticate(username=user_name, password=password)
    if user is not None:
        login(request, user)
    return HttpResponse("User created successfully", status=200)

def _is_logged_in_instructor(user):
    return user.is_authenticated and is_instructor(user)

def _is_logged_in_student(user):
    return user.is_authenticated and is_student(user)

def _parse_time(value):
    """Accept '10:30', '10:30:00', or '10:30 AM'. Return a time or None."""
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(value.strip(), fmt).time()
        except (ValueError, AttributeError):
            continue
    return None

def new_course(request):
    return render(request, 'app/new_course.html')

def new_lecture(request):
    return render(request, 'app/new_lecture.html',
                  {'courses': Course.objects.all()})

def new_qr_upload(request):
    return render(request, 'app/new_qr_upload.html')

@csrf_exempt
def createCourse(request):
    """Create a Course (POST, instructor only)."""
    if not _is_logged_in_instructor(request.user):
        return HttpResponse("Error: instructors only", status=401)
    if request.method != "POST":
        return HttpResponse("Error: only POST is allowed", status=405)

    name = request.POST.get('course-name', '').strip()
    start = _parse_time(request.POST.get('start-time', ''))
    end = _parse_time(request.POST.get('end-time', ''))
    days = {d: (f'day-{d}' in request.POST)
            for d in ('mon', 'tue', 'wed', 'thu', 'fri')}

    if not name or start is None or end is None:
        return HttpResponse("Error: missing or invalid fields", status=400)
    if not any(days.values()):
        return HttpResponse("Error: select at least one day", status=400)
    if Course.objects.filter(name=name).exists():          # CHECK field name
        return HttpResponse("Error: course name already exists", status=400)

    instructor = InstructorProfile.objects.get(user=request.user)
    Course.objects.create(
        name=name,
        instructor=request.user,
        start_time=start,
        end_time=end,
        day_mon=days['mon'],
        day_tue=days['tue'],
        day_wed=days['wed'],
        day_thu=days['thu'],
        day_fri=days['fri'],
    )
    return HttpResponse("Course created successfully", status=200)


@csrf_exempt
def createLecture(request):
    """Create a Lecture for an existing course (POST, instructor only)."""
    if not _is_logged_in_instructor(request.user):
        return HttpResponse("Error: instructors only", status=401)
    if request.method != "POST":
        return HttpResponse("Error: only POST is allowed", status=405)

    course_name = request.POST.get('choice', '').strip()
    course = Course.objects.filter(name=course_name).first()  # CHECK field name
    if course is None:
        return HttpResponse("Error: course not found", status=404)

    Lecture.objects.create(course=course)  # CHECK: add any other required fields
    return HttpResponse("Lecture created successfully", status=200)


@csrf_exempt
def createQRCodeUpload(request):
    """Save a QR code image upload (POST, student only)."""
    if not _is_logged_in_student(request.user):
        return HttpResponse("Error: students only", status=401)
    if request.method != "POST":
        return HttpResponse("Error: only POST is allowed", status=405)

    image = request.FILES.get('imageUpload')
    if image is None:
        return HttpResponse("Error: no file uploaded", status=400)

    student = StudentProfile.objects.get(user=request.user)
    QRCodeUpload.objects.create(student=request.user, image=image)
    return HttpResponse("Upload saved successfully", status=200)


def dumpUploads(request):
    """Return all uploads as JSON (GET, instructor only)."""
    if not _is_logged_in_instructor(request.user):
        return HttpResponse("Error: instructors only", status=401)
    if request.method != "GET":
        return HttpResponse("Error: only GET is allowed", status=405)

    data = []
    for upload in QRCodeUpload.objects.select_related('student'):
        t = upload.uploaded_at
        if timezone.is_aware(t):
            t = t.astimezone(CDT)
        data.append({
            "username": upload.student.username,
            "upload_time": t.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return JsonResponse(data, safe=False)