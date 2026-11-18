"""Multitrack Video Builder for SlideCast Studio Desktop.

Builds and renders multimedia projects combining:
- Visual source: PDF presentation (rendered to slide images) OR MP4 video.
- Audio tracks: 1 to 4 independent audio tracks mixed with individual gain,
  mute, start offsets, time alignment, and peak limiting (anti-clipping).
- Deterministic timeline: total duration pinned to visual master.
- Robust execution: cancellable QProcess/Popen, progress reporting,
  temp cleanup, and clean error handling.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple, List

from app.core.ffmpeg_utils import get_ffmpeg_paths
from app.core.multitrack import MultimediaProject, AudioTrack, VideoInfo, inspect_video
from app.core.pdf_processor import render_all_slides_to_dir
from app.core.video_generator import VideoGenerationError

logger = logging.getLogger(__name__)


def build_audio_filter_complex(
    tracks: List[AudioTrack],
    total_duration: float,
    input_offset: int = 1,
) -> Tuple[List[str], str, List[str]]:
    """
    Constructs the FFmpeg input arguments and filter_complex string for mixing
    up to 4 audio tracks.

    :param tracks: List of AudioTrack instances.
    :param total_duration: Master duration of the video in seconds.
    :param input_offset: Starting FFmpeg input index for audio files (e.g. 1 if input 0 is video/concat).
    :return: (extra_ffmpeg_inputs, filter_complex_str, mapped_audio_output)
    """
    if total_duration <= 0:
        total_duration = 1.0

    active_tracks: List[Tuple[int, AudioTrack]] = []
    extra_inputs: List[str] = []

    for i, t in enumerate(tracks):
        p = Path(t.file_path).resolve()
        if p.is_file():
            in_idx = input_offset + len(extra_inputs) // 2
            extra_inputs.extend(["-i", str(p)])
            active_tracks.append((in_idx, t))

    # Case 1: No audio tracks or all tracks muted/volume zero
    audible_tracks = [
        (idx, t) for (idx, t) in active_tracks
        if not t.mute and t.volume > 0.0001
    ]

    if not audible_tracks:
        # Generate silent stereo track matching the exact duration
        silence_input_idx = input_offset + len(extra_inputs) // 2
        extra_inputs.extend([
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        ])
        filter_str = (
            f"[{silence_input_idx}:a]atrim=0:{total_duration:.4f},"
            f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[aout]"
        )
        return extra_inputs, filter_str, ["[aout]"]

    # Case 2: 1 or more tracks
    filter_parts: List[str] = []
    track_labels: List[str] = []

    for out_num, (in_idx, t) in enumerate(active_tracks):
        label = f"t{out_num}"
        chain: List[str] = [
            "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
        ]

        # Delay start if offset > 0
        if t.offset > 0.001:
            delay_ms = int(round(t.offset * 1000))
            chain.append(f"adelay=delays={delay_ms}:all=1")

        # Volume adjustment (0.0 if muted)
        vol = 0.0 if t.mute else round(float(t.volume), 4)
        chain.append(f"volume={vol:.4f}")

        # Trim to master duration and pad so shorter tracks have clean trailing silence
        chain.append(f"atrim=0:{total_duration:.4f}")
        chain.append(f"apad=whole_dur={total_duration:.4f}")

        filter_parts.append(f"[{in_idx}:a]{','.join(chain)}[{label}]")
        track_labels.append(f"[{label}]")

    num_inputs = len(track_labels)
    if num_inputs == 1:
        # Single track: limit peaks slightly and output
        filter_parts.append(f"{track_labels[0]}alimiter=limit=0.99[aout]")
    else:
        # Mix multiple tracks without automatic division (normalize=0) and apply peak limiter
        mix_inputs = "".join(track_labels)
        filter_parts.append(
            f"{mix_inputs}amix=inputs={num_inputs}:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.99[aout]"
        )

    filter_complex = ";".join(filter_parts)
    return extra_inputs, filter_complex, ["[aout]"]


def should_stream_copy_video(
    vinfo: VideoInfo,
    target_res: Tuple[int, int],
    target_fps: int,
) -> bool:
    """
    Determines objectively if an MP4 source can use video stream copy (-c:v copy)
    without visual re-encoding.
    """
    if vinfo.codec_name.lower() not in ("h264", "avc1"):
        return False
    if vinfo.pix_fmt.lower() not in ("yuv420p", "yuvj420p"):
        return False
    t_w, t_h = target_res
    if vinfo.width != t_w or vinfo.height != t_h:
        return False
    if abs(vinfo.fps - target_fps) > 0.75:
        return False
    return True


def generate_multimedia_video(
    project: MultimediaProject,
    output_path: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    dpi: int = 150,
) -> str:
    """
    Renders a MultimediaProject into a final MP4 video.

    :param project: The MultimediaProject containing visual source and audio tracks.
    :param output_path: Destination path; if None, uses project.export_settings['output_path'].
    :param progress_callback: Called with (fraction 0.0 - 1.0, message).
    :param cancel_check: Returns True if cancellation was requested.
    :param dpi: DPI for rendering PDF slides to images.
    :return: Absolute path to the created MP4 file.
    """
    is_valid, validation_errors = project.validate()
    if not is_valid:
        raise ValueError("Projeto inválido:\n" + "\n".join(validation_errors))

    dest_path = output_path or project.export_settings.get("output_path")
    if not dest_path:
        raise ValueError("Caminho de saída do vídeo não especificado.")

    out_file = Path(dest_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_path, _ = get_ffmpeg_paths()
    if not ffmpeg_path:
        raise VideoGenerationError(
            "FFmpeg não foi encontrado no sistema. "
            "Por favor, instale o FFmpeg ou coloque o executável na pasta do aplicativo."
        )

    total_duration = project.calculate_total_duration()
    if total_duration <= 0:
        raise ValueError("A duração total calculada para o vídeo é zero.")

    res_list = project.export_settings.get("resolution", [1920, 1080])
    target_res: Tuple[int, int] = (int(res_list[0]), int(res_list[1]))
    target_fps = int(project.export_settings.get("fps", 30))

    temp_dir = Path(tempfile.mkdtemp(prefix="slidecast_multi_render_"))
    concat_file_path: Optional[str] = None

    try:
        if progress_callback:
            progress_callback(0.02, "Preparando projeto e fontes...")

        cmd: List[str] = [ffmpeg_path, "-y"]

        # Threading option
        try:
            ffmpeg_threads = max(1, int(os.environ.get("FFMPEG_THREADS", "2")))
        except ValueError:
            ffmpeg_threads = 2
        cmd.extend(["-threads", str(ffmpeg_threads)])

        # Video source configuration
        if project.visual_source_type == "pdf":
            # 1. Render slides to images (progress 0% - 25%)
            def slide_progress(cur: int, tot: int):
                if progress_callback and tot > 0:
                    frac = 0.02 + 0.23 * (cur / tot)
                    progress_callback(frac, f"Renderizando slide {cur} de {tot}...")

            images = render_all_slides_to_dir(
                file_path=project.visual_source_path,
                output_dir=temp_dir,
                target_dpi=dpi,
                progress_callback=slide_progress,
                cancel_check=cancel_check,
            )

            if cancel_check and cancel_check():
                raise InterruptedError("Operação cancelada.")

            # Create concat demuxer file
            concat_path = temp_dir / "slides_concat.txt"
            concat_file_path = str(concat_path)
            with open(concat_path, "w", encoding="utf-8") as f_concat:
                for img_path, dur in zip(images, project.slide_durations):
                    posix_path = img_path.resolve().as_posix().replace("'", "'\\''")
                    f_concat.write(f"file '{posix_path}'\n")
                    f_concat.write(f"duration {dur:.4f}\n")
                # Demuxer requires repeating the last file
                last_posix = images[-1].resolve().as_posix().replace("'", "'\\''")
                f_concat.write(f"file '{last_posix}'\n")

            cmd.extend(["-f", "concat", "-safe", "0", "-i", concat_file_path])

            # Audio inputs and filter
            extra_inputs, audio_filter_str, map_audio = build_audio_filter_complex(
                tracks=project.tracks,
                total_duration=total_duration,
                input_offset=1,
            )
            cmd.extend(extra_inputs)

            # Combined filter complex: video scale/pad + audio mix
            w, h = target_res
            video_filter = (
                f"[0:v]fps={target_fps},"
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p[vout]"
            )
            full_filter = f"{video_filter};{audio_filter_str}"

            cmd.extend(["-filter_complex", full_filter])
            cmd.extend(["-map", "[vout]"])
            cmd.extend(["-map", map_audio[0]])
            cmd.extend([
                "-r", str(target_fps),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-t", f"{total_duration:.4f}",
            ])

        elif project.visual_source_type == "video":
            # Video source: input 0 is the MP4 file
            video_path = str(Path(project.visual_source_path).resolve())
            cmd.extend(["-i", video_path])

            vinfo = project.video_info or inspect_video(video_path)

            extra_inputs, audio_filter_str, map_audio = build_audio_filter_complex(
                tracks=project.tracks,
                total_duration=total_duration,
                input_offset=1,
            )
            cmd.extend(extra_inputs)

            can_stream_copy = should_stream_copy_video(vinfo, target_res, target_fps)

            if can_stream_copy:
                # Direct stream copy of the video stream, replacing audio with our mixed audio
                cmd.extend(["-filter_complex", audio_filter_str])
                cmd.extend(["-map", "0:v:0"])  # Explicitly select video only from input 0 (ignoring original audio)
                cmd.extend(["-map", map_audio[0]])
                cmd.extend([
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-t", f"{total_duration:.4f}",
                ])
            else:
                # Re-encode video with target resolution and format
                w, h = target_res
                video_filter = (
                    f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p[vout]"
                )
                full_filter = f"{video_filter};{audio_filter_str}"

                cmd.extend(["-filter_complex", full_filter])
                cmd.extend(["-map", "[vout]"])
                cmd.extend(["-map", map_audio[0]])
                cmd.extend([
                    "-r", str(target_fps),
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "20",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-t", f"{total_duration:.4f}",
                ])

        cmd.extend(["-progress", "pipe:1", str(out_file)])

        # Run cancellable FFmpeg process
        stderr_capture = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")
        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=stderr_capture,
                text=True,
                bufsize=1,
                startupinfo=startupinfo,
            )

            encoded_time = 0.0
            start_progress = 0.25 if project.visual_source_type == "pdf" else 0.05
            progress_range = 1.0 - start_progress

            while True:
                if cancel_check and cancel_check():
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    if out_file.exists():
                        out_file.unlink(missing_ok=True)
                    raise InterruptedError("Geração de vídeo cancelada pelo usuário.")

                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue

                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        us_str = line.split("=")[1]
                        encoded_time = float(us_str) / 1_000_000.0
                        if total_duration > 0 and progress_callback:
                            frac = min(1.0, max(0.0, encoded_time / total_duration))
                            total_frac = start_progress + (progress_range * frac)
                            msg = (
                                f"Renderizando vídeo multimídia: {encoded_time:.1f}s / {total_duration:.1f}s "
                                f"({int(total_frac * 100)}%)"
                            )
                            progress_callback(min(1.0, total_frac), msg)
                    except Exception:
                        pass

            returncode = process.wait()
            if returncode != 0:
                stderr_capture.seek(0)
                stderr_output = stderr_capture.read()
                if out_file.exists():
                    out_file.unlink(missing_ok=True)
                raise VideoGenerationError(
                    f"Erro no FFmpeg (código {returncode}):\n{stderr_output[-600:]}"
                )

            if progress_callback:
                progress_callback(1.0, "Vídeo renderizado com sucesso!")

            return str(out_file)

        finally:
            try:
                stderr_capture.close()
            except Exception:
                pass

    except InterruptedError:
        if out_file.exists():
            out_file.unlink(missing_ok=True)
        raise
    finally:
        # Clean up temporary directory
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
