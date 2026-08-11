# Third-Party Notices

Meeting Memory includes open-source Python and macOS components. The primary
runtime packages are listed below; their license metadata and license texts are
also retained in the bundled Python distribution metadata.

| Package | License |
| --- | --- |
| Anthropic Python SDK | MIT |
| AssemblyAI Python SDK | MIT |
| boto3 / botocore | Apache-2.0 |
| Google API Python Client and Google Auth OAuthlib | Apache-2.0 |
| FFmpeg 8.1.2 minimal AAC encoder | LGPL-2.1-or-later |
| keyring | MIT |
| pydantic and pydantic-settings | MIT |
| python-dotenv | BSD-3-Clause |
| rumps | BSD |
| PyInstaller bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception |

The bundled FFmpeg executable is a separate, minimal command-line program.
Its exact source, checksum, build flags, and relinking information are in
`FFMPEG_SOURCE_OFFER.md`; its license text is in
`FFMPEG-COPYING.LGPLv2.1`. The corresponding verified
`ffmpeg-8.1.2.tar.xz` source archive is bundled beside them.

The source repository and Python package metadata are the authoritative source
for exact dependency versions. Meeting Memory itself is distributed under the
MIT license in `LICENSE`.
