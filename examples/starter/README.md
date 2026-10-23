# Starter project

Three voices, twelve lines (two vocal, one with a direction) and one custom tone.

    voicebake check
    voicebake bake --dry-run
    voicebake bake --fake      # placeholder audio, no GPU needed
    voicebake bake             # real synthesis; needs the tts extra and a GPU

Edit voices.json and lines.json, or run `voicebake-app`. Output goes to voice/.
To read lines from game scripts instead, set `scanner` in voicebake.toml; see
tools/example_scanner.py and game/shopkeeper.gd.
