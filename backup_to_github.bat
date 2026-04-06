@echo off
cd /d D:\dbku_attendance_project_v2

for /f "tokens=1-3 delims=/" %%a in ("%date%") do set mydate=%%c-%%b-%%a
for /f "tokens=1-2 delims=:." %%a in ("%time%") do set mytime=%%a-%%b

git add .
git commit -m "auto backup %mydate% %mytime%"
git push

pause