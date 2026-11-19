from app.core.ffmpeg_utils import get_ffmpeg_paths, format_duration, get_video_duration
from app.core.pdf_processor import inspect_pdf, render_thumbnail, render_all_slides_to_dir
from app.core.audio_processor import get_audio_info
from app.core.video_generator import generate_video
from app.core.multitrack import (
    AudioTrack,
    VideoInfo,
    MultimediaProject,
    inspect_video,
    probe_audio_track,
    MAX_AUDIO_TRACKS,
    SUPPORTED_AUDIO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
)
from app.core.multitrack_video_builder import (
    generate_multimedia_video,
    build_audio_filter_complex,
)
from app.core.dual_region_recorder import (
    ScreenRegion,
    CompositionConfig,
    DualRegionSession,
    DualRegionRecordingProcess,
    compose_dual_region_video,
    PresentationInterval,
    format_ms_to_time,
    parse_time_to_ms,
    normalize_and_validate_intervals,
    detect_slide_intervals_heuristic,
    probe_video_dimensions,
)

__all__ = [
    "get_ffmpeg_paths",
    "format_duration",
    "get_video_duration",
    "inspect_pdf",
    "render_thumbnail",
    "render_all_slides_to_dir",
    "get_audio_info",
    "generate_video",
    "AudioTrack",
    "VideoInfo",
    "MultimediaProject",
    "inspect_video",
    "probe_audio_track",
    "MAX_AUDIO_TRACKS",
    "SUPPORTED_AUDIO_EXTENSIONS",
    "SUPPORTED_VIDEO_EXTENSIONS",
    "generate_multimedia_video",
    "build_audio_filter_complex",
    "ScreenRegion",
    "CompositionConfig",
    "DualRegionSession",
    "DualRegionRecordingProcess",
    "compose_dual_region_video",
    "PresentationInterval",
    "format_ms_to_time",
    "parse_time_to_ms",
    "normalize_and_validate_intervals",
    "detect_slide_intervals_heuristic",
    "probe_video_dimensions",
]
