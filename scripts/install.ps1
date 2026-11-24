# Install Offerowl for this user and open it. Each release carries this script with its own version written in, so the
# line below installs that release (Windows PowerShell 5.1 or PowerShell 7):
#
#   irm https://github.com/kanggu12/offerowl/releases/download/vX.Y.Z/offerowl-X.Y.Z-windows-installer.ps1 | iex
#
# The one-file app goes to %LOCALAPPDATA%\Programs\Offerowl\offerowl.exe, with Offerowl in this user's Start menu
# (%APPDATA%\Microsoft\Windows\Start Menu\Programs). Run it again to update; your files stay in %LOCALAPPDATA%\Offerowl.
# $env:OFFEROWL_INSTALL_ONLY = '1' installs without opening it (a script, a check).
# Only .NET and core commands: a Windows PowerShell started from another shell may find PowerShell 7's modules first.
& {
  $ErrorActionPreference = 'Stop'
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12  # GitHub takes TLS 1.2 or newer
  $repo = 'kanggu12/offerowl'
  # The release this script installs, written in by scripts/installers.sh; empty in the repository, where it installs the latest.
  $release = ''
  if (-not $release) {
    $ask = [Net.WebRequest]::Create("https://github.com/$repo/releases/latest")  # the latest release's page redirects to its tag
    $ask.Method = 'HEAD'
    $answer = $ask.GetResponse()
    $release = ($answer.ResponseUri.AbsolutePath -split '/')[-1]
    $answer.Close()
  }
  if ($release -notmatch '^v[0-9]') { throw "offerowl: no release found ($release)" }
  $version = $release.Substring(1)  # the address has the v; the files' names have the version without it
  $dir = Join-Path $env:LOCALAPPDATA 'Programs\Offerowl'
  $exe = Join-Path $dir 'offerowl.exe'
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  Write-Host "offerowl: downloading Offerowl $version"
  $part = "$exe.download"  # beside the app first, so a failed download leaves the installed one as it was
  $web = New-Object Net.WebClient
  try { $web.DownloadFile("https://github.com/$repo/releases/download/$release/offerowl-$version-windows-x64.exe", $part) } finally { $web.Dispose() }
  Get-ChildItem -Path $dir -Filter '*.old' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue  # earlier updates' files, once those apps stopped
  if (Test-Path $exe) {
    Move-Item -Force -Path $exe -Destination "$exe.$([DateTime]::Now.ToString('yyyyMMddHHmmss')).old"  # a running app's file can be renamed, never replaced
  }
  Move-Item -Path $part -Destination $exe
  $menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'  # this user's Start menu
  New-Item -ItemType Directory -Force -Path $menu | Out-Null
  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut((Join-Path $menu 'Offerowl.lnk'))
  $link.TargetPath = $exe
  $link.WorkingDirectory = $dir
  $link.Save()
  Write-Host "offerowl: installed: $exe (and Offerowl in the Start menu)"
  if ($env:OFFEROWL_INSTALL_ONLY -eq '1') { return }
  Start-Process -FilePath $exe
}
