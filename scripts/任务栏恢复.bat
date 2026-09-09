@echo off
chcp 65001 >nul
title 任务栏恢复
echo ============================================
echo   任务栏恢复工具
echo   用于采集/自动设置异常后, 手动恢复Windows任务栏
echo ============================================
echo.

rem 方案1: 直接向任务栏窗口发送 SW_SHOW(5)
powershell -NoProfile -Command ^
  "Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class Tb{[DllImport(\"user32.dll\")]public static extern IntPtr FindWindow(string c,string n);[DllImport(\"user32.dll\")]public static extern bool ShowWindow(IntPtr h,int s);}'; $h=[Tb]::FindWindow('Shell_TrayWnd',$null); if($h -ne [IntPtr]::Zero){ [void][Tb]::ShowWindow($h,5); Write-Host '  [OK] 已发送恢复任务栏指令' } else { Write-Host '  [!] 未找到任务栏窗口' }"

echo.
echo 若任务栏仍未恢复, 请尝试:
echo   1) 右键桌面选择"刷新", 或
echo   2) 打开任务管理器(Ctrl+Shift+Esc) -^> 详细信息 -^> 重启"Windows 资源管理器"
echo.
pause