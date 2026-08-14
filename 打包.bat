@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  微信公众号OCR采集器 - 打包脚本
echo ============================================
echo.

echo [1/3] 正在用 PyInstaller 打包...
pyinstaller 微信公众号OCR采集器.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [错误] 打包失败,请查看上方报错信息
    pause
    exit /b 1
)

echo.
echo [2/3] 整理产物到 release 目录...
if not exist release mkdir release
copy /Y "dist\微信公众号OCR采集器.exe" "release\微信公众号OCR采集器.exe" >nul
if exist config xcopy /E /I /Y "config" "release\config" >nul
if exist README.md copy /Y "README.md" "release\README.md" >nul

echo.
echo [3/3] 打包完成!
echo 产物位置: %~dp0release\
echo.
start "" "release"
pause
