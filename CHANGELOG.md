# Changelog

WorldBridge is experimental. These entries describe implemented work, not universal compatibility guarantees.

## v0.3.0-alpha — v0.3 work in progress

- Added persistent viewport clipping controls, workspace-wide application and preservation of adjusted values.
- Added reversible anchor, placeholder and imported-model visibility groups and world/selection framing.
- Added a conservative repair for a demonstrated legacy FBX opaque-material Alpha-zero issue, with checks to preserve transparency metadata and alpha textures.
- Added selected-entity and axis-aligned spatial-region loading, cache reuse and duplicate prevention.
- Retained background downloads, incremental main-thread imports, cancellation, progress, logging and model limits.
- Added viewport, real cached-material, selected/region-loading and preservation regression tests in Blender 4.2 and 4.5.
- Prepared community-facing documentation and excluded private world data and caches from the repository.

Demonstrated progress includes a genuine 2,121-entity layout, genuine textured models and user-reported interactive testing progressing to 50 model imports. Missing images, magenta materials and transparency differences remain known issues. New v0.3 controls have headless coverage; a comprehensive interactive v0.3 acceptance pass has not been recorded.

The original add-on metadata remains `(0, 3, 0)`. `v0.3.0-alpha` is the GitHub prerelease label for the preserved tested `ROBOTDOLLY-WorldBridge-v0.3.zip`.

## v0.2 — responsive import pipeline

- Preserved the v0.1 source/release.
- Moved backup preparation and HTTP downloads to workers without Blender API access.
- Introduced timer-driven entity construction and one native model import per tick.
- Added live progress, cancellation, flushed persistent logs, download limits and a default four-model test limit.
- Added name/ID filtering and expanded failure reporting.
- Retained placeholder-only reconstruction and original entity sidecars.
- Tested worker scheduling, failures, cancellation, logs and preservation in standalone and headless suites.

Individual native FBX/glTF imports remain synchronous on Blender's main thread.

## v0.1 — preservation-first prototype

- Added JSON/gzip backup parsing with an expected `Entities` array.
- Reconstructed entities, hierarchy, coordinate transforms, dimensions and registration points.
- Preserved complete parsed source data in sidecars and linked objects by ID/record index.
- Added primitive representations, lights, unsupported-entity placeholders and import reports.
- Added bounded HTTP(S) model caching and native FBX/glTF/GLB import paths.
- Added standalone parser tests and Blender smoke tests.

Initial real-world testing successfully reconstructed a 2,121-entity domain using placeholders. Model loading was synchronous in this version and could make Blender unresponsive.
