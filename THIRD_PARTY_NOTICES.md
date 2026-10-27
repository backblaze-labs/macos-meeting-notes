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
| MLX and MLX Audio | MIT |
| Hugging Face Hub and Transformers | Apache-2.0 |
| Whisper Large v3 Turbo weights | MIT |
| Nemotron 3 Diarization weights | Open Model, Data and Weights License 1.1 |
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

Local models are downloaded separately, rather than included in the application
bundle. The pinned model manifest identifies the exact files and revisions.
Whisper attribution and license are available in the
[upstream model card](https://huggingface.co/openai/whisper-large-v3-turbo).
Nemotron terms are available in its
[upstream model card](https://huggingface.co/nvidia/Nemotron-3-Diarization).
The converted weights are obtained from the corresponding
[Whisper MLX repository](https://huggingface.co/mlx-community/whisper-large-v3-turbo-asr-fp16)
and [Nemotron MLX repository](https://huggingface.co/mlx-community/Nemotron-3-Diarization).
