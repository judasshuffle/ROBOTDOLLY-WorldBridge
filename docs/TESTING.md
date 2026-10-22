# Testing and evidence boundaries

Publication validation (2026-10-22): 14 standalone tests passed. The existing smoke, incremental, v0.3 and real-backup suites were run headlessly in Blender 4.2.0 and 4.5.0; see the validation results below. These tests do not verify interactive responsiveness or visual appearance.

## Reproduce public tests

From the project root in PowerShell:

```powershell
New-Item -ItemType Directory -Force build | Out-Null
python -m unittest discover -s tests -v
foreach ($version in @('4.2', '4.5')) {
    $blender = "C:\Program Files\Blender Foundation\Blender $version\blender.exe"
    foreach ($suite in @('blender_smoke', 'blender_incremental')) {
        & $blender --background --factory-startup --python-exit-code 1 --python "tests\$suite.py"
        if ($LASTEXITCODE -ne 0) { throw "Failed: $version $suite" }
    }
}
```

The smoke suite creates synthetic fixtures in `build/`. Run suites sequentially because they share output paths. Standalone tests cover plain/gzip parsing, hierarchy errors, coordinate conversion, source preservation, download limits, caching, cancellation, failure continuation, immediate logging and selection validation. Blender suites cover actual scene construction, native synthetic asset imports, main-thread operations and timer lifecycle.

## Optional private-fixture regressions

`tests/blender_v03.py` also uses locally supplied cached FBX models and a genuine world backup; `tests/blender_real_backup.py` needs `test-backup/models.json.gz` and the preserved `build/worldbridge-v0.1-source-backup.zip`. These files are deliberately excluded from publication. Inspect each test's fixture paths before running it with your own authorised content. Run the smoke suite first to create its synthetic GLB fixture.

```powershell
& $blender --background --factory-startup --python-exit-code 1 --python tests/blender_v03.py
& $blender --background --factory-startup --python-exit-code 1 --python tests/blender_real_backup.py
```

The v0.3 suite checks viewport clipping and retained user settings, unchanged camera clipping, reversible visibility, framing, cached crate/wood alpha repair, preservation of glass/alpha links, glTF alpha modes, selected/region loading and duplicate prevention. The real-backup suite compares all 2,121 entity identities, hierarchy, transforms and sidecar data against the preserved v0.1 implementation and verifies the source backup hash. Its historical output label mentions v0.2; it imports the current working source for comparison.

## Interactive evidence

The developer reported successful reconstruction of the genuine world, textured meshes and progress to 50 interactive model imports. This is useful observed progress, not a full interactive acceptance test. The publication checks are automated/headless only. v0.3 controls, appearance across assets and cancellation during real interactive sessions still need broader verification. A single native Blender model import can temporarily block the UI.

## Publication audit

After explicitly staging only public files, run:

```powershell
python tools/audit_publication.py
git diff --cached --stat
git status --short
```

The audit checks the Git index against a source/document allowlist, scans common secret and personal-data patterns, checks ZIP integrity and confirms the preserved v0.3 archive contains only the matching add-on Python source. Pattern scanning is not a proof that every possible secret is absent. The audit manifest is written to ignored `build/publication-audit.json`. Generated logs may contain private asset URLs and must remain local.

The existing release ZIP is not rebuilt during publication. `build_zip.py` is a development packager that writes that filename; do not run it if you need to preserve the original release. `tools/publish.ps1` publishes the reviewed clean commit using the authenticated GitHub CLI and refuses an existing origin/repository. It must run with GitHub network access; no credentials are embedded.

## Publication validation results — 2026-10-22

| Suite | Blender 4.2.0 | Blender 4.5.0 |
|---|---|---|
| Smoke | PASS | PASS |
| Incremental import | PASS | PASS |
| v0.3 regressions | PASS | PASS |
| Genuine 2,121-entity preservation | PASS | PASS |

Standalone: 14/14 passed. Existing test files and add-on source were unchanged. Logs are retained locally under `build/publication-*.txt` and excluded from Git.

The working-tree candidate audit passed for 29 public files. Staged-file verification and committing remain pending because this execution environment denies writes to `.git`. GitHub CLI requests also fail at the environment's network proxy. No repository or prerelease was published during this attempt.

To finish in a terminal with project Git write access and GitHub network access:

```powershell
Set-Location C:\Projects\ROBOTDOLLY-WorldBridge
git config user.name 'ROBOTDOLLY / Judas'
git config user.email '7031192+judasshuffle@users.noreply.github.com'
git add .gitignore .gitattributes README.md CHANGELOG.md LICENSE-STATUS.md THIRD_PARTY_NOTICES.md build_zip.py worldbridge tests docs tools
python tools/audit_publication.py
# Continue only if the audit passes and the staged files are appropriate.
git diff --cached --stat
git commit -m 'Prepare WorldBridge v0.3 experimental community release'
.\tools\publish.ps1
```

These commands do not rebuild release ZIPs. The publishing script refuses an existing origin/repository; review any partial publication manually before retrying.
