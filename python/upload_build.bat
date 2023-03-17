@echo off

set /p tarball="tarball/path:"
for %%f in ("%tarball%") do (
    set filename=%%~nf
    set extname=%%~xf
)

set isComprFile="false"
if "%extname%" == ".gz" (
    set isComprFile="true"
) else (
    if "%extname%" == ".zip" (
        set isComprFile="true"
    )
)

set cosdir=""
if %isComprFile% == "false" (
    set /p cosdir="cosdir:"
)

set isSilent=
:SILENT
set /p silent="是否通知到飞书[y/n]:"
if "%silent%"=="y" goto ENDSILENT
if "%silent%"=="n" (
    set isSilent=--silent
    goto ENDSILENT
)
echo 输入错误,请选择y或n
goto SILENT

:ENDSILENT

set isPush=
:LOOP
set /p push="是否预热CDN[y/n]:"
if "%push%"=="y" (
    set isPush=--push
    goto UPLOAD
)
if "%push%"=="n" goto UPLOAD
echo 输入错误,请选择y或n
goto LOOP

:UPLOAD
.\upload.exe --bucket=xxxx --tarball=%tarball% --platform=domestic --cosdir=%cosdir%  %isSilent% %isPush%

pause
