"""Generate clearly synthetic camera/audio inputs for the loopback browser test."""

import math, struct, subprocess, wave
import imageio_ffmpeg

subprocess.run(
    [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=10",
        "-t",
        "60",
        "-c:v",
        "libvpx",
        "-b:v",
        "100k",
        "/private/tmp/coach-baseline.webm",
    ],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
with wave.open("/private/tmp/coach-voice.wav", "wb") as stream:
    stream.setparams((1, 2, 48000, 0, "NONE", "none"))
    stream.writeframes(
        b"".join(
            struct.pack("<h", int(10000 * math.sin(i * 2 * math.pi * 180 / 48000)))
            for i in range(48000 * 60)
        )
    )
