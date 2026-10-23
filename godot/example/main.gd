extends Node
## Plays one baked line through VoiceBank.
##
## Bake the starter project into godot/voice first (res://voice in this project; set
## paths.out in voicebake.toml to that folder), then run the scene.
## The voice and line id below come from the starter example.

const VoiceBankScript := preload("res://addons/voicebake/voice_bank.gd")
const MANIFEST := "res://voice/manifest.json"
const VOICE := "mechanic"
const LINE_ID := "mech_greet_01"


func _ready() -> void:
	var bank: VoiceBankScript = VoiceBankScript.new()
	add_child(bank)
	if bank.load_manifest(MANIFEST) != OK:
		print("No manifest at %s. Bake some lines first." % MANIFEST)
		return
	if not bank.has_line(VOICE, LINE_ID):
		print("Line %s/%s is not in the manifest." % [VOICE, LINE_ID])
		return
	bank.play(VOICE, LINE_ID)
