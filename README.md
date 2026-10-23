# qwen-voicebake

qwen-voicebake turns a list of game dialogue lines into audio files using the Qwen3-TTS
models. You describe each character's voice in a sentence, write the lines with a tone for
each one, and run a bake. It writes one `.ogg` (or `.wav`) per line plus a `manifest.json`
your game can read. Only lines whose inputs changed are baked again.

It has three parts:

- `voicebake`, a command line tool for checking and baking a project.
- `voicebake-app`, a desktop app (PySide6) for editing voices and lines, choosing reference
  clips, and baking.
- A Godot 4.3+ addon with an editor dock and a `VoiceBank` node for playing lines at runtime.

<img src="https://raw.githubusercontent.com/cwcorella-git/qwen-voicebake/main/docs/images/lines.png" width="960" alt="The Lines tab of the desktop app">

## How it works

Qwen3-TTS comes in two kinds of model:

- **VoiceDesign** creates a voice from a text description, such as "A man in his sixties
  with a low, gravelly voice." Each call can sound like a slightly different person.
- **Base** clones a voice from a short audio clip and its transcript. Every line cloned
  from the same clip sounds like the same person.

qwen-voicebake uses both. For each voice and each tone that voice uses, VoiceDesign speaks
the voice's reference sentence in that tone. That clip is the reference. Base then clones
every line from the reference that matches the line's tone.

Cloning copies the emotion of the reference along with the voice. A calm reference gives
calm lines, even when the text is shouted. This is why references are made per tone: an
angry line is cloned from an angry reference of the same voice. See
[docs/EMOTION.md](docs/EMOTION.md) for more on getting a range of emotion.

```
voices.json        lines.json         tones (built-in + tones.toml)
     |                  |                  |
     +--------+---------+---------+--------+
              |                   |
              v                   v
  VoiceDesign: one reference   VoiceDesign: lines with kind "vocal"
  per (voice, tone) pair       or a direction
  -> refs/<voice>/<tone>.ogg            |
              |                         |
              v                         |
  Base: clone every other line          |
  from its matching reference           |
              |                         |
              +------------+------------+
                           v
            <out>/<voice>/<line id>.ogg + manifest.json
```

## Models

| Model | Used for | Size |
|---|---|---|
| [Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign) | references, vocal lines, lines with a direction | 1.7B |
| [Qwen/Qwen3-TTS-12Hz-1.7B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base) | cloning (default) | 1.7B |
| [Qwen/Qwen3-TTS-12Hz-0.6B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base) | cloning, smaller and faster | 0.6B |

VoiceDesign only exists at 1.7B.

The models are made by the Qwen team at Alibaba and released under the Apache-2.0 license.
qwen-voicebake runs them through the `qwen-tts` package (also Apache-2.0). The weights are
downloaded from Hugging Face the first time they are used and are not part of this
repository.

Supported languages: English, Chinese, Japanese, Korean, German, French, Russian,
Portuguese, Spanish, Italian.

## Hardware and platforms

- **Linux and Windows with an NVIDIA GPU (CUDA):** supported. In our test a 12 GB card held one 1.7B
  model at a time, so qwen-voicebake keeps one model loaded and swaps when needed.
- **macOS:** experimental. It runs on `mps` and falls back to `cpu` if `mps` fails. Expect
  it to be slow.
- **CPU only:** works, but slowly. Useful for testing with a handful of lines.

One measurement on an RTX 3080 Ti (12 GB), 1.7B models, bfloat16, sdpa attention:

| Step | Time |
|---|---|
| Importing torch and qwen-tts | about 40 s |
| Loading a model | about 47 s |
| First line after loading | about 27 s |
| Each following line | 4.5 to 6 s |
| Swapping between VoiceDesign and Base | 26 to 34 s |

Your numbers will differ with hardware, drivers and line length. A bake does all
VoiceDesign work first and all cloning second, so a normal bake swaps models once.

## Install

Python 3.10 or newer.

1. Install PyTorch for your platform first, using the selector at
   [pytorch.org](https://pytorch.org/get-started/locally/). Pick the CUDA build if you have
   an NVIDIA GPU. Installing qwen-voicebake first may pull in a CPU-only torch.
2. Install qwen-voicebake with the model and app extras:

   ```
   pip install "qwen-voicebake[tts,app]"
   ```

   or from a clone of this repository:

   ```
   pip install -e ".[tts,app]"
   ```

Extras:

| Extra | Adds |
|---|---|
| `tts` | `qwen-tts` and `torch`, needed for real synthesis |
| `app` | PySide6, needed for `voicebake-app` |
| `loudness` | `pyloudnorm`, needed for `normalize` in `voicebake.toml` |
| `all` | all of the above |
| `dev`, `test-app` | ruff, pytest, pillow, pytest-qt for development |

Without `tts` you can still run `check`, `bake --dry-run`, `bake --fake` and the app with
`--fake`. These write placeholder tones instead of speech.

Optional: on Linux with a supported GPU you can install `flash-attn` and set
`attn = "flash_attention_2"` under `[engine]`. The default, `sdpa`, needs nothing extra.

## Quick start

```
voicebake init my_voices          # copy the starter example
cd my_voices
voicebake check                   # validate the files
voicebake bake --dry-run          # see what would be baked
voicebake bake                    # bake for real
voicebake-app                     # or do the same in the desktop app
```

The starter project has three voices, twelve lines (two vocal lines and one with a
direction) and one custom tone. Edit `voices.json` and `lines.json`, then bake again. Only
the changed lines are rebaked.

Set `out` under `[paths]` to a folder inside your game, for example
`out = "../my_game/voice"`, so baked files land where the game loads them.

The first real bake takes a few minutes before the first line appears. See
[First run is slow](#first-run-is-slow).

## Concepts

### Project

A project is a folder with `voicebake.toml`. The CLI finds it by looking in the current
directory and its parents, or you pass `--project DIR`. Paths in `voicebake.toml` are
relative to that folder.

Files in a project:

| Path | Contents |
|---|---|
| `voicebake.toml` | settings (see [Configuration](#configuration)) |
| `voices.json` | voice descriptions |
| `lines.json` or a `.csv` | the lines |
| `tones.toml` | optional project tones |
| `refs/` | reference clips and `refs.lock.json` |
| `.voicebake/` | ledger, candidates, rejected takes, lock file |
| `<out>/` | baked lines and `manifest.json` |

Commit `voicebake.toml`, `voices.json`, the lines file, `tones.toml` and `refs/`. Add
`.voicebake/` and `.voicebake-session` to `.gitignore`.

### Voices

`voices.json`:

```json
{
  "version": 1,
  "voices": {
    "mechanic": {
      "instruct": "A man in his sixties with a low, gravelly voice. Speaks slowly and dryly.",
      "ref_text": "Hand me that wrench, would you? The one with the green tape.",
      "seed": 1234,
      "temperature": null,
      "language": null
    }
  }
}
```

| Field | Meaning |
|---|---|
| `instruct` | The voice description sent to VoiceDesign. Describe the voice: age, pitch, texture, pace. |
| `ref_text` | The sentence spoken in every reference clip for this voice. One or two natural sentences work well. |
| `seed` | Random seed for design calls. Changing it gives a different take of the same description. |
| `temperature` | Overrides `[engine] temperature` for this voice. `null` uses the project value. |
| `language` | Overrides `[engine] language` for this voice. `null` uses the project value. |

Voice names may contain letters, digits, `_`, `.` and `-`.

### Lines

`lines.json`:

```json
{
  "version": 1,
  "lines": [
    {"id": "mech_greet_01", "voice": "mechanic", "tone": "warm",
     "text": "Back again? Pull up a stool, the kettle is on.", "kind": "speech", "direction": ""}
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | Unique id, letters, digits, `_`, `.` and `-`. It becomes the file name. |
| `voice` | A voice from `voices.json`. |
| `tone` | A built-in or project tone. Defaults to `neutral`. |
| `text` | What is said. |
| `kind` | `speech` (default) or `vocal`. |
| `direction` | Optional extra instruction for this one line. |

Lines can also come from a CSV file with the header `id,voice,tone,text,kind,direction`
(read-only in the app, which offers to convert it to JSON), or from a scanner script that
reads them from your game's source. See [docs/SCANNERS.md](docs/SCANNERS.md).

### Tones

A tone is a phrase added after the voice description, such as
"Right now: tense and afraid, breath tight, quick and low." There are 48 built-in tones,
listed in [docs/TONES.md](docs/TONES.md). Add your own or override a built-in in
`tones.toml`:

```toml
[tones]
dry = "Right now: deadpan and dry, understated."
```

### Kinds: speech and vocal

`speech` lines are cloned from a reference. `vocal` lines are grunts, sighs, gasps, laughs
and other sounds without words, such as `Hnngh!` or `*sigh*`. Cloning tends to turn these
into spoken words, so vocal lines go through VoiceDesign directly with a short token limit
(`vocal_max_new_tokens`). `voicebake check` warns when a speech line looks wordless and
reports an error when a vocal line has more than 6 words.

### Direction

A line's `direction` is appended to the voice description and tone for that line only,
for example "Whispering, glancing over a shoulder." A line with a direction is made with
VoiceDesign instead of cloned, because a clone cannot take new instructions. The voice can
drift slightly from the reference on these lines. Use directions for the few lines that
need them.

### References

A reference is one VoiceDesign clip per (voice, tone) pair used by speech lines without a
direction, stored at `refs/<voice>/<tone>.ogg`. `refs/refs.lock.json` records what each
reference was made from. Reference states:

| State | Meaning |
|---|---|
| `missing` | Not made yet. The next bake designs it. |
| `ok` | Matches the current voice, tone and model settings. |
| `stale` | The voice, tone or design settings changed. The next bake redesigns it. |
| `modified` | The file differs from the one recorded, for example replaced by hand. Used as it is. Only `--force-refs` replaces it. |
| `pinned` | Chosen by you. Never redesigned. |
| `pinned-stale` | Pinned, but its inputs changed. Bakes keep using it and print a warning. Unpin it to let it be redesigned. |

A reference sets the sound of every cloned line in that tone, so it is worth listening to.
To choose one, generate candidates with different seeds, listen, and pick one:

```
voicebake refs candidates mechanic anger -n 4
voicebake refs pick mechanic anger 1236
```

Picking copies the candidate to `refs/` and pins it. Candidates are kept in
`.voicebake/candidates/<voice>/<tone>/seed<N>.ogg`.

When a reference changes, every line cloned from it becomes stale and is rebaked.

You can also record a reference yourself and put it at `refs/<voice>/<tone>.ogg`, speaking
the voice's `ref_text`. It shows as `modified` and is used as it is.

### Human takes

To keep a recorded or edited file for a line, create an empty marker file next to it named
`<line id>.<ext>.human`, for example `voice/mechanic/mech_greet_01.ogg.human`. The app's
**Mark as Human Take** button does this. Bakes never touch a line with a marker. Delete the
marker to let the line be baked again.

### Ledger, staleness and QA

`.voicebake/ledger.json` stores a hash of the inputs for every baked file. A line is
rebaked when its text, tone text, voice description, reference audio, model, temperature,
language, output format or normalize setting changes. Line states are `new`, `stale`,
`ok`, `failed` and `human`.

Each take is checked after synthesis:

- Longer than `max_seconds` or shorter than `min_seconds`: rejected. The file is not
  written to the output folder; it is saved to `.voicebake/rejected/` so you can listen to
  it, and the line is marked `failed`.
- A multi-word speech line whose seconds per word fall outside `sec_per_word`, or a
  one-word speech line longer than `one_word_max`: kept and reported as a soft QA warning.

Audio is trimmed of silence at both ends (keeping 0.03 s) before it is written. NaNs are
removed and samples are clipped to the range -1 to 1.

### Manifest

After every bake, `<out>/manifest.json` lists each line whose file exists:

```json
{"version": 1, "format": "ogg",
 "voices": {"mechanic": {"mech_greet_01": {"path": "mechanic/mech_greet_01.ogg",
   "text": "...", "tone": "warm", "route": "clone", "duration": 2.91}}}}
```

`path` is relative to the output folder. `route` is `clone` or `design`.

## Configuration

All keys in `voicebake.toml`, with defaults. Unknown sections or keys are an error.

```toml
[engine]
design_model = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
clone_model = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
language = "English"
temperature = 0.5
device = "auto"
dtype = "bfloat16"
attn = "sdpa"
max_new_tokens = 2048
vocal_max_new_tokens = 48

[paths]
voices = "voices.json"
lines = "lines.json"
scanner = ""
tones = "tones.toml"
refs = "refs"
out = "voice"
format = "ogg"
normalize = false

[qa]
max_seconds = 12.0
min_seconds = 0.2
sec_per_word = [0.12, 1.2]
one_word_max = 3.5

[app]
port = 47811
```

| Key | Meaning |
|---|---|
| `engine.design_model` | Model used for references, vocal lines and lines with a direction. |
| `engine.clone_model` | Model used for cloning. `Qwen/Qwen3-TTS-12Hz-0.6B-Base` is smaller and faster. |
| `engine.language` | Default language for every voice. |
| `engine.temperature` | Sampling temperature. Lower is steadier, higher is more varied. |
| `engine.device` | `auto`, `cuda`, `mps` or `cpu`. `auto` picks cuda, then mps, then cpu. |
| `engine.dtype` | Model precision on CUDA. On mps and cpu, float32 is always used. |
| `engine.attn` | Attention implementation: `sdpa`, `flash_attention_2` (needs flash-attn) or `eager`. |
| `engine.max_new_tokens` | Upper limit on generated length for speech. |
| `engine.vocal_max_new_tokens` | Upper limit for vocal lines, which keeps them short. |
| `paths.voices` | Voices file. |
| `paths.lines` | Lines file, `.json` or `.csv`. |
| `paths.scanner` | Optional Python scanner script. When set, it replaces the lines file. It is Python code that runs whenever the project is opened or checked, so only open projects you trust. |
| `paths.tones` | Project tones file. Optional. |
| `paths.refs` | Folder for reference clips. |
| `paths.out` | Output folder for baked lines and `manifest.json`. |
| `paths.format` | `ogg` (Vorbis) or `wav` (16-bit PCM). |
| `paths.normalize` | `false`, `true` (-18 LUFS) or a LUFS number such as `-16`. Needs the `loudness` extra. |
| `qa.max_seconds` | Takes longer than this are rejected. |
| `qa.min_seconds` | Takes shorter than this are rejected. |
| `qa.sec_per_word` | `[low, high]` range for multi-word speech lines; outside it is a soft warning. |
| `qa.one_word_max` | Soft warning above this length for one-word speech lines. |
| `app.port` | Port for the app's local HTTP server on 127.0.0.1. |

## Command line

Every command accepts `--project DIR`. Without it, the project is found from the current
directory upward.

| Command | What it does |
|---|---|
| `voicebake init [DIR] [--example starter]` | Copies the starter example into `DIR` (default: current directory). Refuses to overwrite files. |
| `voicebake check [--strict]` | Validates voices, lines and tones. Exits 1 on errors, or on warnings with `--strict`. |
| `voicebake bake` | Bakes new, stale and failed lines. Options below. |
| `voicebake status` | Counts lines by state, shows whether the project is locked and whether the manifest exists. |
| `voicebake refs status [--voice V]` | Lists the state of each reference. |
| `voicebake refs candidates VOICE TONE [-n 4] [--seeds 1,2] [--fake]` | Designs candidate references. Without `--seeds`, uses consecutive seeds starting at the voice's seed. |
| `voicebake refs pick VOICE TONE SEED` | Copies a candidate into `refs/` and pins it. |
| `voicebake refs pin VOICE TONE` | Pins the current reference. |
| `voicebake refs unpin VOICE TONE` | Unpins it so bakes can redesign it. |

`bake` options:

| Option | Effect |
|---|---|
| `--voices a,b` | Only these voices. |
| `--lines glob,...` | Only line ids matching these globs, for example `mech_*`. |
| `--force` | Rebake lines that are up to date (human takes are still skipped). |
| `--force-refs` | Redesign unpinned references, including `modified` ones. |
| `--dry-run` | Print the plan and synthesize nothing. |
| `--limit N` | Bake at most N lines. |
| `--fake` | Placeholder audio, no model. |

`bake` runs `check` first and stops if there are errors. Exit codes: 0 success; 1 check
errors or failed takes; 2 usage error; 3 the project is locked by another process (the
app or another bake).

Example output:

```
ref   mechanic/warm  via design  3.12 s
take  mech_grunt_01  via design  0.84 s
take  mech_greet_01  via clone  2.91 s
baked 12, failed 0, up to date 0, human 0, soft QA 0, 241.3 s
```

## Desktop app

```
voicebake-app [--project DIR] [--fake]
```

Without `--project` it opens the last project. `--fake` uses placeholder audio and loads no
model. The app holds a lock on the project while it is open; if another process holds it,
the project opens read-only.

<table>
<tr>
<td><img src="https://raw.githubusercontent.com/cwcorella-git/qwen-voicebake/main/docs/images/welcome.png" width="460" alt="Start screen"></td>
<td><img src="https://raw.githubusercontent.com/cwcorella-git/qwen-voicebake/main/docs/images/voices.png" width="460" alt="Voices tab"></td>
</tr>
<tr>
<td><img src="https://raw.githubusercontent.com/cwcorella-git/qwen-voicebake/main/docs/images/references.png" width="460" alt="References tab"></td>
<td><img src="https://raw.githubusercontent.com/cwcorella-git/qwen-voicebake/main/docs/images/bake.png" width="460" alt="Bake tab"></td>
</tr>
</table>

- **Voices**: add, rename and remove voices. Edit the description, reference text, seed,
  temperature and language. Renaming a voice also updates its lines.
- **Lines**: a table of id, voice, tone, kind, direction, text and state, with a filter.
  Play a take, Regenerate one line, or Mark as Human Take. When lines come from a CSV file
  or a scanner, the table is read-only; for CSV a Convert to JSON button writes
  `lines.json` and updates `voicebake.toml`.
- **References**: pick a voice to see each tone it needs a reference for, with status,
  length, seed and line count. Play or Pin/Unpin a reference. Generate Candidates makes
  several takes with different seeds; Use This One pins the selected candidate.
- **Bake**: Bake Changed, Bake All and Cancel. Cancel stops after the current line. Shows
  progress, a log and a list of QA problems.

The status bar shows the device, the loaded model, how many lines need baking and the
local server address. File > Save writes `voices.json` and `lines.json`; the app asks
before closing with unsaved changes.

The model loads on the first job, not at start-up, so the app opens quickly.

### Local HTTP API

While the app is open it serves a small HTTP API on `127.0.0.1:<app.port>` for editor
integrations. The Godot addon uses it. If the port is taken, the app runs without it.

On start the app writes `<out>/.voicebake-session`, a JSON file with `port` and `token`,
readable only by your user. It is deleted when the app closes. Add `.voicebake-session`
to your `.gitignore`.

Every request must send `Authorization: Bearer <token>` and a `Host` of
`127.0.0.1:<port>` or `localhost:<port>`. Requests with an `Origin` header are refused, which
blocks requests made by web pages in a browser.

| Request | Response |
|---|---|
| `GET /status` | `{project, model, device, busy, queued}` |
| `GET /lines` | `[{id, voice, tone, state, path}]`; `path` is absolute, or `null` if not baked |
| `POST /regenerate` with `{"line_id": "...", "seed": 7}` (`seed` optional) | `{ok, path, rel, route, qa, duration}` or `{ok: false, error}` |

`POST` bodies must be `Content-Type: application/json`. `/regenerate` waits for the line
to finish, up to 300 seconds. On timeout, a job still waiting in the queue is cancelled and
the response is an `{ok: false, error}` saying so. A job that is already running is not
interrupted: the response is `{"ok": false, "error": "timed out; the line may still finish
and appear in the manifest"}`. It rebakes one line from the saved project files, designs its
reference first if needed, and updates the manifest.

```
TOKEN=$(python -c "import json;print(json.load(open('voice/.voicebake-session'))['token'])")
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:47811/status
```

## Godot addon

The `godot/` folder is a Godot 4.3+ project with the addon enabled and an example scene.
To use the addon in your game:

1. Copy `godot/addons/voicebake` to `res://addons/voicebake/` in your project.
2. Enable it under Project Settings > Plugins.
3. Set `out` in `voicebake.toml` to a folder inside your project, normally the folder
   that is `res://voice`.

The **VoiceBake dock** lists baked lines by voice. Play (or double-click) plays a line in
the editor. Regenerate asks the running app to rebake the selected line, then imports and
plays the new file. Regenerate is disabled when the app is not running. The plugin checks
`manifest.json` every 2 seconds and rescans the project when it changes.

The manifest path is the project setting `voicebake/manifest_path` (default
`res://voice/manifest.json`). The dock reads `.voicebake-session` from the same folder.

A newly written `.ogg` plays silently until Godot has imported it. The dock and the
rescan handle this in the editor. If you bake from the command line while the editor is
closed, Godot imports the files the next time it opens.

At runtime, use `VoiceBank`:

```gdscript
var bank := VoiceBank.new()
add_child(bank)
bank.load_manifest("res://voice/manifest.json")
if bank.has_line("mechanic", "mech_greet_01"):
    bank.play("mechanic", "mech_greet_01")
```

`manifest.json` is not a Godot resource, so exports leave it out unless you add it. In
the export preset, under Resources, add `voice/*.json` to "Filters to export non-resource
files/folders". The audio files export normally.

[godot/addons/voicebake/README.md](godot/addons/voicebake/README.md) lists the full
`VoiceBank` API.

## Scanners

If your lines live in your game's scripts or data files, a scanner script can read them
so you do not keep a separate `lines.json`. Set `scanner = "tools/my_scanner.py"` under
`[paths]`. The contract and an example are in [docs/SCANNERS.md](docs/SCANNERS.md).

A scanner is Python code that runs whenever the project is opened or checked. Only open
projects you trust.

## Troubleshooting

### First run is slow

The first real bake downloads the models from Hugging Face (several GB each), then imports
torch and qwen-tts and loads a model onto the GPU. On the test machine above, import and
load took about a minute and a half and the first line about 27 s more. Later lines take
seconds. Downloads happen once; the import and load happen every time a bake or the app
starts synthesizing.

### Out of GPU memory

Close other programs using the GPU. Set `clone_model` to
`Qwen/Qwen3-TTS-12Hz-0.6B-Base`. Lower `max_new_tokens` if very long lines run out of
memory. On 8 GB cards or smaller, expect trouble with the 1.7B models.

### Why does it load one model at a time?

On a 12 GB card the two 1.7B models do not fit together. The bake orders work so it swaps
once: all VoiceDesign work, then all cloning.

### "looks wordless; mark kind: vocal"

`check` found a speech line that looks like a sound, such as `Hmph` or `*gasp*`. Set its
`kind` to `vocal`. Cloned sounds often come out as spoken words.

### A take was rejected

It was longer than `max_seconds` or shorter than `min_seconds`, which usually means the
model ran on or produced nothing. Listen in `.voicebake/rejected/`, then bake again; a
failed line is retried on every bake. Try a different seed with Regenerate, a different
reference, or reword the line.

### The same seed sounds different on another machine

Sampling results differ across GPUs, drivers and library versions, even with the same
seed. This is why references are stored as audio files in `refs/` and committed, rather
than regenerated from seeds. Cloned lines made from the same reference keep the same voice
on any machine.

### "project locked"

Another `voicebake bake` or the app has the project open. The lock is released when it
exits. A lock left by a crashed process is ignored after 30 seconds.

### Regenerate in Godot is disabled

The app is not running, or `paths.out` is not the folder that holds the manifest the dock
reads. If the app crashed, a stale `.voicebake-session` may remain; delete it or restart
the app.

## Contributing

```
pip install -e ".[dev,app,test-app,loudness]"
ruff check .
pytest
python scripts/gen_tones_md.py --check
```

Tests run without a GPU, using a placeholder engine. `docs/TONES.md` is generated from the
built-in tone list; run `python scripts/gen_tones_md.py` after changing it. The README
screenshots are made with `python scripts/capture_screenshots.py`, which runs the app
offscreen with placeholder audio. `python scripts/gpu_smoke.py` is a manual end-to-end
test on real models.

## License

The code is MIT licensed (see [LICENSE](LICENSE)). The Qwen3-TTS models are released by
Alibaba's Qwen team under the Apache-2.0 license and are covered by their own license
terms, not this repository's.
