# VoiceBake Godot addon

Godot 4.3+ editor plugin and runtime helper for audio baked with VoiceBake.

## Install

Copy this folder (`godot/addons/voicebake` in the repository) to `res://addons/voicebake/` in your project and enable it under
Project Settings > Plugins. Set the VoiceBake output folder (`paths.out` in
`voicebake.toml`) to a folder inside your project, normally `res://voice`.

## Editor dock

The VoiceBake dock lists every baked line by voice. Select a line and press Play (or
double-click it) to hear it. The project is rescanned automatically when `manifest.json`
changes, so new files are imported without focusing another window.

The manifest location is the project setting `voicebake/manifest_path`
(default `res://voice/manifest.json`).

### Regenerate

Regenerate asks the running VoiceBake app to rebake the selected line, then imports the new
file and plays it. A newly written `.ogg` is silent until Godot has imported it; the dock
triggers the import for you.

The app's local server requires a token. While the app is open it writes
`.voicebake-session` (port and token) next to `manifest.json`. The dock reads this file
before every request and does not store the token anywhere. If the file is missing the app is
closed, and Regenerate is disabled with a tooltip.

Add this line to your `.gitignore`:

    .voicebake-session

If the app crashes, a stale `.voicebake-session` may remain. Requests then fail with a
message in the dock; deleting the file or restarting the app fixes it.

## Exporting your game

`manifest.json` is not a Godot resource, so exports leave it out by default. Add it under
Export > Resources > "Filters to export non-resource files/folders", for example
`voice/*.json`. The audio files themselves are imported resources and export normally.
If the manifest is missing at runtime, `VoiceBank` prints a warning saying so.

## Runtime: VoiceBank

```gdscript
var bank := VoiceBank.new()
add_child(bank)
bank.load_manifest("res://voice/manifest.json")

if bank.has_line("mechanic", "mech_greet_01"):
    bank.play("mechanic", "mech_greet_01")          # temporary player, freed when done
    bank.play("mechanic", "mech_greet_01", my_player)  # or your own AudioStreamPlayer / 2D / 3D
```

| Method | Returns |
|---|---|
| `load_manifest(path)` | `OK` or an Error |
| `get_voices()`, `get_line_ids(voice)` | `PackedStringArray` |
| `has_line(voice, id)` | `bool` |
| `get_entry(voice, id)` | manifest entry: path, text, tone, route, duration |
| `get_stream(voice, id)` | `AudioStream` or `null` |
| `play(voice, id, player = null)` | the player used, or `null` |

Scripts of your own can refer to the class by name (`VoiceBank`), or load the script directly
with `preload("res://addons/voicebake/voice_bank.gd")` to avoid depending on the editor's
class cache. `get_stream` returns `null` until Godot has imported the file. Make sure the output folder is
not excluded from export.
