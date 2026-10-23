"""DarkRide location parsing and optical-camera basis conversion."""
import math
from urllib.parse import urlsplit, unquote
from .parser import coordinates, rotation


def parse_location(location):
    parsed = urlsplit(location.strip())
    if parsed.scheme.lower() != 'hifi':
        raise ValueError('Expected hifi://domain/x,y,z/qx,qy,qz,qw')
    fields = unquote(parsed.path).strip('/').split('/')
    if len(fields) != 2:
        raise ValueError('Location must include position and orientation')
    position, quaternion = ([float(v) for v in field.split(',')] for field in fields)
    if len(position) != 3 or len(quaternion) != 4 or not all(math.isfinite(v) for v in position+quaternion):
        raise ValueError('Expected three finite position and four quaternion numbers')
    if sum(v*v for v in quaternion) < 1e-12:
        raise ValueError('Zero-length orientation quaternion')
    return coordinates(position), rotation({'rotation': dict(zip(('x','y','z','w'), quaternion))}, 'rotation')


def create_camera(scene, location, fov=70, eye_height=1.6, distance=0, radius=35):
    import bpy
    from mathutils import Quaternion, Vector
    position, rotation_values = parse_location(location)
    if not 10 <= fov <= 150 or not all(math.isfinite(v) for v in (eye_height, distance, radius)) or radius <= 0:
        raise ValueError('FOV must be 10–150 degrees and area radius positive')
    camera = next((o for o in scene.objects if o.get('worldbridge_reference_camera')), None)
    if camera is None:
        camera = bpy.data.objects.new('WorldBridge Reference Camera', bpy.data.cameras.new('WorldBridge Reference Camera'))
        scene.collection.objects.link(camera)
    q = Quaternion(rotation_values)
    camera.rotation_mode = 'QUATERNION'
    camera.rotation_quaternion = q @ Quaternion((1, 0, 0), math.pi/2)
    camera.location = Vector(position)+Vector((0, 0, eye_height))-(q @ Vector((0, 1, 0)))*distance
    camera.data.type = 'PERSP'
    camera.data.sensor_fit = 'HORIZONTAL'
    camera.data.angle = math.radians(fov)
    camera.data.clip_start, camera.data.clip_end = .05, 100000
    camera['worldbridge_reference_camera'] = True
    camera['worldbridge_source_location'] = location
    camera['worldbridge_eye_height'] = eye_height
    camera['worldbridge_camera_distance'] = distance
    scene.camera = camera
    region = getattr(scene, 'worldbridge_region', None)
    if region is None:
        region = bpy.data.objects.new('WorldBridge Selection Region', None)
        scene.collection.objects.link(region)
        region.empty_display_type = 'CUBE'
        region.empty_display_size = 1
        region.show_in_front = True
        region['worldbridge_role'] = 'REGION'
        scene.worldbridge_region = region
    region.location, region.scale = position, (radius, radius, radius)
    scene.cursor.location = position
    from .viewport import viewports
    for area, space in viewports():
        space.region_3d.view_perspective = 'CAMERA'
        area.tag_redraw()
    return camera
