# Credits and dependency inspection

WorldBridge is independently developed by **ROBOTDOLLY / Judas** for the **DarkRide** and **High Fidelity** ecosystems. It is not an official project of, or endorsed by, either ecosystem or the Blender Foundation.

## Runtime dependencies

WorldBridge has no third-party pip dependencies and vendors no dependency code. It uses the Python standard library and modules supplied by the user's Blender installation.

| Component | Inspected licence information | Distribution here |
|---|---|---|
| Python standard library | Installed Python 3.10 licence includes the Python Software Foundation licence and historical notices | Not bundled |
| Blender / `bpy`, `bmesh`, `mathutils`, `bpy_extras` | Installed Blender 4.5 `copyright.txt` describes GNU GPL licensing and points to individual SPDX headers and bundled dependency notices | Not bundled |
| Blender FBX importer / `io_scene_fbx.parse_fbx` | Installed Blender 4.5 module header: `GPL-2.0-or-later`; Blender Foundation copyright | Not bundled; imported from Blender at runtime |
| Blender glTF importer / `io_scene_gltf2` | Installed Blender 4.5 module header: `Apache-2.0`; glTF-Blender-IO authors | Not bundled; invoked through Blender |

This inspection records dependency notices; it does not settle WorldBridge's own licensing. See [LICENSE-STATUS.md](LICENSE-STATUS.md). Other Blender versions may ship different dependency versions/notices.

## Implementation references

These projects were inspected read-only for format and implementation guidance. They are not copied or vendored into this repository:

- [caitlynmeeks/darkride-interface](https://github.com/caitlynmeeks/darkride-interface): entity backup format, hierarchy, registration points and transforms. The repository provides LICENSE and LICENSE-MIT notices; refer to the relevant source files and upstream notices.
- [Nex-Pro/darkride-blender-tools](https://github.com/Nex-Pro/darkride-blender-tools): Blender export and coordinate-conversion guidance. No top-level licence file was found during inspection; no permission to copy its code is assumed.
- [Menithal/Blender-Metaverse-Addon](https://github.com/Menithal/Blender-Metaverse-Addon): entity import and primitive/hierarchy guidance. Upstream includes a GPL licence; individual files carry their own notices.

## World content

No real domain data, cached model, image, texture or private test fixture is included. A few test scripts identify locally available fixtures by filename; those names are not asset redistributions. Users must supply world backups and assets they are authorised to use. Referenced remote assets are downloaded only when requested; WorldBridge does not upload or modify them.
