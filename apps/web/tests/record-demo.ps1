param(
  [Parameter(Mandatory=$true)][string]$Url,
  [string]$Image='kontroferta:local',
  [string]$OutputDirectory=(Join-Path $PSScriptRoot '../evidence')
)
$ErrorActionPreference='Stop'
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
$BrowserTestsDirectory=[IO.Path]::GetFullPath($PSScriptRoot)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
# The application image contains Chromium, Playwright and its encoder.
# This isolated container receives only the public demo URL, test code and output folder.
docker run --rm --entrypoint python --env "DEMO_URL=$Url" --env EVIDENCE_DIR=/evidence --mount "type=bind,source=$BrowserTestsDirectory,target=/test,readonly" --mount "type=bind,source=$OutputDirectory,target=/evidence" $Image /test/verify_public_browser.py
exit $LASTEXITCODE