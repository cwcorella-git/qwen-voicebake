@tool
class_name VoiceBank
extends Node
## Looks up baked voice lines by voice name and line id using manifest.json.
##
## Usage:
##   var bank := VoiceBank.new()
##   add_child(bank)
##   bank.load_manifest("res://voice/manifest.json")
##   bank.play("mechanic", "mech_greet_01")

var _voices: Dictionary = {}
var _base_dir: String = ""
var _streams: Dictionary = {}


## Reads the manifest. Returns OK, or an Error code if the file is missing or invalid.
func load_manifest(path: String) -> Error:
	_voices = {}
	_streams = {}
	_base_dir = path.get_base_dir()
	if not FileAccess.file_exists(path):
		return ERR_FILE_NOT_FOUND
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return ERR_PARSE_ERROR
	var voices: Variant = (parsed as Dictionary).get("voices", {})
	if typeof(voices) != TYPE_DICTIONARY:
		return ERR_PARSE_ERROR
	_voices = voices
	return OK


func get_voices() -> PackedStringArray:
	return PackedStringArray(_voices.keys())


func get_line_ids(voice: String) -> PackedStringArray:
	var lines: Dictionary = _voices.get(voice, {})
	return PackedStringArray(lines.keys())


## Manifest entry for a line: {path, text, tone, route, duration}. Empty if unknown.
func get_entry(voice: String, id: String) -> Dictionary:
	var lines: Dictionary = _voices.get(voice, {})
	return lines.get(id, {})


func has_line(voice: String, id: String) -> bool:
	return not get_entry(voice, id).is_empty()


## Resource path of a line's audio file, or "" if unknown.
func get_path_for(voice: String, id: String) -> String:
	var entry: Dictionary = get_entry(voice, id)
	if entry.is_empty():
		return ""
	return _base_dir.path_join(str(entry.get("path", "")))


## Returns the line's stream, or null if the line or its imported file is missing.
## Pass reload = true to bypass the cache after a file was regenerated.
func get_stream(voice: String, id: String, reload: bool = false) -> AudioStream:
	var path: String = get_path_for(voice, id)
	if path == "":
		return null
	if not reload and _streams.has(path):
		return _streams[path]
	if not ResourceLoader.exists(path):
		return null
	var mode := ResourceLoader.CACHE_MODE_REPLACE if reload else ResourceLoader.CACHE_MODE_REUSE
	var stream := ResourceLoader.load(path, "", mode) as AudioStream
	if stream != null:
		_streams[path] = stream
	return stream


## Plays a line. With no player given, a temporary AudioStreamPlayer is created and freed
## when it finishes. Returns the player used, or null if the line is unavailable.
func play(voice: String, id: String, player: Node = null) -> Node:
	var stream: AudioStream = get_stream(voice, id)
	if stream == null:
		push_warning("VoiceBank: no audio for %s/%s" % [voice, id])
		return null
	if player == null:
		var temp := AudioStreamPlayer.new()
		add_child(temp)
		temp.finished.connect(temp.queue_free)
		player = temp
	player.set("stream", stream)
	player.call("play")
	return player
