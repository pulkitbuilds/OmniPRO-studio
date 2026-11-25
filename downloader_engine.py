import os
import shutil
from typing import Dict, Any, Optional, Callable
import yt_dlp

# Find ffmpeg binary if available
DEFAULT_FFMPEG_PATHS = [
    r"C:\Users\pulki\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe",
    shutil.which("ffmpeg") or "",
]
FFMPEG_PATH: Optional[str] = next(
    (p for p in DEFAULT_FFMPEG_PATHS if p and os.path.isfile(p)), None
)


def get_base_ydl_opts(use_chrome_cookies: bool = False) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "nocheckcertificate": True,
        # Extreme Speed Optimizations
        "concurrent_fragment_downloads": 8,
        "buffersize": 1024 * 64,
        "http_chunk_size": 10485760,
        "retries": 5,
        "fragment_retries": 5,
    }
    if FFMPEG_PATH:
        opts["ffmpeg_location"] = os.path.dirname(FFMPEG_PATH)

    if use_chrome_cookies:
        try:
            opts["cookiesfrombrowser"] = ("chrome", None, None, None)
        except Exception:
            pass

    return opts


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_info(url: str, use_chrome_cookies: bool = False) -> Dict[str, Any]:
    """Extracts metadata, preview streams, and available formats without downloading."""
    opts = get_base_ydl_opts(use_chrome_cookies=use_chrome_cookies)
    opts.update({"extract_flat": False, "skip_download": True})

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError(f"Could not extract video metadata from: {url}")

        if "entries" in info and info["entries"]:
            info = info["entries"][0]

        formats = info.get("formats", [])
        available_resolutions = set()
        has_audio = False
        direct_preview_url = None

        for f in formats:
            height = f.get("height")
            if height:
                available_resolutions.add(f"{height}p")
            if f.get("acodec") != "none":
                has_audio = True
            if (
                not direct_preview_url
                and f.get("ext") == "mp4"
                and f.get("acodec") != "none"
                and f.get("vcodec") != "none"
                and f.get("url")
            ):
                direct_preview_url = f.get("url")

        def res_key(r: str) -> int:
            try:
                return int(r.replace("p", ""))
            except ValueError:
                return 0

        sorted_resolutions = sorted(
            list(available_resolutions), key=res_key, reverse=True
        )

        return {
            "id": info.get("id", ""),
            "title": info.get("title", "Unknown Title"),
            "uploader": info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or "Unknown Uploader",
            "duration": info.get("duration", 0),
            "duration_string": info.get("duration_string")
            or _format_duration(info.get("duration", 0)),
            "thumbnail": info.get("thumbnail")
            or (
                info.get("thumbnails", [{}])[-1].get("url")
                if info.get("thumbnails")
                else None
            ),
            "webpage_url": info.get("webpage_url", url),
            "extractor": info.get("extractor_key", "Generic"),
            "resolutions": sorted_resolutions,
            "has_audio": has_audio,
            "preview_stream_url": direct_preview_url,
            "embed_url": (
                f"https://www.youtube.com/embed/{info.get('id')}"
                if info.get("extractor_key") == "Youtube"
                else None
            ),
            "description": (info.get("description") or "")[:250],
        }


def download_video(
    url: str,
    output_dir: str,
    quality: str = "best",
    use_chrome_cookies: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """High-speed multi-threaded video download engine with FFmpeg muxing."""
    os.makedirs(output_dir, exist_ok=True)
    out_tmpl = os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s")

    opts = get_base_ydl_opts(use_chrome_cookies=use_chrome_cookies)
    opts.update(
        {
            "outtmpl": out_tmpl,
            "windowsfilenames": True,
            "restrictfilenames": False,
        }
    )

    if quality == "audio":
        opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )
    elif quality in ("1080p", "720p", "480p"):
        h = quality.replace("p", "")
        opts.update(
            {
                "format": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best",
                "merge_output_format": "mp4",
            }
        )
    else:
        opts.update(
            {
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            }
        )

    def ydl_hook(d: Dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100) if total > 0 else 0
            if progress_callback:
                progress_callback(
                    {
                        "status": "downloading",
                        "percent": round(percent, 1),
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "speed_str": d.get("_speed_str", "N/A"),
                        "eta_str": d.get("_eta_str", "N/A"),
                        "filename": os.path.basename(d.get("filename", "")),
                    }
                )
        elif status == "finished":
            if progress_callback:
                progress_callback(
                    {
                        "status": "processing",
                        "percent": 100.0,
                        "message": "Merging high-speed streams with FFmpeg...",
                    }
                )

    opts["progress_hooks"] = [ydl_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise ValueError(f"Failed to download video from: {url}")
        if "entries" in info and info["entries"]:
            info = info["entries"][0]

        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        if quality == "audio":
            final_path = f"{base}.mp3"
        else:
            final_path = f"{base}.mp4"
            if not os.path.isfile(final_path) and os.path.isfile(filename):
                final_path = filename

        resolved = final_path if os.path.isfile(final_path) else filename
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "filepath": resolved,
            "filename": os.path.basename(resolved),
            "filesize": os.path.getsize(resolved) if os.path.isfile(resolved) else 0,
            "duration": info.get("duration"),
        }
