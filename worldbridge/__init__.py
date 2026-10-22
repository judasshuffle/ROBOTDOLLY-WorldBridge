bl_info = {'name': 'ROBOTDOLLY WorldBridge', 'author': 'ROBOTDOLLY', 'version': (0, 3, 0), 'blender': (4, 2, 0), 'location': 'View3D > Sidebar > WorldBridge', 'description': 'DarkRide worlds: incremental import, viewport controls, material repair and selected model loading', 'category': 'Import-Export'}


def register():
    from . import ui
    ui.register()


def unregister():
    from . import ui
    ui.unregister()
