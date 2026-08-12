@echo off
timeout 3
set /p VERSION=Version (e.g. 0.1.3):
if "%VERSION%"=="" (echo Version cannot be empty & exit /b 1)

set "V1=" & set "V2=" & set "V3=" & set "V4="
for /f "tokens=1,2,3,4 delims=." %%a in ("%VERSION%") do (
    set "V1=%%a" & set "V2=%%b" & set "V3=%%c" & set "V4=%%d"
)
if not "%V4%"=="" goto :badversion
if "%V1%"=="" goto :badversion
if "%V2%"=="" goto :badversion
if "%V3%"=="" goto :badversion
if not "%V1:~2%"=="" goto :badversion
if not "%V2:~2%"=="" goto :badversion
if not "%V3:~2%"=="" goto :badversion
echo %V1%%V2%%V3%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 goto :badversion
goto :versionok

:badversion
echo Invalid version "%VERSION%" - expected format N.N.N with 1-2 digit numbers (e.g. 1.2.3 or 12.34.5)
exit /b 1

:versionok
echo %VERSION%> version
rmdir /s /q build dist 2>nul
python -m PyInstaller --noconfirm --clean Atelier.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
xcopy /E /I /Y Tools dist\Atelier\Tools
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" Atelier.iss /DAppVersion=%VERSION%
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
