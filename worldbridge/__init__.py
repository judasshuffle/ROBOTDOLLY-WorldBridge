bl_info = {'name': 'ROBOTDOLLY WorldBridge', 'author': 'ROBOTDOLLY', 'version': (0, 5, 0), 'blender': (4, 2, 0), 'location': 'View3D > Sidebar > WorldBridge', 'description': 'DarkRide worlds: local texture recovery and visual reconstruction', 'category': 'Import-Export'}


def register():
    from . import ui
    ui.register()
    from . import reconstruction_ui
    reconstruction_ui.register()


def unregister():
    from . import reconstruction_ui
    reconstruction_ui.unregister()
    from . import ui
    ui.unregister()
