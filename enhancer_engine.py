import os
import time
import uuid
import subprocess
from typing import Dict, Any, Optional, Callable

import cv2
import numpy as np
import torch

from downloader_engine import FFMPEG_PATH
from model import VideoSuperResolutionNet


def get_ffmpeg_exe() -> Optional[str]:
    """Return resolved FFmpeg executable path if available."""
    if FFMPEG_PATH and os.path.isfile(FFMPEG_PATH):
        return FFMPEG_PATH
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return "ffmpeg"
    except Exception:
        return None


def get_enhancer_capabilities() -> Dict[str, Any]:
    """Report PyTorch, CUDA GPU, and FFmpeg availability for the UI and API."""
    cuda_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if cuda_available else None
    return {
        "cuda_available": cuda_available,
        "device": "cuda" if cuda_available else "cpu",
        "gpu_name": gpu_name,
        "ffmpeg_available": get_ffmpeg_exe() is not None,
        "torch_version": torch.__version__,
    }


def _enhance_tile(
    tile: np.ndarray, model: VideoSuperResolutionNet, device: torch.device
) -> np.ndarray:
    """Inference on a single RGB tile with shape (H, W, C)."""
    with torch.no_grad():
        inp = (
            torch.from_numpy(tile)
            .permute(2, 0, 1)
            .unsqueeze(0)
            .float()
            .to(device)
            / 255.0
        )
        out = model(inp)
        out = out.squeeze(0).permute(1, 2, 0).cpu().numpy() * 255.0
        return np.clip(out, 0, 255).astype(np.uint8)


def enhance_frame_tiled(
    frame: np.ndarray,
    model: VideoSuperResolutionNet,
    device: torch.device,
    scale: int = 4,
    tile_size: int = 256,
    tile_pad: int = 16,
) -> np.ndarray:
    """Process high-resolution frames in overlapping tiles to prevent GPU OOM."""
    h, w, c = frame.shape
    out_h, out_w = h * scale, w * scale
    output = np.zeros((out_h, out_w, c), dtype=np.uint8)

    for y in range(0, h, tile_size):
        for x in range(0, w, tile_size):
            y_start = max(0, y - tile_pad)
            y_end = min(h, y + tile_size + tile_pad)
            x_start = max(0, x - tile_pad)
            x_end = min(w, x + tile_size + tile_pad)

            tile = frame[y_start:y_end, x_start:x_end]
            enhanced_tile = _enhance_tile(tile, model, device)

            tile_y_offset = (y - y_start) * scale
            tile_x_offset = (x - x_start) * scale
            valid_h = min(tile_size, h - y) * scale
            valid_w = min(tile_size, w - x) * scale

            cropped = enhanced_tile[
                tile_y_offset : tile_y_offset + valid_h,
                tile_x_offset : tile_x_offset + valid_w,
            ]

            out_y = y * scale
            out_x = x * scale
            output[out_y : out_y + valid_h, out_x : out_x + valid_w] = cropped

    return output


def _format_eta(seconds: float) -> str:
    if seconds <= 0 or not np.isfinite(seconds):
        return "--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def enhance_video(
    input_path: str,
    output_path: str,
    model_path: Optional[str] = None,
    scale: int = 2,
    tile_size: int = 256,
    use_gpu: bool = True,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    AI Super-Resolution & Video Enhancement pipeline with tiled inference,
    progress callbacks, and FFmpeg H.264/AAC audio remuxing.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")
    if scale not in (2, 4):
        raise ValueError("Scale must be 2 or 4")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    device = torch.device("cuda" if use_gpu and torch.cuda.is_available() else "cpu")

    if progress_callback:
        progress_callback(
            {
                "status": "loading_model",
                "percent": 0.0,
                "message": f"Initializing {scale}x RRDBNet on {device.type.upper()}...",
            }
        )

    model = VideoSuperResolutionNet(scale=scale).to(device)
    if model_path and os.path.isfile(model_path):
        checkpoint = torch.load(model_path, map_location=device)
        model.load_state_dict(checkpoint, strict=False)
    model.eval()

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {input_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_width = width * scale
    out_height = height * scale

    temp_video = os.path.join(
        os.path.dirname(os.path.abspath(output_path)),
        f".tmp_enhanced_{uuid.uuid4().hex[:8]}.mp4",
    )
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(temp_video, fourcc, fps, (out_width, out_height))

    start_time = time.time()
    frame_idx = 0

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            enhanced_rgb = enhance_frame_tiled(
                frame_rgb, model, device, scale=scale, tile_size=tile_size
            )
            enhanced_bgr = cv2.cvtColor(enhanced_rgb, cv2.COLOR_RGB2BGR)
            writer.write(enhanced_bgr)

            frame_idx += 1
            elapsed = max(time.time() - start_time, 1e-6)
            proc_fps = frame_idx / elapsed
            pct = (
                min(99.0, (frame_idx / total_frames) * 100.0)
                if total_frames > 0
                else 0.0
            )
            eta_sec = (
                (total_frames - frame_idx) / proc_fps
                if total_frames > 0 and proc_fps > 0
                else 0.0
            )

            if progress_callback:
                progress_callback(
                    {
                        "status": "enhancing",
                        "percent": round(pct, 1),
                        "current_frame": frame_idx,
                        "total_frames": total_frames,
                        "speed_str": f"{proc_fps:.2f} fps",
                        "eta_str": _format_eta(eta_sec),
                        "message": f"Enhancing frame {frame_idx}/{total_frames or '?'} ({width}x{height} → {out_width}x{out_height})",
                    }
                )
    finally:
        cap.release()
        writer.release()

    if progress_callback:
        progress_callback(
            {
                "status": "remuxing",
                "percent": 99.5,
                "speed_str": "--",
                "eta_str": "Almost done",
                "message": "Encoding H.264 & remuxing original audio with FFmpeg...",
            }
        )

    ffmpeg_exe = get_ffmpeg_exe()
    if ffmpeg_exe:
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i",
            temp_video,
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            output_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=False)
        if os.path.exists(temp_video):
            os.remove(temp_video)
    else:
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(temp_video, output_path)

    return {
        "filepath": output_path,
        "filename": os.path.basename(output_path),
        "filesize": os.path.getsize(output_path) if os.path.isfile(output_path) else 0,
        "input_resolution": f"{width}x{height}",
        "output_resolution": f"{out_width}x{out_height}",
        "scale": scale,
        "frames_processed": frame_idx,
        "device": device.type,
    }
