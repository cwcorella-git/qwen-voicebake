# VoiceBake example project

A minimal Godot 4.3+ project that plays one baked line with `VoiceBank`.

`addons/voicebake` here is a relative symlink to `../../addons/voicebake`. On Windows, or
if the symlink is missing, copy `godot/addons/voicebake` into `godot/example/addons/`.
To use the addon in your own game, copy `addons/voicebake` into your project's `addons/`
folder and enable it under Project Settings > Plugins.

To hear something, bake the starter project with its output folder set to
`godot/example/voice`, then run `main.tscn`.
