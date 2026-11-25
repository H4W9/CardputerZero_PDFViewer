@echo off
rem Copy the newest PDF Viewer .deb to the Cardputer Zero and install it.
rem   tools\deploy.cmd DEVICE_IP USER
setlocal
if "%~2"=="" (echo usage: tools\deploy.cmd DEVICE_IP USER & exit /b 1)
set IP=%~1
set USR=%~2
cd /d "%~dp0.."
for /f "delims=" %%f in ('dir /b /o-d dist\czpdf_*.deb') do (set DEB=%%f & goto :found)
echo no .deb in dist\ - run: python tools\build_deb.py & exit /b 1
:found
set DEB=%DEB: =%
scp "dist\%DEB%" %USR%@%IP%:~/ || exit /b 1
ssh -t %USR%@%IP% "sudo apt install -y ./%DEB%"
