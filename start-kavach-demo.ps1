# Superseded by run-kavach.ps1, which checks ports first, verifies every service and the tunnel, and only then prints the link.
# This file is kept so old instructions keep working.
& (Join-Path $PSScriptRoot "run-kavach.ps1") @args
