# Скрипт для открытия порта Flask в Windows Firewall
# Запустите от имени администратора: правый клик → "Запуск от имени администратора"

Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Открытие порта для AGM Backend" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# Проверка прав администратора
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "❌ Ошибка: Требуются права администратора!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Запустите PowerShell от имени администратора:" -ForegroundColor Yellow
    Write-Host "1. Найдите PowerShell в меню Пуск" -ForegroundColor Yellow
    Write-Host "2. Правый клик → Запуск от имени администратора" -ForegroundColor Yellow
    Write-Host "3. Запустите этот скрипт снова" -ForegroundColor Yellow
    Write-Host ""
    Pause
    Exit 1
}

Write-Host "✅ Права администратора подтверждены" -ForegroundColor Green
Write-Host ""

# Порт для Flask
$port = 5000
$ruleName = "AGM Backend (Flask)"

# Проверка существующего правила
Write-Host "🔍 Проверка существующих правил..." -ForegroundColor Yellow
$existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue

if ($existingRule) {
    Write-Host "⚠️  Правило '$ruleName' уже существует" -ForegroundColor Yellow
    $response = Read-Host "Пересоздать правило? (y/n)"
    
    if ($response -eq "y" -or $response -eq "Y") {
        Write-Host "🗑️  Удаление старого правила..." -ForegroundColor Yellow
        Remove-NetFirewallRule -DisplayName $ruleName
        Write-Host "✅ Старое правило удалено" -ForegroundColor Green
    } else {
        Write-Host "ℹ️  Используется существующее правило" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Порт $port уже открыт!" -ForegroundColor Green
        Write-Host ""
        Pause
        Exit 0
    }
}

# Создание нового правила
Write-Host ""
Write-Host "🔧 Создание правила брандмауэра..." -ForegroundColor Yellow
Write-Host "   Имя: $ruleName" -ForegroundColor Gray
Write-Host "   Порт: $port (TCP)" -ForegroundColor Gray
Write-Host "   Направление: Входящие подключения" -ForegroundColor Gray

try {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -LocalPort $port `
        -Protocol TCP `
        -Action Allow `
        -Profile Any `
        -Description "Разрешает входящие подключения для AGM Backend сервера на порту $port" `
        | Out-Null
    
    Write-Host "✅ Правило успешно создано!" -ForegroundColor Green
} catch {
    Write-Host "❌ Ошибка создания правила: $_" -ForegroundColor Red
    Pause
    Exit 1
}

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  Настройка завершена!" -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# Получение локального IP
Write-Host "📡 Ваш локальный IP-адрес:" -ForegroundColor Cyan
try {
    $ipAddress = (Get-NetIPAddress -AddressFamily IPv4 | 
                  Where-Object {$_.InterfaceAlias -like "*Wi-Fi*" -or $_.InterfaceAlias -like "*Ethernet*"} |
                  Where-Object {$_.IPAddress -notlike "169.*"} |
                  Select-Object -First 1).IPAddress
    
    if ($ipAddress) {
        Write-Host ""
        Write-Host "   🌐 http://$ipAddress:$port" -ForegroundColor Green
        Write-Host ""
        Write-Host "Откройте этот адрес на другом устройстве в сети!" -ForegroundColor Yellow
    } else {
        Write-Host "   ⚠️  IP-адрес не найден" -ForegroundColor Yellow
        Write-Host "   Используйте команду 'ipconfig' для просмотра IP" -ForegroundColor Gray
    }
} catch {
    Write-Host "   ⚠️  Не удалось определить IP автоматически" -ForegroundColor Yellow
    Write-Host "   Используйте команду 'ipconfig' для просмотра IP" -ForegroundColor Gray
}

Write-Host ""
Write-Host "💡 Следующие шаги:" -ForegroundColor Cyan
Write-Host "   1. Запустите сервер: python app.py" -ForegroundColor Gray
Write-Host "   2. На другом устройстве откройте http://ВАШ_IP:$port" -ForegroundColor Gray
Write-Host ""
Write-Host "📖 Подробная инструкция: LOCAL_NETWORK.md" -ForegroundColor Cyan
Write-Host ""

Pause

