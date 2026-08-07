# Removing the Legacy BlackHole Setup

Meeting Memory no longer requires BlackHole, an Aggregate Device, a
Multi-Output Device, or a configured `AUDIO_DEVICE`. Native macOS capture keeps
the current input and output selections untouched, including AirPods.

If those devices are useful to another application, keep them. If they were
created only for Meeting Memory, they can be removed.

## Remove a Legacy Aggregate or Multi-Output Device

1. Open **Audio MIDI Setup**.
2. Select the old `Meeting Aggregate` or Multi-Output Device.
3. Click the lower-left `-` button.

## Uninstall BlackHole, Optional

If BlackHole was installed with Homebrew and no other app needs it:

```bash
brew uninstall blackhole-2ch
```

Restart any open meeting applications afterward. BlackHole's upstream
documentation covers non-Homebrew uninstall paths:
<https://github.com/ExistentialAudio/BlackHole>.

## Current Audio Modes

- **Full Meeting** captures system audio and the current macOS microphone while
  playback continues through the current output.
- **Silent System Only** captures system audio with the microphone off and
  playback muted.

Run `make setup`, grant the permissions requested by macOS, and use
[manual-validation.md](manual-validation.md) to validate both modes.
