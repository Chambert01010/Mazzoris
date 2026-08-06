$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
$frontendDir = Join-Path $projectRoot "hostinger-static"
$assetsDir = Join-Path $frontendDir "assets"

New-Item -ItemType Directory -Force -Path $frontendDir, $assetsDir | Out-Null

$templatePath = Join-Path $projectRoot "templates\index.html"
$outputPath = Join-Path $frontendDir "index.html"
$html = [System.IO.File]::ReadAllText($templatePath)

$html = $html -replace "\{\% load static \%\}\r?\n", ""
$html = $html -replace "\{\% static '([^']+)' \%\}", './assets/$1'
$html = $html -replace "(?m)^\s*<li><a class=""staff-access-btn"" href=""\{\% url 'login' \%\}"">Acceso Staff</a></li>\r?\n?", ""
$html = $html -replace '<footer class="footer-mazzoris">', '<footer class="footer-mazzoris" id="contacto">'
$html = $html -replace "\?v=[0-9A-Za-z]+", ""

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($outputPath, $html, $utf8NoBom)

Copy-Item -Path (Join-Path $projectRoot "static\*") -Destination $assetsDir -Recurse -Force

Write-Host "Frontend exportado en hostinger-static."
Write-Host "Sube el contenido de hostinger-static dentro de public_html en Hostinger."
