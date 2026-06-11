# BlackHole Setup

This app records from the macOS audio device named by `AUDIO_DEVICE`. The
default is `Meeting Aggregate`.

The expected setup is:

- BlackHole 2ch installed
- A macOS Aggregate Device named `Meeting Aggregate`
- The aggregate includes the microphone and BlackHole
- `AUDIO_DEVICE=Meeting Aggregate` in `.env`

References:

- BlackHole: https://github.com/ExistentialAudio/BlackHole
- Apple Audio MIDI Setup help: https://support.apple.com/guide/audio-midi-setup/

## Install BlackHole 2ch

BlackHole's README documents both installer and Homebrew paths. The Homebrew
command is:

```bash
brew install blackhole-2ch
```

After installing, close and reopen audio applications. Restart macOS if the
installer prompts for it or if BlackHole does not appear in Audio MIDI Setup.

## Create the Aggregate Device

1. Open `Audio MIDI Setup`.
2. In the lower-left `+` menu, choose `Create Aggregate Device`.
3. Rename it to `Meeting Aggregate`.
4. Enable your microphone input.
5. Enable `BlackHole 2ch`.
6. Use the microphone as the clock source when available.
7. Enable drift correction for every non-clock-source device.
8. Set the aggregate sample rate to a value supported by both devices.

The app captures at 16 kHz mono and writes 16-bit WAV before converting to M4A.
macOS may expose the physical device at a higher native sample rate; the app
requests the recording format through `sounddevice`.

## Route Meeting Audio

For the app to capture remote participants, meeting audio must reach BlackHole.
The usual macOS pattern is:

1. In Audio MIDI Setup, create a Multi-Output Device containing:
   - your normal output device or headphones
   - `BlackHole 2ch`
2. Set the Multi-Output Device as system output.
3. Keep `Meeting Aggregate` as the app recording input through `.env`.

If you cannot hear audio after switching output, switch system output back to
your speakers/headphones. Multi-output volume control can be awkward on macOS;
set levels before joining the meeting.

## Configure `.env`

```bash
AUDIO_DEVICE=Meeting Aggregate
```

Then run:

```bash
make doctor
```

Expected success line:

```text
[OK] audio-device: Audio device exists: Meeting Aggregate.
```

If doctor reports the device missing, confirm the exact device name in Audio
MIDI Setup and update `AUDIO_DEVICE`.

## Validation

After setup, run the manual recording section in
[manual-validation.md](manual-validation.md).
