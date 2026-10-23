extends Node
# Sample game script. tools/example_scanner.py finds the say(...) calls below.

func greet() -> void:
	say("mechanic", "mech_greet_01", "warm", "Back again? Pull up a stool, the kettle is on.")

func warn() -> void:
	say("mechanic", "mech_warn_01", "anger", "Put that down. It is not a toy.")

func announce() -> void:
	say("announcer", "ann_dock_01", "announcer", "Attention. Docking will begin in three minutes.")

func say(voice: String, id: String, tone: String, text: String) -> void:
	print("%s (%s, %s): %s" % [voice, id, tone, text])
