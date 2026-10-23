@tool
extends EditorPlugin
## Adds the VoiceBake dock and rescans the project when the manifest changes.

const SETTING_MANIFEST := "voicebake/manifest_path"
const DEFAULT_MANIFEST := "res://voice/manifest.json"
const DOCK_SCENE := preload("res://addons/voicebake/dock.tscn")

var _dock: Control
var _timer: Timer
var _last_mtime: int = 0


func _enter_tree() -> void:
	if not ProjectSettings.has_setting(SETTING_MANIFEST):
		ProjectSettings.set_setting(SETTING_MANIFEST, DEFAULT_MANIFEST)
	ProjectSettings.set_initial_value(SETTING_MANIFEST, DEFAULT_MANIFEST)
	ProjectSettings.add_property_info({
		"name": SETTING_MANIFEST,
		"type": TYPE_STRING,
		"hint": PROPERTY_HINT_FILE,
		"hint_string": "*.json",
	})
	_dock = DOCK_SCENE.instantiate()
	add_control_to_dock(DOCK_SLOT_RIGHT_UL, _dock)
	_timer = Timer.new()
	_timer.wait_time = 2.0
	_timer.timeout.connect(_poll_manifest)
	add_child(_timer)
	_timer.start()
	_last_mtime = _manifest_mtime()


func _exit_tree() -> void:
	if _timer != null:
		_timer.queue_free()
	if _dock != null:
		remove_control_from_docks(_dock)
		_dock.queue_free()


func _manifest_path() -> String:
	return str(ProjectSettings.get_setting(SETTING_MANIFEST, DEFAULT_MANIFEST))


func _manifest_mtime() -> int:
	var path := _manifest_path()
	if not FileAccess.file_exists(path):
		return 0
	return FileAccess.get_modified_time(path)


func _poll_manifest() -> void:
	var mtime := _manifest_mtime()
	if mtime == _last_mtime:
		return
	_last_mtime = mtime
	EditorInterface.get_resource_filesystem().scan()
	if _dock != null and _dock.has_method("refresh"):
		_dock.call("refresh")
