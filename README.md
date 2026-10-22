# VidFix 🎬✨

**Video Enhancer for Termux** — upscale, color grade, and smooth FPS directly on your Android phone.
**Pemperbagus video langsung dari HP Android** — upscale, color grading, dan interpolasi FPS via Termux.

> No PC. No cloud. 100% on-device with FFmpeg + Python.

---

## ✨ Features / Fitur

| Feature | Presets | Math inside |
|---|---|---|
| 🔍 **Upscaling** | Keep / 720p / 1080p / 1440p / 4K / Custom | Lanczos resampling `L(x) = sinc(x)·sinc(x/3)` + unsharp mask `out = in + a·(in − blur(in))` |
| 🎨 **Color Grading** | Auto-Fix / Vivid / Cinematic / Custom | Gamma `out = 255·(in/255)^(1/γ)`, S-curve contrast, color balance, histogram analysis |
| ⏱️ **FPS Interpolation** | Keep / 30 / 60 / 120 / Custom | Frame blending `(1−α)·A + α·B` and motion-compensated interpolation (aobmc + bidir ME) |
| 🧠 **Content Auto-Detect** | real / anime / game / auto | Unique-color ratio, edge density, Donoho noise estimator `σ = median(|∇²I|)/0.6745` |
| 📱 **RAM Adaptive** | 3/4/6/8/12/16 GB or custom | Auto-detects via `/proc/meminfo`, picks Safe / Balanced / Full Power profile |

Also bilingual: **English 🇬🇧 + Bahasa Indonesia 🇮🇩** (switch in Settings).

---

## 📲 Install (Termux) / Instalasi

```bash
pkg update -y && pkg upgrade -y
pkg install -y git
git clone https://github.com/YOUR_USERNAME/vidfix.git
cd vidfix
bash install.sh
```

The installer installs `python`, `ffmpeg`, `numpy` (prebuilt Termux packages — no compiling), then registers the global command `vidfix`.

---

## 🚀 Usage / Cara Pakai

**Interactive / Interaktif:**
```bash
vidfix
```

**Quick mode (non-interactive):**
```bash
vidfix video.mp4                            # defaults: 1080p + Auto-Fix + 60fps
vidfix video.mp4 -u 2 -c 2 -f 2             # explicit presets
vidfix anime.mp4 -u 3 -c 1 -f 2 --content anime --lang id
vidfix clip.mkv -u 5 --res 2560x1440 -f 4 --fps-val 90
```

**Options:**
```
-u / --upscale   0 keep | 1 720p | 2 1080p | 3 1440p | 4 4K | 5 custom (--res)
-c / --color     0 keep | 1 auto-fix | 2 vivid | 3 cinematic | 4 custom
-f / --fps       0 keep | 1 30fps | 2 60fps | 3 120fps | 4 custom (--fps-val)
--content        auto | real | anime | game
--lang           en | id        --yes    skip confirmation
```

Output is written next to the source as `name_enhanced.mp4` (H.264 CRF 18, audio preserved).

---

## 📱 RAM Profiles / Profil RAM

| Tier | RAM | FPS mode | Notes |
|---|---|---|---|
| 🛡️ Safe | 3–4 GB | blend (light) | 120 fps capped at 60, `veryfast` encoder, 4 threads |
| ⚖️ Balanced | 6–8 GB | motion-compensated | Full 1080p interpolation |
| 🚀 Full Power | 12 GB+ | motion-compensated | 4K ready, max threads |

Change anytime: `vidfix` → **Settings** → RAM. Auto-detection runs on first launch.

---

## 🧠 How detection works / Cara kerja deteksi konten

VidFix samples 5 tiny frames (160×90) and computes:

1. **Unique color ratio** — anime/cartoon use flat cel shading → few colors
2. **Edge density** — game/screen recordings have dense sharp edges (HUD, text)
3. **Noise sigma** (Donoho estimator on the Laplacian) — camera sensors always inject noise; rendered content does not

Then a simple decision tree classifies the clip and adapts sharpening strength & saturation per content type (e.g. anime gets +18% saturation on Vivid, real-life only +12% so skin tones stay natural).

---

## ⚠️ Honest notes / Catatan jujur

- Video processing is **CPU-bound** — a 1-minute clip at 1080p/60fps can take 5–20 minutes depending on your SoC and presets. The app shows a rough time estimate before starting.
- Termux wake-lock is acquired automatically during rendering so Android won't kill the job.
- Interpolation cannot invent detail that isn't there — it smooths motion between existing frames.

---

## 🗺️ Roadmap

- [x] v1.0 — upscaling, color grading, FPS interpolation, content auto-detect, RAM adaptive, bilingual UI
- [ ] v1.1 — Web UI (browser dashboard on localhost)
- [ ] v1.2 — batch queue folder
- [ ] v2.0 — optional AI upscaling (Real-ESRGAN, experimental)

---

## 📄 License

MIT — free to use, modify, and share. See [LICENSE](LICENSE).
