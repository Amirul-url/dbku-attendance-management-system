# DBKU Attendance Management System

## 📌 Project Overview
DBKU Attendance Management System is a web-based system developed to manage staff attendance and event participation efficiently.

The system allows administrators to register staff, manage events, and track attendance using QR code scanning, while also supporting attendance registration for external participants.

---

## 🎯 Objectives
- Staff registration (MyKad / Manual)
- Secure login system
- Admin dashboard with key information
- QR Code-based attendance tracking
- Event management module
- External participant registration
- Geolocation & Geofencing validation
- Passport registration for non-Malaysians using OCR

---

## 🧩 Features

### 👥 Staff Management
- Register staff manually or via MyKad (simulation)
- Store employee details (name, ID, email, department)

### 🔐 Authentication
- Secure login system
- Password validation

### 📊 Admin Dashboard
- Staff list
- Event list
- Attendance records
- Basic analytics

### 📅 Event Management
- Create, update, and manage events
- Assign staff to events

### 📷 QR Code Attendance
- Generate QR codes for events
- Scan QR to record attendance
- Prevent duplicate attendance

### 🌍 Geolocation & Geofencing
- Capture user location during attendance
- Validate within event radius

### 🪪 Passport Registration (OCR)
- Upload or capture passport image
- Extract passport data using OCR
- Manual correction if needed
- Store extracted data and image

---

## 🛠️ Tech Stack

### Frontend
- HTML
- JavaScript
- Tailwind CSS

### Backend
- Django (Python)

### Database
- PostgreSQL

### Libraries / Tools
- OpenCV (Image Processing)
- OCR Engine (PaddleOCR / Tesseract)
- Chart.js (Analytics)
- QR Code Generator

---

## 🚀 How to Run

1. Clone the repository
```bash
git clone https://github.com/Amirul-url/dbku-attendance-management-system.git