# Getting emotional range

This page covers how to get lines that sound angry, scared, tired or happy instead of all
sounding the same.

## Why cloning flattens emotion

The Base model clones a voice from a reference clip. It copies the speaker, and it also
copies how the speaker sounded in that clip: pace, energy, mood. If every line is cloned
from one calm reference, every line comes out calm, including "Get out!".

Writing emotion into the line text helps a little. The reference has much more effect.

## Tone-matched references

This is the main tool. qwen-voicebake designs one reference per voice and tone. A line
with tone `anger` is cloned from that voice's `anger` reference, so it inherits the anger.

To get a good set:

1. Use the tones your lines need, and keep the number of tones per voice small. Each
   tone is one more reference to check.
2. Bake once, then listen to each reference in the References tab of the app, or in
   `refs/<voice>/<tone>.ogg`.
3. If a reference is flat or wrong, generate candidates, listen, and pick the best:

   ```
   voicebake refs candidates mechanic anger -n 6
   voicebake refs pick mechanic anger 1237
   ```

   A picked reference is pinned and stays as it is when you edit the voice later.
4. Rebake. Every line cloned from a changed reference is rebaked.

The voice's `ref_text` is spoken in every reference. A neutral sentence that fits most
moods works best. If one tone sounds odd with it, the problem is often the sentence: a
cheerful sentence read in `fear` gives a confused reference.

## Writing tone texts

A tone text is added after the voice description. The built-in tones are in
[TONES.md](TONES.md); you can add or replace tones in `tones.toml`.

- Describe how the voice sounds, not the situation. "Tense and afraid, breath tight,
  quick and low" works better than "The monster is behind the door."
- Name the physical effects: volume, pace, breath, pitch movement, tension.
- Keep it to one short sentence. Long instructions blur together.
- Start with "Right now:" like the built-in tones, so the model reads it as the current
  state rather than a permanent trait of the voice.
- Keep the voice description free of mood. "A man in his sixties with a low, gravelly
  voice" combines with any tone. "A grumpy old man" pulls every tone toward grumpy.

## Per-line direction for big moments

A line's `direction` is added after the tone for that one line, for example "Screaming,
voice breaking on the last word." Lines with a direction are made with VoiceDesign
directly instead of cloned, so they follow the instruction closely.

The cost is consistency. VoiceDesign makes a new voice from the description each time, so
the speaker on these lines can drift slightly from the reference. Use directions for a
few important lines, not as a replacement for tones.

## Recording your own reference takes

A recorded reference often gives the strongest result. Record a few seconds of a person
speaking the voice's `ref_text` in the emotion you want, save it as
`refs/<voice>/<tone>.ogg` (Ogg Vorbis, whatever the output format), and bake. The reference shows
as `modified` and is used as it is. Every line in that tone is then cloned from the
recording.

- One clear sentence, 3 to 10 seconds, with little room noise and no music.
- The words spoken must match `ref_text` exactly.
- Act the emotion clearly. Subtle takes give subtle clones.

Only record people who have agreed to have their voice cloned, and make sure you have the
rights to use the recording in your game.

## Vocal lines

Grunts, sighs, gasps and laughs should be `kind: "vocal"`. They are made with VoiceDesign
and a short length limit. Write them as the sound (`Hnngh!`, `Ha!`, `*sigh*`) and use the
tone to describe it: `injured` for a pained grunt, `relief` for a sigh. If one comes out
as a spoken word, try another seed with Regenerate, or change the spelling.

## Text tricks

The model reads punctuation as delivery:

- Exclamation marks raise energy. Question marks lift the end.
- Ellipses and commas add pauses: "I... I don't know."
- Short sentences sound clipped. Run-on sentences sound rushed.
- Repeated words or broken words read as hesitation: "Wait, wait, I can ex- I can explain."
- Stage words in the text, such as "(laughs)", are unreliable. They may be read aloud. Use
  a vocal line or a direction instead.

## Post-processing

Some effects are easier to add after the bake, in your audio editor or in the game's
audio buses. These are directions to try, not presets. Tune each one by ear on the actual
lines.

- **Size and age:** a small pitch or formant shift makes a voice sound larger, smaller,
  older or younger. Large shifts sound artificial.
- **Radio, helmet, intercom:** band-limit the voice (cut lows and highs) and add a little
  distortion.
- **Synthetic voices:** light ring modulation, a vocoder, or a short chorus.
- **Effort and presence:** layer breaths or noise under the line.
- **Strain or anger:** gentle saturation.
- **Space:** reverb that matches the room the character is in. Godot's audio buses can do
  this per area.

## Other models

Other text-to-speech models offer more direct emotion control. Many of them release their
weights under non-commercial licenses. Check each model's weight license before shipping
a game with its output.
