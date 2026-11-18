# SlideCast Studio — Multimedia Editor Contract

> **Target Audience:** Codex (Visual Redesign, UX/UI, Design Tokens, Themes)  
> **Author:** Muse / Agi (Backend, Media Processing & Core Engine)  
> **Status:** Implemented & Verified in Desktop Engine (`app/core/multitrack.py`, `app/core/multitrack_video_builder.py`, `app/worker.py`, `app/ui/main_window.py`)

---

## 1. Overview & Architectural Boundary

The SlideCast Multimedia Video Creator operates entirely **locally** via Python, PySide6, and FFmpeg. There are no remote HTTP endpoints or cloud uploads required for video creation.

- **Codex owns:** The UI layout, design system tokens, themes, widget styling, drag-and-drop feedback, timeline visualization, and user experience.
- **Muse owns:** Data models (`MultimediaProject`, `AudioTrack`, `VideoInfo`), media probing, validation, FFmpeg mixdown engine, background rendering thread (`MultimediaRenderWorker`), progress calculation, cancellation, project persistence (`.slidecast`), and tests.

---

## 2. State Machine & Observable Events

The editor operates with the following explicit states:

```
[idle] ──(select source / add tracks)──> [ready] ──(start render)──> [rendering]
  │                                        │                              │
  ├───(validation error)───> [validating] ─┘                              ├───(cancel)───> [cancelled]
  │                                                                       ├───(error)────> [failed]
  └───────────────────────────────────────────────────────────────────────┴───(success)──> [completed]
```

### 2.1 State Definitions

| State | Condition / Meaning | UI Behavior |
|---|---|---|
| `idle` | No visual source selected yet or project cleared. | "Gerar Vídeo" disabled. Drop areas waiting for input. |
| `validating` | Probing media file with ffprobe / inspecting PDF pages. | Brief spinner or loading state on the affected drop zone. |
| `ready` | Visual source loaded, duration > 0, destination path set. Warnings may be present. | "Gerar Vídeo" enabled. Duration badges green/neutral. |
| `rendering` | Background FFmpeg process running via `MultimediaRenderWorker`. | Progress bar active (0%–100%), status text updating, "Gerar Vídeo" replaced by "Cancelar". |
| `completed` | Video finished and verified on disk. | Success dialog, action buttons ("Assistir Vídeo", "Abrir Pasta"). |
| `failed` | Error during rendering or FFmpeg exited with non-zero code. Incomplete MP4 unlinked. | Error modal with sanitized diagnostics, controls re-enabled. |
| `cancelled` | User clicked Cancel during render. Process terminated, temp files deleted, no file left. | Cancellation notice, controls re-enabled for adjustments. |

---

## 3. Data Shapes & Types

### 3.1 `AudioTrack`

Represents one of up to **4 independent audio tracks**.

```python
@dataclass
class AudioTrack:
    id: str                   # Unique identifier (e.g. "a1b2c3d4")
    name: str                 # Display name (e.g. "Narração", "Música de Fundo")
    file_path: str            # Absolute path to audio file on disk
    duration: float           # Duration in seconds (ffprobe/mutagen verified)
    sample_rate: Optional[int]# Sample rate in Hz (e.g. 44100, 48000)
    channels: Optional[int]   # Channel count (1 = mono, 2 = stereo)
    file_size_bytes: int      # Size on disk
    volume: float = 1.0       # Gain: 0.0 to 2.0 (1.0 = 100%)
    mute: bool = False        # Mute toggle (True = volume 0 in mixdown)
    offset: float = 0.0       # Start offset in seconds on video timeline (>= 0.0)
    fade_in: float = 0.0      # Optional fade-in seconds (extension hook)
    fade_out: float = 0.0     # Optional fade-out seconds (extension hook)
    loop: bool = False        # Optional loop setting (extension hook)
```

### 3.2 `VideoInfo`

Metadata for an imported video file (used when visual source is MP4).

```python
@dataclass
class VideoInfo:
    file_path: str            # Absolute path
    duration: float           # Total duration in seconds
    width: int                # e.g. 1920
    height: int               # e.g. 1080
    fps: float                # e.g. 30.0, 24.0, 60.0
    codec_name: str           # e.g. "h264", "hevc"
    pix_fmt: str              # e.g. "yuv420p"
    has_audio: bool           # True if the original video contains an audio stream
    audio_codec: Optional[str]# e.g. "aac"
    file_size_bytes: int
```

### 3.3 `MultimediaProject`

Root state object for saving, loading, and passing to the renderer.

```python
@dataclass
class MultimediaProject:
    schema_version: int = 2
    title: str = "Projeto SlideCast"
    visual_source_type: str = "pdf"       # "pdf" | "video"
    visual_source_path: Optional[str] = None
    slide_durations: List[float] = field(default_factory=list) # Only if visual_source_type == "pdf"
    video_info: Optional[VideoInfo] = None                    # Only if visual_source_type == "video"
    ignore_original_audio: bool = True    # MANDATORY DEFAULT: ignores MP4 original audio
    tracks: List[AudioTrack] = field(default_factory=list)    # Max 4 tracks
    export_settings: Dict[str, Any] = field(default_factory=lambda: {
        "resolution": [1920, 1080],
        "fps": 30,
        "output_path": ""
    })
```

---

## 4. Public API Methods (Core Engine & Worker)

All methods follow Python standard naming conventions (`snake_case`) with strict typing.

### 4.1 Project & Source Operations

```python
from app.core.multitrack import (
    MultimediaProject,
    AudioTrack,
    VideoInfo,
    inspect_video,
    probe_audio_track,
    MAX_AUDIO_TRACKS,
)

# 1. Create a project
project = MultimediaProject(title="Minha Apresentação")

# 2. Set visual source to PDF
project.set_visual_source("pdf", "/path/to/slides.pdf", slide_durations=[5.0, 7.5, 10.0])

# 3. Set visual source to Video MP4
project.set_visual_source("video", "/path/to/orig.mp4")

# 4. Probe and add an audio track (up to 4)
track = probe_audio_track("/path/to/voice.mp3", name="Narração")
project.add_track(track)

# 5. Modify track volume, offset or mute
track.volume = 0.8       # 80%
track.offset = 2.5       # Starts 2.5 seconds into the video
track.mute = False

# 6. Reorder or remove tracks
project.move_track(from_index=0, to_index=1)
project.remove_track(track.id)

# 7. Calculate master duration
total_sec = project.calculate_total_duration()

# 8. Validate project before rendering
is_valid, messages = project.validate()
# is_valid: bool
# messages: List[str] of blocking errors or human warnings

# 9. Persistence
project.save_to_file("/path/to/project.slidecast")
loaded_project = MultimediaProject.load_from_file("/path/to/project.slidecast")
```

### 4.2 Background Worker Execution

The rendering runs in `MultimediaRenderWorker` (`QThread`), avoiding any UI freeze.

```python
from app.worker import MultimediaRenderWorker

worker = MultimediaRenderWorker(
    project=project,
    output_path="/path/to/output.mp4",
    dpi=150,      # Only used for PDF rasterization
    parent=self,
)

# Connect signals
worker.progress_changed.connect(lambda frac, msg: update_progress_bar(frac, msg))
worker.render_finished.connect(lambda out_path: on_success(out_path))
worker.render_error.connect(lambda err_msg: on_error(err_msg))
worker.render_cancelled.connect(lambda: on_cancelled())

# Start render
worker.start()

# Cancel render
worker.cancel()
```

---

## 5. UI Integration Rules for Codex

1. **Visual Source Toggle:**
   - Present a mutually exclusive toggle between `Apresentação de Slides (PDF)` and `Vídeo de Origem (MP4)`.
   - When PDF is selected, expose the slide timing controls (equal distribution, custom spinboxes, balance to audio).
   - When Video is selected, hide the slide thumbnails and display the master video duration and metadata badge.
2. **Audio Tracks Strip (Max 4):**
   - Provide an "+ Adicionar Faixa de Áudio" button. Disable it when `len(project.tracks) == 4`.
   - For each track row, include:
     - Drag handle or track index (`#1`, `#2`, `#3`, `#4`).
     - Track name input (defaulting to "Narração", "Música de Fundo", "Efeitos", "Áudio Complementar").
     - Audio file name and duration badge.
     - Volume slider / spinbox (0% to 200%, default 100%).
     - Mute toggle button.
     - Start Offset spinbox (seconds, 0.0s to video duration, step 0.5s).
     - Remove track button (`✕`).
3. **Audio of Source Video:**
   - When an MP4 file is loaded that contains audio, display a clear indicator:  
     `"Áudio original do vídeo: detectado (ignorado por padrão)"`.  
     *Engine rule:* Original video audio is never mixed in unless a specific future toggle is implemented.
4. **All Tracks Muted (Corner Case):**
   - If all audio tracks are muted or volume is set to 0%, the engine renders a silent video (`anullsrc` AAC stream matching video duration). Show a warning note: `"Aviso: Todas as faixas estão mutadas. O vídeo final será exportado sem som."`
5. **Project Persistence:**
   - Buttons to "Salvar Projeto (.slidecast)" and "Abrir Projeto" can be styled prominently in the header or toolbar.

---

## 6. Concrete JSON Schemas & Examples

### Example 1: PDF + 4 Audio Tracks

```json
{
  "schema_version": 2,
  "title": "Aula de História - Cap 3",
  "visual_source_type": "pdf",
  "visual_source_path": "/home/user/documentos/aula3.pdf",
  "slide_durations": [10.0, 15.5, 20.0, 12.0],
  "video_info": null,
  "ignore_original_audio": true,
  "tracks": [
    {
      "id": "t1-narr",
      "name": "Narração Principal",
      "file_path": "/home/user/audio/voz_professora.mp3",
      "duration": 57.5,
      "sample_rate": 44100,
      "channels": 2,
      "file_size_bytes": 1845200,
      "volume": 1.0,
      "mute": false,
      "offset": 0.0,
      "fade_in": 0.0,
      "fade_out": 0.0,
      "loop": false
    },
    {
      "id": "t2-bgm",
      "name": "Música de Fundo",
      "file_path": "/home/user/musica/trilha_suave.wav",
      "duration": 65.0,
      "sample_rate": 48000,
      "channels": 2,
      "file_size_bytes": 11468800,
      "volume": 0.25,
      "mute": false,
      "offset": 0.0,
      "fade_in": 2.0,
      "fade_out": 3.0,
      "loop": false
    },
    {
      "id": "t3-sfx",
      "name": "Efeito de Transição",
      "file_path": "/home/user/efeitos/whoosh.ogg",
      "duration": 1.5,
      "sample_rate": 44100,
      "channels": 1,
      "file_size_bytes": 48200,
      "volume": 0.7,
      "mute": false,
      "offset": 10.0,
      "fade_in": 0.0,
      "fade_out": 0.0,
      "loop": false
    },
    {
      "id": "t4-extra",
      "name": "Citação em Áudio",
      "file_path": "/home/user/audio/citacao_historica.m4a",
      "duration": 8.0,
      "sample_rate": 44100,
      "channels": 2,
      "file_size_bytes": 128400,
      "volume": 0.9,
      "mute": false,
      "offset": 25.5,
      "fade_in": 0.0,
      "fade_out": 0.0,
      "loop": false
    }
  ],
  "export_settings": {
    "resolution": [1920, 1080],
    "fps": 30,
    "output_path": "/home/user/videos/aula3_final.mp4"
  }
}
```

### Example 2: MP4 Source Video + 2 Audio Tracks

```json
{
  "schema_version": 2,
  "title": "Demonstração de Software com Locução",
  "visual_source_type": "video",
  "visual_source_path": "/home/user/videos/captura_tela_muda.mp4",
  "slide_durations": [],
  "video_info": {
    "file_path": "/home/user/videos/captura_tela_muda.mp4",
    "duration": 42.5,
    "width": 1920,
    "height": 1080,
    "fps": 30.0,
    "codec_name": "h264",
    "pix_fmt": "yuv420p",
    "has_audio": false,
    "audio_codec": null,
    "file_size_bytes": 14205800
  },
  "ignore_original_audio": true,
  "tracks": [
    {
      "id": "tr-voz",
      "name": "Locução Explicativa",
      "file_path": "/home/user/gravacoes/locucao.wav",
      "duration": 40.0,
      "sample_rate": 44100,
      "channels": 1,
      "file_size_bytes": 3528000,
      "volume": 1.0,
      "mute": false,
      "offset": 1.0,
      "fade_in": 0.0,
      "fade_out": 0.0,
      "loop": false
    },
    {
      "id": "tr-intro",
      "name": "Vinheta de Abertura",
      "file_path": "/home/user/musica/intro.flac",
      "duration": 4.0,
      "sample_rate": 48000,
      "channels": 2,
      "file_size_bytes": 950000,
      "volume": 0.6,
      "mute": false,
      "offset": 0.0,
      "fade_in": 0.0,
      "fade_out": 1.0,
      "loop": false
    }
  ],
  "export_settings": {
    "resolution": [1920, 1080],
    "fps": 30,
    "output_path": "/home/user/videos/demo_final.mp4"
  }
}
```

---

## 7. Status: Implementado vs. Planejado

| Funcionalidade | Status | Detalhes |
|---|---|---|
| **Fonte visual PDF** | **Implementado & Testado** | Renderiza slides via PyMuPDF e concatena com tempos. |
| **Fonte visual MP4** | **Implementado & Testado** | Inspeciona com ffprobe; suporta stream copy ou re-encode. |
| **Ignorar áudio original do MP4** | **Implementado & Testado** | Padrão obrigatório no pipeline de renderização (`-map 0:v:0`). |
| **Até 4 faixas de áudio independentes** | **Implementado & Testado** | Probing, ganho (`volume`), `mute`, e `offset` temporal. |
| **Mixagem sem distorção / anti-clipping** | **Implementado & Testado** | `amix=...:normalize=0` + `alimiter=limit=0.99`. |
| **Tratamento de áudio mudo** | **Implementado & Testado** | Gera faixa estéreo AAC silenciosa sem corromper container. |
| **Persistência `.slidecast` (JSON v2)** | **Implementado & Testado** | Salvar e carregar com retrocompatibilidade para v1. |
| **Cancelamento robusto** | **Implementado & Testado** | Encerra processo FFmpeg, apaga temporários e remove arquivo parcial. |
| **Formatos decodificáveis** | **Implementado & Testado** | MP3, WAV, M4A, AAC, OGG, FLAC, WebM verificados. |
| **Fade in/out configurável na UI** | *Planejado (P2)* | Parâmetros no modelo prontos; filtros FFmpeg preparados. |
| **Automação de volume (envelope)** | *Planejado (P2)* | Não bloqueia entrega P0. |
