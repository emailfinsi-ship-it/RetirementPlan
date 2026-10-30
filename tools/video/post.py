"""Joins a recording and its voice track into the finished mp4, and writes where each scene starts.

    python3 tools/video/post.py trading /tmp/tour11_trading_dark help-trading.mp4

The recording runs a little slower than the clock, so the video is sped up to match (the voice stays natural). Each time Fin speaks, a
magenta dot in the corner of the recording lights up; the dot is how the voice is lined up with the picture, and it is painted out
of the final video."""

import glob
import json
import pickle
import subprocess
import sys

import numpy as np
import soundfile as sf

out_dir, out_mp4 = sys.argv[1], sys.argv[2]
vid = glob.glob(out_dir + "/video/*.webm")[0]
FPS, SR = 25, 24000
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", vid, "-vf", f"crop=6:6:0:0,fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                     capture_output=True).stdout
fr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 36, 3).astype(float).mean(axis=1)
mag = (fr[:, 0] > 140) & (fr[:, 2] > 140) & (fr[:, 1] < 120)
runs, i, n = [], 0, len(mag)
while i < n:
    if mag[i]:
        j = i
        while j < n and (mag[j] or mag[j:j + 4].any()):
            j += 1
        runs.append((i, j))
        i = j
    else:
        i += 1
runs = [(a, b) for a, b in runs if b - a >= 8]
events = pickle.load(open(out_dir + "/events.pkl", "rb"))
print("video frames", n, "segments", len(runs), "events", len(events))
if len(runs) != len(events):
    sys.exit("The voice marks in the video do not match the narration (%d vs %d); record it again." % (len(runs), len(events)))
w = np.array([e[0] for e in events])
v = np.array([a / FPS for a, b in runs])
F = float(np.polyfit(w, v, 1)[0])
print("speed factor", round(F, 4))
starts = [a / FPS / F for a, b in runs]
dur = n / FPS / F
track = np.zeros(int((dur + 2) * SR), dtype=np.float32)
for st, (_t, audio) in zip(starts, events):
    k = int(st * SR)
    track[k:k + len(audio)] += audio[:len(track) - k]
sf.write(out_dir + "/narration_synced.wav", track, SR)
scenes = json.load(open(out_dir + "/scenes.json"))
chapters = [{"name": nm, "title": title, "page": path, "start": round(max(0.0, starts[idx] - 1.5), 1)} for nm, title, path, idx in scenes if idx < len(starts)]
json.dump({"duration": round(dur, 1), "chapters": chapters}, open(out_dir + "/chapters.json", "w"), indent=1)
vf = "split[a][b];[b]crop=6:6:8:0[c];[a][c]overlay=0:0,setpts=PTS/%f" % F
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", vid, "-i", out_dir + "/narration_synced.wav", "-filter_complex", "[0:v]" + vf + "[v]", "-map", "[v]",
                "-map", "1:a", "-c:v", "libx264", "-crf", "28", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart", "-shortest", out_mp4], check=True)
print("wrote", out_mp4, "chapters", [(c["title"], c["start"]) for c in chapters])
