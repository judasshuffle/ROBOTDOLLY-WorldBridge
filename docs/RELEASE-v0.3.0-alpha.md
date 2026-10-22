# ROBOTDOLLY WorldBridge v0.3.0-alpha — Early WIP

An experimental Blender bridge for DarkRide and High Fidelity virtual worlds, independently developed by **ROBOTDOLLY / Judas**.

**Early work in progress — expect missing textures, unfinished features and occasional gremlins.** This is a prerelease, not a production-ready editor or a guarantee of compatibility with every DarkRide world.

## Included

- World backup JSON/gzip import, preserved entity data and lightweight large-world placeholders.
- Selective FBX/glTF/GLB loading, background downloads/cache, incremental imports, cancellation and safety limits.
- Viewport clipping, visibility groups and world/entity framing.
- Selected-entity and spatial-region loading with duplicate prevention.
- Basic supported materials/textures and a conservative cached-FBX alpha repair tool.

The attachment is the existing tested `ROBOTDOLLY-WorldBridge-v0.3.zip`, preserved without rebuilding it.

## Demonstrated, not guaranteed

A genuine 2,121-entity world has been reconstructed, genuine mesh geometry and textures have been displayed, and user-reported interactive testing progressed to 50 model imports. Automated suites passed in Blender 4.2 and 4.5. New v0.3 controls have headless coverage; their complete interactive acceptance remains unverified.

## Installation

In Blender 4.2 or 4.5, disable an older WorldBridge version, restart Blender, then use Preferences > Add-ons > Install from Disk to install the attached ZIP. Enable it and open the 3D View sidebar's WorldBridge tab. Start with the default four-model limit or placeholders only. Follow the README and usage guide for path configuration and supported backups.

## Limitations

External textures may be missing and unresolved images can make models magenta. Transparency remains under investigation. Some entities are approximate. A native model import may temporarily block Blender. Safe world editing and reliable round-trip export are not complete or verified. Keep original backups unchanged and work on copies.

**Licensing is unresolved:** no project open-source licence has been assigned. Read LICENSE-STATUS.md and THIRD_PARTY_NOTICES.md. No worlds, models, textures or third-party dependency code are included. No official DarkRide, High Fidelity or Blender endorsement is implied.
