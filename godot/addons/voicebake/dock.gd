@tool
extends VBoxContainer
## Editor dock: lists baked lines, plays them, and asks the VoiceBake app to regenerate one.
##
## Regenerate talks to the app's local server. The app writes its port and a per-session
## token to ".voicebake-session" next to manifest.json; it is read before every request
## and never stored. If the file is missing the app is closed and Regenerate is disabled.

const SETTING_MANIFEST := "voicebake/manifest_path"
const DEFAULT_MANIFEST := "res://voice/manifest.json"
const SESSION_FILE := ".voicebake-session"

const VoiceBankScript := preload("res://addons/voicebake/voice_bank.gd")
const TOKEN_PATTERN := "^[A-Za-z0-9_-]+$"

var _bank: VoiceBankScript = VoiceBankScript.new()
var _busy: bool = false

@onready var _status: Label = $Status
@onready var _tree: Tree = $Lines
@onready var _refresh_btn: Button = $Buttons/Refresh
@onready var _play_btn: Button = $Buttons/Play
@onready var _regen_btn: Button = $Buttons/Regenerate
@onready var _player: AudioStreamPlayer = $Player
@onready var _http: HTTPRequest = $Http


func _ready() -> void:
	add_child(_bank)
	_tree.set_column_title(0, "Line")
	_tree.set_column_title(1, "Text")
	_tree.set_column_expand(0, false)
	_tree.set_column_custom_minimum_width(0, 120)
	_tree.item_selected.connect(_update_buttons)
	_tree.nothing_selected.connect(_update_buttons)
	_tree.item_activated.connect(_on_play)
	_refresh_btn.pressed.connect(refresh)
	_play_btn.pressed.connect(_on_play)
	_regen_btn.pressed.connect(_on_regenerate)
	var timer := Timer.new()
	timer.wait_time = 2.0
	timer.timeout.connect(_on_tick)
	add_child(timer)
	timer.start()
	refresh()


func _on_tick() -> void:
	if is_visible_in_tree():
		_update_buttons()


func _manifest_path() -> String:
	return str(ProjectSettings.get_setting(SETTING_MANIFEST, DEFAULT_MANIFEST))


## Reloads the manifest and rebuilds the tree.
func refresh() -> void:
	_tree.clear()
	var root := _tree.create_item()
	var err := _bank.load_manifest(_manifest_path())
	if err != OK:
		_status.text = "No manifest at %s" % _manifest_path()
		_update_buttons()
		return
	var count := 0
	for voice in _bank.get_voices():
		var voice_item := _tree.create_item(root)
		voice_item.set_text(0, voice)
		voice_item.set_selectable(0, false)
		voice_item.set_selectable(1, false)
		for id in _bank.get_line_ids(voice):
			var line_item := _tree.create_item(voice_item)
			line_item.set_text(0, id)
			line_item.set_text(1, str(_bank.get_entry(voice, id).get("text", "")))
			line_item.set_metadata(0, [voice, id])
			count += 1
	_status.text = "%d lines" % count
	_update_buttons()


func _selected() -> Array:
	var item := _tree.get_selected()
	if item == null or item.get_metadata(0) == null:
		return []
	return item.get_metadata(0)


func _session_path() -> String:
	return _manifest_path().get_base_dir().path_join(SESSION_FILE)


## Port and token from the session file, or an empty dictionary if the app is closed.
func _read_session() -> Dictionary:
	var path := _session_path()
	if not FileAccess.file_exists(path):
		return {}
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return {}
	var session: Dictionary = parsed
	var port: Variant = session.get("port")
	var token: Variant = session.get("token")
	if typeof(port) != TYPE_FLOAT and typeof(port) != TYPE_INT:
		return {}
	if float(port) != floorf(float(port)) or int(port) < 1 or int(port) > 65535:
		return {}
	if typeof(token) != TYPE_STRING:
		return {}
	var re := RegEx.create_from_string(TOKEN_PATTERN)
	if re.search(token) == null:
		return {}
	return {"port": int(port), "token": token}


func _update_buttons() -> void:
	var has_line := not _selected().is_empty()
	_play_btn.disabled = not has_line
	var app_open := not _read_session().is_empty()
	_regen_btn.disabled = _busy or not has_line or not app_open
	if not app_open:
		_regen_btn.tooltip_text = "The VoiceBake app is not running (no %s found)." % SESSION_FILE
	else:
		_regen_btn.tooltip_text = "Regenerate the selected line in the VoiceBake app."


func _on_play() -> void:
	var sel := _selected()
	if sel.is_empty():
		return
	var stream := _bank.get_stream(sel[0], sel[1])
	if stream == null:
		_status.text = "Not imported yet. Wait for the editor to import the file."
		return
	_player.stream = stream
	_player.play()


func _on_regenerate() -> void:
	var sel := _selected()
	var session := _read_session()
	if sel.is_empty() or session.is_empty():
		_update_buttons()
		return
	var url := "http://127.0.0.1:%d/regenerate" % int(session["port"])
	var headers := PackedStringArray([
		"Authorization: Bearer %s" % str(session["token"]),
		"Content-Type: application/json",
	])
	var body := JSON.stringify({"line_id": sel[1]})
	_busy = true
	var err := _http.request(url, headers, HTTPClient.METHOD_POST, body)
	if err != OK:
		_busy = false
		_status.text = "Could not send request (error %d)." % err
		_update_buttons()
		return
	_status.text = "Regenerating %s ..." % sel[1]
	_update_buttons()
	var result: Array = await _http.request_completed
	_busy = false
	if not is_instance_valid(self) or not is_inside_tree():
		return
	await _on_regenerated(sel, result[0], result[1], result[3])


func _on_regenerated(sel: Array, result: int, code: int, raw: PackedByteArray) -> void:
	var reply: Variant = JSON.parse_string(raw.get_string_from_utf8())
	if result != HTTPRequest.RESULT_SUCCESS or typeof(reply) != TYPE_DICTIONARY:
		_status.text = "Request failed (result %d, HTTP %d). Is the app still open?" % [result, code]
		_update_buttons()
		return
	var data: Dictionary = reply
	if code != 200 or not data.get("ok", false):
		_status.text = "Regenerate failed: %s" % str(data.get("error", "HTTP %d" % code))
		_update_buttons()
		return
	_bank.load_manifest(_manifest_path())
	var path := _bank.get_path_for(sel[0], sel[1])
	_status.text = "Importing %s ..." % sel[1]
	var imported := await _import_file(path)
	if not is_instance_valid(self) or not is_inside_tree():
		return
	var stream: AudioStream = null
	if imported:
		stream = _bank.get_stream(sel[0], sel[1], true)
	if stream == null:
		_status.text = "Regenerated %s but Godot has not imported %s yet. Press Play shortly." % [sel[1], path]
	else:
		_status.text = "Regenerated %s (%.1f s)" % [sel[1], float(data.get("duration", 0.0))]
		_player.stream = stream
		_player.play()
	_update_buttons()


## Imports a new or changed file and waits (up to about 10 s) until it can be loaded.
func _import_file(path: String) -> bool:
	var fs := EditorInterface.get_resource_filesystem()
	fs.update_file(path)
	fs.reimport_files(PackedStringArray([path]))
	for i in 20:
		if ResourceLoader.exists(path) and not fs.is_scanning():
			return true
		if i == 2:
			fs.scan()
		await get_tree().create_timer(0.5).timeout
		if not is_instance_valid(self):
			return false
	return ResourceLoader.exists(path)
