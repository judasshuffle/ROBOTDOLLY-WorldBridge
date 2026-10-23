# Usage guide — v0.3 alpha

This guide is retained for the published v0.3 release. For the local v0.4 build,
use **[the v0.4 guide](V0.4.md)**; file selection, area selection, defaults and logs changed.

## Backups and preservation

Import a DarkRide/High Fidelity-style backup object containing an `Entities` array. Supported filenames are `.json`, `.json.gz` and `.gz`; gzip is detected from its signature rather than only the extension. The decompressed input is limited to 512 MiB. Source backup files are read only.

A complete parsed copy is written to a unique `.source.json` sidecar before scene construction. Unknown fields, original URLs and scripts are preserved as data; scripts are never executed. JSON whitespace is not retained. Each entity has an unscaled anchor linked by original ID and record index, with geometry beneath it. Sidecar data is not rewritten by viewport controls or targeted loading.

DarkRide `(x, y, z)` is mapped to Blender `(x, -z, y)`. Domain backup transforms are treated as parent-local. Dimensions are applied to visuals, avoiding dimension-based scaling of child anchors. The optional script-export world-transform mode is not the tested default.

Malformed root/record structures fail before scene creation. Missing parents, cycles and unsupported entities produce diagnostics rather than silent disappearance. Fatal scene errors leave a labelled partial collection for inspection.

### Optional gzip workaround

Direct gzip import is implemented and tested. If a particular file/picker path fails, decompress a copy:

```powershell
python -c "import gzip,shutil; src=gzip.open('models.json.gz','rb'); dst=open('models-copy.json','xb'); shutil.copyfileobj(src,dst); dst.close(); src.close()"
```

This creates a new file and refuses to overwrite an existing `models-copy.json`. Do not run it on untrusted unlimited-size compressed input; the add-on's direct parser provides the size bound. Keep the original backup unchanged.

## Outputs and portability

The current tested Windows release defaults to `C:\Projects\ROBOTDOLLY-WorldBridge\imports` for sidecars/cache and `C:\Projects\ROBOTDOLLY-WorldBridge\build\worldbridge-import.log` for logging. The import file picker exposes the sidecar/cache directory. Targeted-operation reports and logs still use the fixed project root. Portable path configuration is unfinished.

When moving a saved Blender scene, preserve the linked sidecars and cache paths. Missing or mismatched sidecar records stop targeted preparation visibly rather than inventing entity data.

## Viewport controls

Initial clipping is 0.01 to 100,000 metres at Blender's standard scale. Sidebar values persist with the scene. Subsequent imports reuse them and preserve native viewport edits since the last application. **Apply to All Viewports** explicitly synchronises 3D viewports in the current workspace. Workspace layout changes can change viewport identity; reapply settings when needed.

Large clipping ratios reduce depth precision. Raise Clip Start or lower Clip End for close work if surfaces flicker or z-fight. Render-camera clipping is not changed.

Visibility groups use `worldbridge_role` tags and reversible per-view-layer hiding; objects are not moved into new parent hierarchies or deleted. Anchors default hidden, placeholders/models visible. Primitive geometry and lights remain separate from wireframe placeholders. Toggles affect matching WorldBridge objects throughout the scene and may override manual per-object hide choices. Excluded collections or local-view isolation are not automatically undone.

**Frame Entire World** includes hidden entity bounds, including large zones. **Frame Selected Entity** resolves selected model geometry or placeholders to their entity anchors. Framing only changes viewport navigation.

## Selected / region model loading

Select entity meshes, placeholders or anchors. For a collection, use Blender's Select Objects command. **Load Selected Models** keeps existing anchors and skips models that already have loaded child meshes. Repeating this operation does not duplicate those models.

**Load Models in Region** explicitly includes anchor origins inside Region Min/Max, inclusive, in Blender world coordinates. It does not test mesh intersections. Both operations have a positive model limit, initially four, and use the original sidecar directory's cache. A failed model consumes a loading slot; already-loaded or ineligible entities are skipped.

The full-backup importer can still create a separate new world collection on each invocation. Use targeted loading to fill in an existing world instead of repeatedly importing the whole backup.

## Materials and missing images

The cached crate investigation reproduced Alpha 0 from a legacy Blender 2.77 FBX export. Its template specifies opaque defaults, but material-local Opacity is absent and TransparentColor is white. Blender's fallback derives zero alpha from that combination.

The repair requires that legacy source pattern plus no explicit transparency override/texture, no linked Alpha and no transmission/glass/transparent shader indication. It repairs only the demonstrated opaque ambiguity. glTF OPAQUE/BLEND/MASK handling is left to Blender. Tests preserve the genuine cupboard glass while repairing its wood.

**Repair Selected Cached FBX Materials** works on existing imported models using the local cache only. It copies materials before changing them, preserving shared original materials. Ambiguous or renamed source-material matches may be skipped. Automatic repairs appear in reports; manual repair details are logged.

Missing external images are a separate issue. Magenta materials generally require image-resource resolution, not an alpha reset. Automatic missing-texture recovery is planned. Transparency behaviour across other exporters and assets remains under investigation.

## Progress, limits and cancellation

The sidebar reports entities processed, downloaded/cached models, successes, failures, skips, cancellations and the current model. **Cancel Import** stops new scheduling and retains completed geometry/placeholders. Download workers stop at their next I/O check. Changing files/scenes or disabling the add-on cancels active work.

HTTP(S) downloads have a 128 MiB size limit, five-second connection/read timeout and checked 60-second elapsed deadline. DNS resolution remains OS-controlled. The UI never waits for a worker join. Cached assets do not auto-refresh. External glTF dependencies, ATP/FST and extensionless URLs are not generally supported.

A single native FBX/glTF importer remains synchronous on Blender's main thread. It can temporarily block interaction; cancellation takes effect after that native call returns. Local FBX evidence inspection/manual repair is also synchronous. All Blender API operations stay on the main thread.

## Reports and persistent log

Open the Text Editor's **WorldBridge Report ...** datablock, or the corresponding `.report.json`. The append-only log is flushed after each entry:

```powershell
Get-Content 'C:\Projects\ROBOTDOLLY-WorldBridge\build\worldbridge-import.log' -Tail 40 -Wait
```

`download_started` / `download_ready` bracket background downloads. `model_import_started` is flushed before the native importer; a missing completion entry helps identify a stalled model. Errors retain the asset URL, entity index, stage and traceback. Logs and sidecars may contain private original data: do not commit or post them without review.
