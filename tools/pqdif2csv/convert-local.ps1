# convert-local.ps1 — batch-convert PQDIF files to GridWitness-ready CSV on your Windows machine.
#
# PQDIF support runs locally (GSF.PQDIF is .NET Framework / Windows-only). This converts every .pqd
# in a folder to a <name>.csv in the long format the site accepts, so you can just upload the CSVs
# through the normal "Contribute a survey" page — no drama.
#
#   .\convert-local.ps1 -Folder C:\surveys\pending
#   .\convert-local.ps1 -Folder C:\surveys\pending -OutFolder C:\surveys\converted
#
param(
    [Parameter(Mandatory = $true)][string]$Folder,
    [string]$OutFolder = "",
    [string]$Exe = ""
)

$ErrorActionPreference = "Stop"

# Locate the built converter (Release preferred, else Debug) unless an explicit path was given.
if (-not $Exe) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $Exe = Get-ChildItem -Path $here -Recurse -Filter pqdif2csv.exe -ErrorAction SilentlyContinue |
           Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    if (-not $Exe) { throw "pqdif2csv.exe not found. Build it first: dotnet build -c Release" }
}

if (-not $OutFolder) { $OutFolder = $Folder }
New-Item -ItemType Directory -Force -Path $OutFolder | Out-Null

$pqd = Get-ChildItem -Path $Folder -Include *.pqd, *.pqdif -File -Recurse
if (-not $pqd) { Write-Host "No .pqd/.pqdif files under $Folder"; return }

$ok = 0; $fail = 0
foreach ($f in $pqd) {
    $out = Join-Path $OutFolder ($f.BaseName + ".csv")
    Write-Host "converting $($f.Name) -> $(Split-Path -Leaf $out)"
    & $Exe $f.FullName $out
    if ($LASTEXITCODE -eq 0) { $ok++ } else { $fail++; Write-Warning "failed: $($f.Name)" }
}
Write-Host "done: $ok converted, $fail failed. Upload the .csv files in $OutFolder via the site."
