$naoLib = "C:\Users\nicol\OneDrive\Documentos\NAO\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\lib"
$naoBin = "C:\Users\nicol\OneDrive\Documentos\NAO\pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649\bin"

$currentPyPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "User")
if ($currentPyPath -notmatch [regex]::Escape($naoLib)) {
    if ($currentPyPath) {
        $newPyPath = $currentPyPath + ";" + $naoLib
    } else {
        $newPyPath = $naoLib
    }
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $newPyPath, "User")
    Write-Host "✅ Añadido SDK lib a PYTHONPATH"
} else {
    Write-Host "✅ SDK lib ya estaba en PYTHONPATH"
}

$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notmatch [regex]::Escape($naoBin)) {
    $newPath = $currentPath + ";" + $naoBin
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "✅ Añadido SDK bin a PATH"
} else {
    Write-Host "✅ SDK bin ya estaba en PATH"
}

if (Test-Path "C:\Python27") {
    if ($currentPath -notmatch "C:\\Python27") {
        $newPath = [Environment]::GetEnvironmentVariable("PATH", "User") + ";C:\Python27"
        [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
        Write-Host "✅ Añadido C:\Python27 a PATH"
    } else {
        Write-Host "✅ C:\Python27 ya estaba en PATH"
    }
}
Write-Host "¡Variables de entorno actualizadas con éxito!"
