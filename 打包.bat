@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  微信公众号OCR采集器 - 打包脚本
echo ============================================
echo.

rem 从 main.py 自动读取版本号（如 V1.1.4）
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION" main.py') do set VER=%%v
set VER=%VER:"=%
if "%VER%"=="" set VER=unknown
echo 当前版本: %VER%
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
rem 清理旧的版本化 exe,避免多个版本残留
del /Q "release\微信公众号OCR采集器_*.exe" >nul 2>&1
copy /Y "dist\微信公众号OCR采集器.exe" "release\微信公众号OCR采集器_%VER%.exe" >nul
if exist config xcopy /E /I /Y "config" "release\config" >nul
if exist README.md copy /Y "README.md" "release\README.md" >nul

echo.
echo [3/3] 打包完成!
echo 产物位置: %~dp0release\微信公众号OCR采集器_%VER%.exe
echo.
start "" "release"
pause
