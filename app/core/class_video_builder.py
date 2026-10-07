import os
import subprocess
import tempfile
import sys
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Callable
import pymupdf

from app.core.ffmpeg_utils import get_ffmpeg_paths


class ClassVideoBuilderError(Exception):
    pass


def render_intro_card_image(
    output_png_path: Path,
    title: str,
    teacher: str,
    cover_image_path: Optional[str] = None,
    resolution: Tuple[int, int] = (1920, 1080),
) -> Path:
    """
    Renders a high-resolution stylized intro title card with cover image background,
    elegant dark overlay, class title, and teacher name.
    Supports both horizontal (16:9 - 1920x1080) and vertical (9:16 - 1080x1920) layouts.
    """
    w, h = resolution
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)

    clean_title = title.strip() or "Aula Especial"
    clean_teacher = teacher.strip() or "Professor(a)"

    # 1. Background (Cover image or dark modern backdrop)
    if cover_image_path and Path(cover_image_path).is_file():
        try:
            page.insert_image(pymupdf.Rect(0, 0, w, h), filename=cover_image_path)
            # Semi-transparent dark overlay card for readability
            if h > w:  # Vertical 9:16
                page.draw_rect(
                    pymupdf.Rect(0, 0, w, h),
                    color=(0.04, 0.06, 0.10),
                    fill=(0.04, 0.06, 0.10),
                )
            else:  # Horizontal 16:9
                overlay_h = h * 0.44
                page.draw_rect(
                    pymupdf.Rect(0, h - overlay_h, w, h),
                    color=(0.04, 0.06, 0.10),
                    fill=(0.04, 0.06, 0.10),
                )
        except Exception:
            page.draw_rect(pymupdf.Rect(0, 0, w, h), color=(0.06, 0.08, 0.14), fill=(0.06, 0.08, 0.14))
    else:
        page.draw_rect(pymupdf.Rect(0, 0, w, h), color=(0.06, 0.08, 0.14), fill=(0.06, 0.08, 0.14))

    if h > w:  # Vertical layout (Shorts / Reels: 1080x1920)
        # Center card (Safe zone between y=400 and y=1500)
        card_y = 650
        page.draw_rect(
            pymupdf.Rect(60, card_y, w - 60, card_y + 600),
            color=(0.10, 0.14, 0.24),
            fill=(0.10, 0.14, 0.24),
        )
        # Accent bar
        page.draw_rect(
            pymupdf.Rect(60, card_y, w - 60, card_y + 12),
            color=(0.38, 0.40, 0.95),
            fill=(0.38, 0.40, 0.95),
        )
        # Tag
        page.insert_text(
            (110, card_y + 80),
            "V I D E O A U L A",
            fontsize=26,
            color=(0.38, 0.74, 0.98),
        )
        # Title (allow up to 2 lines or truncated)
        if len(clean_title) > 42:
            clean_title = clean_title[:39] + "..."
        page.insert_text(
            (110, card_y + 200),
            clean_title,
            fontsize=54,
            color=(1, 1, 1),
        )
        # Teacher
        page.insert_text(
            (110, card_y + 340),
            f"Prof(a). {clean_teacher}",
            fontsize=38,
            color=(0.65, 0.80, 1.0),
        )
    else:  # Horizontal layout (YouTube: 1920x1080)
        start_y = h * 0.64 if cover_image_path else h * 0.40
        page.draw_rect(
            pymupdf.Rect(100, start_y, 112, start_y + 160),
            color=(0.38, 0.40, 0.95),
            fill=(0.38, 0.40, 0.95),
        )
        if len(clean_title) > 52:
            clean_title = clean_title[:49] + "..."
        page.insert_text(
            (140, start_y + 55),
            clean_title,
            fontsize=52,
            color=(1, 1, 1),
        )
        page.insert_text(
            (142, start_y + 125),
            f"Apresentado por: {clean_teacher}",
            fontsize=32,
            color=(0.65, 0.80, 1.0),
        )

    pix = page.get_pixmap(dpi=72)
    pix.save(str(output_png_path))
    doc.close()
    return output_png_path


def render_outro_card_image(
    output_png_path: Path,
    title: str,
    teacher: str,
    cover_image_path: Optional[str] = None,
    resolution: Tuple[int, int] = (1920, 1080),
) -> Path:
    """
    Renders a high-resolution stylized outro / end card image.
    Supports both horizontal (16:9 - 1920x1080) and vertical (9:16 - 1080x1920).
    """
    w, h = resolution
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)

    clean_title = title.strip() or "Aula Especial"
    clean_teacher = teacher.strip() or "Professor(a)"

    # Dark stylish background
    page.draw_rect(pymupdf.Rect(0, 0, w, h), color=(0.05, 0.07, 0.12), fill=(0.05, 0.07, 0.12))

    if h > w:  # Vertical layout (Shorts / Reels: 1080x1920)
        card_y = 650
        page.draw_rect(
            pymupdf.Rect(60, card_y, w - 60, card_y + 620),
            color=(0.09, 0.13, 0.22),
            fill=(0.09, 0.13, 0.22),
        )
        page.draw_rect(
            pymupdf.Rect(60, card_y, w - 60, card_y + 12),
            color=(0.16, 0.73, 0.58),
            fill=(0.16, 0.73, 0.58),
        )
        page.insert_text(
            (110, card_y + 110),
            "OBRIGADO POR ASSISTIR!",
            fontsize=48,
            color=(1, 1, 1),
        )
        page.insert_text(
            (110, card_y + 220),
            "Gostou da aula? Curta e compartilhe!",
            fontsize=32,
            color=(0.38, 0.74, 0.98),
        )
        page.insert_text(
            (110, card_y + 310),
            "Inscreva-se no canal para não perder as próximas aulas.",
            fontsize=26,
            color=(0.80, 0.85, 0.95),
        )
        page.insert_text(
            (110, card_y + 450),
            f"Prof(a). {clean_teacher} • {clean_title[:32]}",
            fontsize=28,
            color=(0.55, 0.65, 0.80),
        )
    else:  # Horizontal layout (YouTube: 1920x1080)
        card_y = 300
        page.draw_rect(
            pymupdf.Rect(180, card_y, w - 180, card_y + 480),
            color=(0.09, 0.13, 0.22),
            fill=(0.09, 0.13, 0.22),
        )
        page.draw_rect(
            pymupdf.Rect(180, card_y, w - 180, card_y + 10),
            color=(0.16, 0.73, 0.58),
            fill=(0.16, 0.73, 0.58),
        )
        page.insert_text(
            (260, card_y + 110),
            "OBRIGADO POR ASSISTIR!",
            fontsize=56,
            color=(1, 1, 1),
        )
        page.insert_text(
            (260, card_y + 200),
            "Deixe seu Like, inscreva-se no canal e ative o sininho! 🔔",
            fontsize=34,
            color=(0.38, 0.74, 0.98),
        )
        page.insert_text(
            (260, card_y + 280),
            "Dúvidas ou sugestões? Deixe seu comentário logo abaixo.",
            fontsize=28,
            color=(0.80, 0.85, 0.95),
        )
        page.insert_text(
            (260, card_y + 390),
            f"Ministrado por: {clean_teacher}  |  {clean_title}",
            fontsize=26,
            color=(0.55, 0.65, 0.80),
        )

    pix = page.get_pixmap(dpi=72)
    pix.save(str(output_png_path))
    doc.close()
    return output_png_path


def normalize_video_clip(
    input_video: str,
    output_video: str,
    target_res: Tuple[int, int],
    fps: int = 30,
) -> str:
    """
    Transcodes any external video clip to target resolution, fps, yuv420p,
    and 48kHz stereo AAC (adding silent audio if video has no sound)
    so that FFmpeg concat demuxer can merge it cleanly without re-encoding.
    """
    ffmpeg_path, _ = get_ffmpeg_paths()
    w, h = target_res

    # Check if input video has an audio stream
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(Path(input_video).resolve()),
    ]
    has_audio = False
    try:
        res = subprocess.run(probe_cmd, capture_output=True, text=True)
        has_audio = bool(res.stdout.strip())
    except Exception:
        has_audio = False

    cmd = [ffmpeg_path, "-y", "-i", str(Path(input_video).resolve())]

    if not has_audio:
        # Generate silent audio track
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
        cmd.extend([
            "-filter_complex",
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p[v]",
            "-map", "[v]",
            "-map", "1:a",
            "-shortest",
        ])
    else:
        cmd.extend([
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p",
            "-map", "0:v:0",
            "-map", "0:a:0",
        ])

    cmd.extend([
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "192k",
        str(output_video),
    ])

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_video


def build_class_video(
    slide_images: List[Path],
    durations: List[float],
    narration_audio_path: str,
    output_path: str,
    class_title: str = "",
    teacher_name: str = "",
    cover_image_path: Optional[str] = None,
    bgm_path: Optional[str] = None,
    subtitles_srt_path: Optional[str] = None,
    avatar_video_path: Optional[str] = None,
    custom_bg_path: Optional[str] = None,
    video_format: str = "youtube",
    vertical_layout: str = "presenter",
    intro_mode: str = "auto",
    intro_video_path: Optional[str] = None,
    outro_mode: str = "auto",
    outro_video_path: Optional[str] = None,
    intro_duration: float = 3.5,
    outro_duration: float = 3.5,
    fps: int = 30,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Assembles the final video combining:
    - Target Format: 'youtube' (16:9 - 1920x1080), 'shorts' (9:16 - 1080x1920), 'reels' (9:16 - 1080x1920)
    - Vertical Layout: 'presenter' (focus on presenter without slides + big subtitles) or 'split_slides' (slide top + presenter bottom)
    - Intro: 'auto' (title card), 'custom' (external video clip), or 'none'
    - Outro: 'auto' (end card), 'custom' (external video clip), or 'none'
    - High-res slides with exact presentation durations
    - Teacher microphone narration or AI clone voice
    - Digital Avatar / Live Webcam PIP box overlay
    - Custom video background image (AI-generated or user uploaded)
    - Optional background music with auto-ducking volume
    - Optional burned-in subtitles (.srt)
    """
    ffmpeg_path, _ = get_ffmpeg_paths()
    if not ffmpeg_path:
        raise ClassVideoBuilderError("FFmpeg não encontrado.")

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    is_vertical = video_format in ("shorts", "reels")
    resolution: Tuple[int, int] = (1080, 1920) if is_vertical else (1920, 1080)
    w, h = resolution

    temp_dir = Path(tempfile.mkdtemp(prefix="class_build_"))
    try:
        final_images = list(slide_images)
        final_durations = list(durations)

        # 1. Intro Card (Auto mode)
        has_auto_intro = (intro_mode == "auto") and bool(cover_image_path or class_title)
        if has_auto_intro:
            intro_img = temp_dir / "intro_card.png"
            render_intro_card_image(
                output_png_path=intro_img,
                title=class_title,
                teacher=teacher_name,
                cover_image_path=cover_image_path,
                resolution=resolution,
            )
            final_images.insert(0, intro_img)
            final_durations.insert(0, intro_duration)

        # 2. Outro Card (Auto mode)
        has_auto_outro = (outro_mode == "auto")
        if has_auto_outro:
            outro_img = temp_dir / "outro_card.png"
            render_outro_card_image(
                output_png_path=outro_img,
                title=class_title,
                teacher=teacher_name,
                cover_image_path=cover_image_path,
                resolution=resolution,
            )
            final_images.append(outro_img)
            final_durations.append(outro_duration)

        # Concat demuxer for slides
        concat_txt = temp_dir / "concat.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for img, dur in zip(final_images, final_durations):
                posix = img.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{posix}'\n")
                f.write(f"duration {dur:.4f}\n")
            last_posix = final_images[-1].resolve().as_posix().replace("'", "'\\''")
            f.write(f"file '{last_posix}'\n")

        # Determine intermediate output path
        has_custom_clips = (
            (intro_mode == "custom" and intro_video_path and Path(intro_video_path).is_file())
            or (outro_mode == "custom" and outro_video_path and Path(outro_video_path).is_file())
        )
        main_lesson_target = str(temp_dir / "main_lesson.mp4") if has_custom_clips else str(out_file)

        # Build FFmpeg command inputs
        cmd = [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]

        # Input 1: Narration audio
        cmd.extend(["-i", str(Path(narration_audio_path).resolve())])

        # Track dynamically assigned input indices
        curr_in_idx = 2

        # Input (Optional): BGM
        has_bgm = bool(bgm_path and Path(bgm_path).is_file())
        bgm_idx = None
        if has_bgm:
            bgm_idx = curr_in_idx
            cmd.extend(["-stream_loop", "-1", "-i", str(Path(bgm_path).resolve())])
            curr_in_idx += 1

        # Input (Optional): Digital Avatar / Presenter Video
        has_avatar = bool(avatar_video_path and Path(avatar_video_path).is_file())
        avatar_idx = None
        if has_avatar:
            avatar_idx = curr_in_idx
            cmd.extend(["-stream_loop", "-1", "-i", str(Path(avatar_video_path).resolve())])
            curr_in_idx += 1

        # Input (Optional): Custom Background Image
        has_custom_bg = bool(custom_bg_path and Path(custom_bg_path).is_file())
        bg_idx = None
        if has_custom_bg:
            bg_idx = curr_in_idx
            cmd.extend(["-loop", "1", "-i", str(Path(custom_bg_path).resolve())])
            curr_in_idx += 1

        narration_delay_ms = int(intro_duration * 1000) if has_auto_intro else 0
        total_expected_sec = sum(final_durations)

        # Build filter_complex parts
        fc_parts = []

        if is_vertical:
            if vertical_layout == "presenter" and has_avatar and avatar_idx is not None:
                # Vertical layout: Presenter Spotlight (No slides, presenter prominent in center)
                delay_sec = intro_duration if has_auto_intro else 0.0
                main_active_end = total_expected_sec - (outro_duration if has_auto_outro else 0.0)

                # Base background: Custom image if provided, otherwise ambient blurred avatar
                if has_custom_bg and bg_idx is not None:
                    fc_parts.append(
                        f"[{bg_idx}:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                        f"format=yuv420p[cust_bg_raw];"
                        f"[cust_bg_raw]drawbox=0:0:{w}:{h}:color=black@0.22:t=fill[av_bg]"
                    )
                    fc_parts.append(f"[{avatar_idx}:v]null[av_fg_in]")
                else:
                    fc_parts.append(f"[{avatar_idx}:v]split=2[av_bg_in][av_fg_in]")
                    if delay_sec > 0:
                        fc_parts.append(
                            f"[av_bg_in]fps={fps},scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                            f"boxblur=5:5,scale={w}:{h},format=yuv420p,setpts=PTS-STARTPTS+{delay_sec}/TB[av_bg_raw];"
                            f"[av_bg_raw]drawbox=0:0:{w}:{h}:color=black@0.45:t=fill[av_bg]"
                        )
                    else:
                        fc_parts.append(
                            f"[av_bg_in]fps={fps},scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                            f"boxblur=5:5,scale={w}:{h},format=yuv420p[av_bg_raw];"
                            f"[av_bg_raw]drawbox=0:0:{w}:{h}:color=black@0.45:t=fill[av_bg]"
                        )

                # 2. Intro / Outro card overlay if auto cards enabled
                if has_auto_intro or has_auto_outro:
                    enable_cond = []
                    if has_auto_intro:
                        enable_cond.append(f"lte(t,{delay_sec})")
                    if has_auto_outro:
                        enable_cond.append(f"gte(t,{main_active_end})")
                    cond_str = "+".join(enable_cond)

                    fc_parts.append(
                        f"[0:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
                        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p[card_overlay];"
                        f"[av_bg][card_overlay]overlay=0:0:enable='{cond_str}':repeatlast=0[base_v]"
                    )
                else:
                    fc_parts.append(f"[av_bg]null[base_v]")

                # 3. Presenter overlay in center (1040x584 at x=20, y=520)
                pres_y = 500 if video_format == "shorts" else 530
                if delay_sec > 0:
                    fc_parts.append(
                        f"[av_fg_in]scale=1040:584:force_original_aspect_ratio=decrease,"
                        f"pad=1040:584:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"drawbox=0:0:1040:584:color=white@0.8:t=3,setpts=PTS-STARTPTS+{delay_sec}/TB[pres_fg];"
                        f"[base_v][pres_fg]overlay=20:{pres_y}:enable='between(t,{delay_sec},{main_active_end})':repeatlast=0[curr_pres_v]"
                    )
                else:
                    fc_parts.append(
                        f"[av_fg_in]scale=1040:584:force_original_aspect_ratio=decrease,"
                        f"pad=1040:584:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"drawbox=0:0:1040:584:color=white@0.8:t=3[pres_fg];"
                        f"[base_v][pres_fg]overlay=20:{pres_y}:enable='lte(t,{main_active_end})':repeatlast=0[curr_pres_v]"
                    )

                curr_v = "curr_pres_v"

                # 4. Subtitles in presenter_only mode: Prominent, centered below the presenter
                if subtitles_srt_path and Path(subtitles_srt_path).is_file():
                    srt_escaped = Path(subtitles_srt_path).resolve().as_posix().replace("'", "'\\''").replace(":", "\\:")
                    margin_v = 380 if video_format == "shorts" else 420
                    style = (
                        f"Fontname=Arial,Fontsize=26,PrimaryColour=&H00FFFFFF,"
                        f"OutlineColour=&H00000000,BackColour=&H80000000,Bold=1,MarginV={margin_v}"
                    )
                    fc_parts.append(f"[{curr_v}]subtitles='{srt_escaped}':force_style='{style}'[vout]")
                else:
                    fc_parts.append(f"[{curr_v}]null[vout]")

            else:
                # Vertical layout: Split Slides (Slide top + Presenter bottom)
                # Base: Custom background image if provided, otherwise blurred slide
                if has_custom_bg and bg_idx is not None:
                    fc_parts.append(
                        f"[{bg_idx}:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                        f"format=yuv420p[cust_bg_raw];"
                        f"[cust_bg_raw]drawbox=0:0:{w}:{h}:color=black@0.25:t=fill[base_bg]"
                    )
                    fc_parts.append(f"[0:v]null[slide_fg_in]")
                else:
                    fc_parts.append(f"[0:v]split=2[slide_bg_in][slide_fg_in]")
                    fc_parts.append(
                        f"[slide_bg_in]fps={fps},scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=5:5,scale={w}:{h},format=yuv420p[blurred_bg];"
                        f"[blurred_bg]drawbox=0:0:{w}:{h}:color=black@0.45:t=fill[base_bg]"
                    )

                # Slide overlay in upper section (or centered if no avatar)
                if not has_avatar:
                    slide_y = (h - 584) // 2
                    fc_parts.append(
                        f"[slide_fg_in]fps={fps},scale=1040:584:force_original_aspect_ratio=decrease,pad=1040:584:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"drawbox=0:0:1040:584:color=white@0.6:t=2[slide_v];"
                        f"[base_bg][slide_v]overlay=20:{slide_y}[base_v]"
                    )
                elif video_format == "shorts":
                    # Shorts: Slide centered at y=280 (1040 width)
                    fc_parts.append(
                        f"[slide_fg_in]fps={fps},scale=1040:584:force_original_aspect_ratio=decrease,pad=1040:584:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"drawbox=0:0:1040:584:color=white@0.6:t=2[slide_v];"
                        f"[base_bg][slide_v]overlay=20:280[base_v]"
                    )
                else:
                    # Reels: Centered within 4:5 safe zone (y=340, 1000 width)
                    fc_parts.append(
                        f"[slide_fg_in]fps={fps},scale=1000:562:force_original_aspect_ratio=decrease,pad=1000:562:(ow-iw)/2:(oh-ih)/2:color=black,"
                        f"drawbox=0:0:1000:562:color=white@0.6:t=2[slide_v];"
                        f"[base_bg][slide_v]overlay=40:340[base_v]"
                    )

                curr_v = "base_v"

                # Avatar overlay in lower section
                if has_avatar and avatar_idx is not None:
                    delay_sec = intro_duration if has_auto_intro else 0.0
                    main_active_end = total_expected_sec - (outro_duration if has_auto_outro else 0.0)

                    # Avatar dimensions: 500x280, placed in center below slide
                    av_y = 900 if video_format == "shorts" else 940
                    if delay_sec > 0:
                        fc_parts.append(
                            f"[{avatar_idx}:v]scale=500:280,drawbox=0:0:500:280:color=white@0.8:t=3,setpts=PTS-STARTPTS+{delay_sec}/TB[pip];"
                            f"[{curr_v}][pip]overlay=290:{av_y}:enable='between(t,{delay_sec},{main_active_end})':repeatlast=0[v_pip]"
                        )
                    else:
                        fc_parts.append(
                            f"[{avatar_idx}:v]scale=500:280,drawbox=0:0:500:280:color=white@0.8:t=3[pip];"
                            f"[{curr_v}][pip]overlay=290:{av_y}:enable='lte(t,{main_active_end})':repeatlast=0[v_pip]"
                        )
                    curr_v = "v_pip"

                # Subtitles: position above YouTube Shorts / Reels bottom UI
                if subtitles_srt_path and Path(subtitles_srt_path).is_file():
                    srt_escaped = Path(subtitles_srt_path).resolve().as_posix().replace("'", "'\\''").replace(":", "\\:")
                    margin_v = 270 if video_format == "shorts" else 310
                    style = (
                        f"Fontname=Arial,Fontsize=22,PrimaryColour=&H00FFFFFF,"
                        f"OutlineColour=&H00000000,BackColour=&H80000000,Bold=1,MarginV={margin_v}"
                    )
                    fc_parts.append(f"[{curr_v}]subtitles='{srt_escaped}':force_style='{style}'[vout]")
                else:
                    fc_parts.append(f"[{curr_v}]null[vout]")

        else:
            # Horizontal layout (YouTube: 1920x1080)
            if has_custom_bg and bg_idx is not None:
                fc_parts.append(
                    f"[{bg_idx}:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=yuv420p[custom_base_bg];"
                    f"[0:v]fps={fps},scale=1600:900:force_original_aspect_ratio=decrease,pad=1600:900:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"drawbox=0:0:1600:900:color=white@0.4:t=2[slide_card];"
                    f"[custom_base_bg][slide_card]overlay=(W-w)/2:(H-h)/2[base_v]"
                )
            else:
                fc_parts.append(
                    f"[0:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p[base_v]"
                )
            curr_v = "base_v"

            if has_avatar and avatar_idx is not None:
                delay_sec = intro_duration if has_auto_intro else 0.0
                main_active_end = total_expected_sec - (outro_duration if has_auto_outro else 0.0)
                if delay_sec > 0:
                    fc_parts.append(
                        f"[{avatar_idx}:v]scale=384:216,drawbox=0:0:384:216:color=white@0.8:t=2,setpts=PTS-STARTPTS+{delay_sec}/TB[pip];"
                        f"[{curr_v}][pip]overlay=W-w-24:H-h-24:enable='between(t,{delay_sec},{main_active_end})':repeatlast=0[v_pip]"
                    )
                else:
                    fc_parts.append(
                        f"[{avatar_idx}:v]scale=384:216,drawbox=0:0:384:216:color=white@0.8:t=2[pip];"
                        f"[{curr_v}][pip]overlay=W-w-24:H-h-24:enable='lte(t,{main_active_end})':repeatlast=0[v_pip]"
                    )
                curr_v = "v_pip"

            if subtitles_srt_path and Path(subtitles_srt_path).is_file():
                srt_escaped = Path(subtitles_srt_path).resolve().as_posix().replace("'", "'\\''").replace(":", "\\:")
                style = (
                    "Fontname=Arial,Fontsize=18,PrimaryColour=&H00FFFFFF,"
                    "OutlineColour=&H00000000,BackColour=&H80000000,Bold=1,MarginV=35"
                )
                fc_parts.append(f"[{curr_v}]subtitles='{srt_escaped}':force_style='{style}'[vout]")
            else:
                fc_parts.append(f"[{curr_v}]null[vout]")

        # Audio filter pipeline
        if has_bgm and bgm_idx is not None:
            if narration_delay_ms > 0:
                fc_parts.append(
                    f"[1:a]adelay={narration_delay_ms}|{narration_delay_ms}[voice];"
                    f"[{bgm_idx}:a]volume=0.12[bgm];"
                    f"[voice][bgm]amix=inputs=2:duration=first[aout]"
                )
            else:
                fc_parts.append(
                    f"[1:a]volume=1.0[voice];"
                    f"[{bgm_idx}:a]volume=0.12[bgm];"
                    f"[voice][bgm]amix=inputs=2:duration=first[aout]"
                )
        else:
            if narration_delay_ms > 0:
                fc_parts.append(f"[1:a]adelay={narration_delay_ms}|{narration_delay_ms}[aout]")
            else:
                fc_parts.append(f"[1:a]anull[aout]")

        filter_complex_str = "; ".join(fc_parts)
        cmd.extend([
            "-filter_complex", filter_complex_str,
            "-map", "[vout]",
            "-map", "[aout]",
            "-t", f"{total_expected_sec:.3f}",
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            str(main_lesson_target),
        ])

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            startupinfo=startupinfo,
        )

        while True:
            if cancel_check and cancel_check():
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                if Path(main_lesson_target).exists():
                    Path(main_lesson_target).unlink(missing_ok=True)
                raise InterruptedError("Operação cancelada pelo usuário.")

            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    break
                continue

            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us_str = line.split("=")[1]
                    encoded = float(us_str) / 1_000_000.0
                    if total_expected_sec > 0 and progress_callback:
                        frac = min(0.95 if has_custom_clips else 1.0, max(0.0, encoded / total_expected_sec))
                        progress_callback(frac, f"Renderizando aula: {encoded:.1f}s / {total_expected_sec:.1f}s ({int(frac*100)}%)")
                except Exception:
                    pass

        ret = process.wait()
        if ret != 0:
            err_msg = process.stderr.read()
            raise ClassVideoBuilderError(f"Erro na renderização final:\n{err_msg[-400:]}")

        # 3. Concatenate Custom Video Clips (Intro / Outro) if requested
        if has_custom_clips:
            if progress_callback:
                progress_callback(0.96, "Anexando vinhetas personalizadas de abertura e encerramento...")

            concat_parts = []
            if intro_mode == "custom" and intro_video_path and Path(intro_video_path).is_file():
                norm_intro = str(temp_dir / "norm_intro.mp4")
                normalize_video_clip(intro_video_path, norm_intro, resolution, fps=fps)
                concat_parts.append(norm_intro)

            concat_parts.append(main_lesson_target)

            if outro_mode == "custom" and outro_video_path and Path(outro_video_path).is_file():
                norm_outro = str(temp_dir / "norm_outro.mp4")
                normalize_video_clip(outro_video_path, norm_outro, resolution, fps=fps)
                concat_parts.append(norm_outro)

            final_concat_txt = temp_dir / "final_concat.txt"
            with open(final_concat_txt, "w", encoding="utf-8") as f:
                for p in concat_parts:
                    posix = Path(p).resolve().as_posix().replace("'", "'\\''")
                    f.write(f"file '{posix}'\n")

            cmd_concat = [
                ffmpeg_path, "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(final_concat_txt),
                "-c", "copy",
                "-movflags", "+faststart",
                str(out_file),
            ]
            subprocess.run(cmd_concat, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if progress_callback:
            progress_callback(1.0, "Vídeo da aula gerado com sucesso!")

        return str(out_file)

    finally:
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
