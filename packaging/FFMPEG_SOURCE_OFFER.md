# FFmpeg source and relinking information

Meeting Memory bundles a separate executable named
`MeetingMemoryFFmpegAudioEncoder`, built from the unmodified upstream FFmpeg 8.1.2
source. It includes only FFmpeg components available under the GNU Lesser
General Public License version 2.1 or later. Its sole job is converting the
app's 16 kHz mono PCM WAV staging file into AAC/M4A when the host macOS
installation does not provide an AAC encoder through AVFoundation.

The complete corresponding source is the official FFmpeg 8.1.2 release:

- release page: <https://ffmpeg.org/download.html>
- build archive: <https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz>
- archive SHA-256: `464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c`

The executable is reproducibly rebuilt by
`src/meeting_memory/repo/native_audio_build.py`. That file contains the exact
configure arguments and architecture selection used for each release. The
build deliberately disables network support, shared libraries, autodetection,
and every codec or container not needed for PCM WAV to AAC/M4A conversion.

The bundled `FFMPEG-COPYING.LGPLv2.1` file contains the applicable license.
The exact verified source is versioned at
`packaging/vendor/ffmpeg-8.1.2.tar.xz` and is included alongside this document
in the app's Resources directory.
