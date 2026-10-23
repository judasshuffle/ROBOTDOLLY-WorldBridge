# ROBOTDOLLY WorldBridge

**v0.4 local development build — not published.** Install the local
`ROBOTDOLLY-WorldBridge-v0.4.zip` through Blender's Add-ons > Install from Disk.
Use WorldBridge's separate **Import DarkRide Backup** button to open worlds.

v0.4 adds ZIP/content-ZIP inspection and world choice, a placeholder-first default,
visual region selection, confirmation with cache/download counts, optional bounds
intersection, camera suppression, light controls and local texture recovery.
See the **[v0.4 usage, findings and limitations](docs/V0.4.md)** for current instructions.
The v0.1–v0.3 ZIPs and published v0.3 release remain unchanged.

The overview below documents the preserved published v0.3 alpha. Its numeric
region controls, defaults and log locations are superseded by the v0.4 guide.

*An experimental Blender bridge for DarkRide and High Fidelity virtual worlds.*

**ROBOTDOLLY / Judas** is developing WorldBridge independently to import, inspect and eventually rearrange virtual-world entities in Blender. The long-term ambition is to make managing a world as intuitive as selecting and moving objects in a 3D editor.

Our first successful test reconstructed a **2,121-entity world** in Blender, with genuine mesh geometry and textures beginning to appear. Interactive testing has since progressed to **50 model imports**.

> **Early work in progress — expect missing textures, unfinished features and occasional gremlins.** This is an experimental alpha, not a production-ready editor or a promise of full compatibility with every DarkRide world. Keep original backups unchanged and work on copies.

## Published capabilities — v0.3

- Import DarkRide / High Fidelity-style world backup JSON containing an `Entities` array, including gzip-compressed files.
- Preserve entity IDs, hierarchy, transforms and complete parsed source metadata in linked JSON sidecars.
- Represent large worlds with lightweight anchors, primitives and placeholders.
- Selectively load genuine FBX, glTF and GLB model assets through Blender's native importers.
- Download HTTP(S) assets in the background and reuse a local cache.
- Process scene construction and model imports incrementally, with progress, cancellation and safety limits.
- Adjust viewport clipping, show/hide anchors, placeholders and imported models, and frame worlds or selections.
- Handle supported basic materials and textures, with a conservative cached-FBX material repair tool.
- Load models for selected entities or an axis-aligned spatial region without duplicating already-loaded models.

The default model-loading limit is **four**. Start there, or use placeholders only, before increasing the scope.

## Demonstrated progress

| Observation | What it establishes |
|---|---|
| A genuine 2,121-entity backup was reconstructed | A substantial real-world layout can be represented; this is not universal format coverage. |
| Genuine mesh geometry and textured models appeared in Blender | Supported asset paths work for tested examples; external textures and materials are not all resolved. |
| Interactive testing progressed to 50 model imports | User-reported progress beyond the initial four-model test; not a comprehensive stress, compatibility or correctness test. |
| Automated suites passed in Blender 4.2 and 4.5 | Parser, scheduling, preservation and tested Blender API behaviour pass. Headless results do not prove interactive responsiveness or final appearance. |

The new v0.3 viewport/material/targeted-loading features have headless regression coverage. A comprehensive interactive v0.3 acceptance pass has not been recorded. See [testing and validation](docs/TESTING.md).

## Install in Blender 4.2 or 4.5

1. Download `ROBOTDOLLY-WorldBridge-v0.3.zip` from the project's GitHub **Releases** page when the prerelease is available. The release label is **v0.3.0-alpha**.
2. If upgrading, disable the older WorldBridge add-on and restart Blender to unload its Python modules.
3. Open **Edit > Preferences > Add-ons**, choose **Install from Disk** from the dropdown, and select the ZIP. Enable **ROBOTDOLLY WorldBridge**.
4. In the 3D View, switch to **Object Mode**, press **N**, and open the **WorldBridge** tab.

**Current portability limitation:** this WIP was developed on Windows and still defaults its import output and persistent log to `C:\Projects\ROBOTDOLLY-WorldBridge`. The full-backup file picker lets you change the sidecar/cache output directory, but targeted-operation reports and logging still use the fixed project location. That location must be writable for the unchanged tested release. Cross-platform path configuration is unfinished; do not assume this prerelease is portable to every machine.

## Load a world

1. Click **Import DarkRide Backup** and select `.json`, `.json.gz` or `.gz`.
2. Leave **Script export: world-space transforms** OFF for a domain backup.
3. Use the four-model limit, or turn model downloads off to inspect the complete placeholder layout first.
4. Keep the generated `.source.json` sidecar with your Blender project. Objects refer to its records by original ID and record index.
5. Watch progress in the sidebar. **Cancel Import** retains completed objects and remaining placeholders. Detailed reports are available in Blender's Text Editor and as `.report.json` files.

Compressed backups are supported directly: the parser detects gzip by its file signature and applies a decompressed size limit. No current blanket `.json.gz` restriction was reproduced by the automated tests. If a particular picker/import path has trouble with a compressed file, decompress **a copy** to `.json` and import that copy; never overwrite the original backup. Instructions are in the [usage guide](docs/USAGE.md).

For an already imported world, select one or more entity meshes/placeholders and use **Load Selected Models**, or explicitly define **Region Min/Max** and use **Load Models in Region**. A region includes entities by anchor origin in Blender coordinates, not by mesh intersection. These operations retain the original entity data and reuse available cache files.

If an already-imported opaque crate is invisible, select its mesh and try **Repair Selected Cached FBX Materials**. The repair targets a demonstrated legacy FBX opacity pattern; it is not a general transparency reset. Glass, decals and alpha textures must remain intentional. More detail is in [the usage guide](docs/USAGE.md).

## Known limitations

- Some external textures are missing; unresolved image resources can make models display **magenta**.
- Transparency and alpha handling remain under investigation. The current repair is deliberately narrow.
- Certain DarkRide entity types, lights, zones, joint/avatar parenting and unsupported shapes have approximate representations.
- Individual native FBX/glTF imports may temporarily block Blender. Cancellation cannot interrupt a native importer already executing.
- External glTF buffer/image dependencies, ATP/FST and extensionless model URLs are not generally supported. Prefer self-contained GLB where possible.
- Cached assets do not automatically refresh. Model instances can still consume substantial memory.
- World editing and reliable round-trip export are **not complete or verified**. Moving objects in Blender is not yet a safe domain-edit/export workflow.
- Blender 5.x, every DarkRide backup variant and all third-party assets are not verified.
- Licensing is unresolved; see below.

A clipping range of **0.01–100,000 metres** improves large-domain visibility, but its very large near/far ratio can reduce depth precision and cause z-fighting. Use a smaller useful range for detailed work. WorldBridge's clipping controls do not change render-camera clipping.

## Roadmap

The goal is a visual world-management tool: select whole groups or geographical areas of a virtual world, reposition them in 3D, inspect the result from multiple views and eventually export a validated modified layout.

Planned work includes:

- Automatic missing-texture recovery.
- Additional asset-cache integration and portable path configuration.
- Improved model/material diagnostics.
- Spatial grouping and multi-view editing.
- Selectable 3D regions with more expressive selection tools.
- Safe world export with validation, identity preservation and round-trip checks.

These are planned capabilities, not promises that the current alpha already implements them.

## Documentation and development

- [Usage, clipping, visibility, material repair and logs](docs/USAGE.md)
- [Tests and evidence boundaries](docs/TESTING.md)
- [Changelog: v0.1, v0.2 and v0.3](CHANGELOG.md)
- [v0.3.0-alpha prerelease notes](docs/RELEASE-v0.3.0-alpha.md)
- [Licensing status](LICENSE-STATUS.md) and [dependency/credit notices](THIRD_PARTY_NOTICES.md)

Source is in `worldbridge/`; tests are in `tests/`. No private domain data, cached assets or test-world contents are distributed. Some optional real-asset tests require locally supplied private fixtures and cannot be reproduced from the public repository alone.

The checked-in `.gitignore` uses a public-source allowlist. Private backups, asset caches, generated reports, logs, credentials and local release archives remain excluded. The tested ZIP is distributed separately as a prerelease attachment rather than committing private build directories or binary bundles to the source tree.

## Credits and licensing

**ROBOTDOLLY / Judas** develops this project independently for the **DarkRide** and **High Fidelity** ecosystems. No official endorsement by those ecosystems or the Blender Foundation is implied.

Acknowledgements: [DarkRide](https://github.com/caitlynmeeks/darkride-interface), [Nex-Pro's DarkRide Blender tools](https://github.com/Nex-Pro/darkride-blender-tools), and [Menithal's Blender Metaverse Add-on](https://github.com/Menithal/Blender-Metaverse-Addon) provided read-only implementation guidance. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

**No project open-source licence has been selected.** Licensing remains unresolved and is explicitly flagged in [LICENSE-STATUS.md](LICENSE-STATUS.md). No third-party worlds, models, textures or dependency source are bundled; rights to those assets remain separate from this tool.
