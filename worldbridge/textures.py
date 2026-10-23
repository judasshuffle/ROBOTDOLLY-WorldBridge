"""Read-only rescue lookup; only unambiguous byte-identical names are relinked."""
from pathlib import Path
import hashlib
import shutil
from functools import lru_cache


@lru_cache(maxsize=4)
def rescue_index(root):
    result = {}
    directory = Path(root) / 'texture-rescue'
    if directory.is_dir():
        for path in directory.rglob('*'):
            if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.tga', '.bmp'):
                result.setdefault(path.name.casefold(), []).append(path)
    return result


def _legacy_repair_images_unused(materials, cache, rescue_root):
    import bpy
    index = rescue_index(rescue_root)
    images = {node.image for material in materials if material.use_nodes
              for node in material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image}
    diagnostics = []
    for image in images:
        if image.packed_file or (image.filepath and Path(bpy.path.abspath(image.filepath)).is_file()):
            continue
        name = image.filepath.replace('\\', '/').rsplit('/', 1)[-1]
        candidates = index.get(name.casefold(), [])
        hashes = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in candidates}
        record = dict(image=image.name, original_path=image.filepath, candidates=len(candidates))
        if len(hashes) == 1:
            digest, source = next(iter(hashes.items()))
            target = Path(cache) / 'textures' / (digest + source.suffix.lower())
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                shutil.copyfile(source, target)
            image.filepath = str(target)
            image.reload()
            record.update(status='recovered', source=str(source), cached=str(target))
        else:
            record['status'] = 'ambiguous' if hashes else 'missing'
        diagnostics.append(record)
    return diagnostics


# Compatibility entry point; v0.5 deliberately rejects unscoped basename guesses.
from .visualtextures import repair_images
