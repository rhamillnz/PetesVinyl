# Creates the desktop shortcuts for Pete's Vinyl:
#   "Pete's Vinyl"         starts the app (record icon)
#   "Update Pete's Vinyl"  gets the latest version (record icon with a green arrow)
# Used by Install_PetesVinyl.bat (-Force: recreate them) and Update_PetesVinyl.bat (only adds any that are missing).
param([string]$AppDir, [switch]$Force)

$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$items = @(
    @{ Name = "Pete's Vinyl";        Target = 'Start_PetesVinyl.bat';  Icon = 'vinyl.ico';  Style = 7; Desc = "Pete's Vinyl" },
    @{ Name = "Update Pete's Vinyl"; Target = 'Update_PetesVinyl.bat'; Icon = 'update.ico'; Style = 1; Desc = "Get the latest version of Pete's Vinyl" }
)
foreach ($i in $items) {
    $path = Join-Path $desktop ($i.Name + '.lnk')
    if ((Test-Path $path) -and -not $Force) { continue }
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = Join-Path $AppDir $i.Target
    $s.WorkingDirectory = $AppDir
    $s.WindowStyle = $i.Style
    $s.IconLocation = Join-Path $AppDir ('static\' + $i.Icon)
    $s.Description = $i.Desc
    $s.Save()
    Write-Host ("  Made the desktop shortcut: " + $i.Name)
}
