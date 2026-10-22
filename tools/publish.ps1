# Run from this repository only after reviewing LICENSE-STATUS.md and staged files.
# Refuses existing remote repositories rather than risk overwriting unrelated work.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$repository = 'judasshuffle/ROBOTDOLLY-WorldBridge'
$releaseTag = 'v0.3.0-alpha'

$githubCli = 'C:\Program Files\GitHub CLI\gh.exe'
if (-not (Test-Path -LiteralPath $githubCli)) {
    $githubCli = (Get-Command gh -ErrorAction SilentlyContinue).Source
}
if (-not $githubCli) {
    throw 'GitHub CLI is unavailable. Install/authenticate gh, then retry from this project.'
}
& $githubCli auth status
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI is not authenticated.' }
$login = & $githubCli api user --jq .login
if ($LASTEXITCODE -ne 0 -or $login.Trim() -ne 'judasshuffle') { throw 'Expected authenticated GitHub account judasshuffle.' }
$dirty = git status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Commit the reviewed public files first; working tree must be clean.' }
python tools/audit_publication.py
if ($LASTEXITCODE -ne 0) { throw 'Publication audit failed.' }
$commit = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'No reviewed commit is available.' }
$remotes = git remote
if ($remotes -contains 'origin') { throw 'An origin remote already exists. Review it manually before publishing.' }
$existing = & $githubCli repo view $repository --json nameWithOwner 2>$null
if ($LASTEXITCODE -eq 0) { throw 'Repository already exists. This script will not overwrite or push into it.' }

Write-Output 'Licensing remains unresolved; no project open-source licence has been assigned.'
& $githubCli repo create $repository --public --source . --remote origin --push --description 'An experimental Blender bridge for DarkRide and High Fidelity virtual worlds. Independent WIP by ROBOTDOLLY / Judas.'
if ($LASTEXITCODE -ne 0) { throw 'Repository creation/push failed. Inspect remote state before retrying.' }
$remoteCommit = & $githubCli api "repos/$repository/commits/main" --jq .sha
if ($LASTEXITCODE -ne 0 -or $remoteCommit.Trim() -ne $commit.Trim()) { throw 'Remote commit verification failed.' }
& $githubCli release create $releaseTag 'ROBOTDOLLY-WorldBridge-v0.3.zip' --repo $repository --target $commit --prerelease --title 'ROBOTDOLLY WorldBridge v0.3.0-alpha - Early WIP' --notes-file docs/RELEASE-v0.3.0-alpha.md
if ($LASTEXITCODE -ne 0) { throw 'Source was pushed but prerelease creation failed. Do not overwrite existing release assets.' }
& $githubCli release view $releaseTag --repo $repository --json url,isPrerelease,assets
if ($LASTEXITCODE -ne 0) { throw 'Could not verify the published prerelease.' }
Write-Output "Published commit: $commit"

