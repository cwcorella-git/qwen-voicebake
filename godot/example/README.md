# VoiceBake example scene

`main.tscn` and `main.gd` play one baked line through `VoiceBank`. The parent folder
(`godot/`) is a Godot 4.3+ project with the addon already enabled; open it in Godot to try it.

To hear something, bake the starter project with its output folder set to `godot/voice`
(`paths.out` in `voicebake.toml`), then run the project.

To use the addon in your own game, copy `godot/addons/voicebake` into your project's
`addons/` folder and enable it under Project Settings > Plugins.
