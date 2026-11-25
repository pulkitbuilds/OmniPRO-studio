import os
import re
import json
import uuid
import shutil
import importlib.util
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional

from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    Request,
    Response,
    UploadFile,
    File,
    Form,
    status,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from downloader_engine import extract_info, download_video, FFMPEG_PATH

try:
    from enhancer_engine import enhance_video, get_enhancer_capabilities
    ENHANCER_IMPORT_ERROR: Optional[str] = None
except Exception as exc:
    enhance_video = None  # type: ignore
    get_enhancer_capabilities = None  # type: ignore
    ENHANCER_IMPORT_ERROR = str(exc)

try:
    from omniscrape import UniversalScraper, WebCrawler, DatasetExporter
    SCRAPER_IMPORT_ERROR: Optional[str] = None
except Exception as exc:
    UniversalScraper = None  # type: ignore
    WebCrawler = None  # type: ignore
    DatasetExporter = None  # type: ignore
    SCRAPER_IMPORT_ERROR = str(exc)

app = FastAPI(title="AI Video Downloader & Enhancer Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

if IS_VERCEL:
    UPLOADS_DIR = os.path.join("/tmp", "omnipro-studio", "uploads")
    DOWNLOAD_DIR = os.path.join("/tmp", "omnipro-studio", "downloads")
else:
    UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
    DEFAULT_DOWNLOAD_DIR = os.environ.get(
        "VIDEO_STUDIO_DOWNLOAD_DIR",
        os.path.join(os.path.expanduser("~"), "Downloads", "VideoStudio"),
    )
    try:
        os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)
        DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR
    except OSError:
        DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

for _d in (UPLOADS_DIR, DOWNLOAD_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

if not IS_VERCEL:
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
    except OSError:
        pass

jobs: Dict[str, Dict[str, Any]] = {}
thread_pool = ThreadPoolExecutor(max_workers=4)


class InfoRequest(BaseModel):
    url: str
    use_chrome_cookies: bool = False


class BatchInfoRequest(BaseModel):
    urls: List[str]
    use_chrome_cookies: bool = False


class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"
    use_chrome_cookies: bool = False
    custom_dir: str = ""
    auto_enhance: bool = False
    enhance_scale: int = 2
    enhance_tile_size: int = 256
    enhance_use_gpu: bool = True
    enhance_model_path: Optional[str] = None


class BatchDownloadRequest(BaseModel):
    urls: List[str]
    quality: str = "best"
    use_chrome_cookies: bool = False
    custom_dir: str = ""
    auto_enhance: bool = False
    enhance_scale: int = 2
    enhance_tile_size: int = 256
    enhance_use_gpu: bool = True
    enhance_model_path: Optional[str] = None


class EnhanceRequest(BaseModel):
    filename: Optional[str] = None
    filepath: Optional[str] = None
    scale: int = 2
    tile_size: int = 256
    use_gpu: bool = True
    model_path: Optional[str] = None


class ScrapeRequest(BaseModel):
    url: str
    mode: str = "auto"
    pages: int = 1
    item_selector: Optional[str] = None
    fields: Optional[Dict[str, str]] = None
    delay: float = 0.5
    proxy: Optional[str] = None
    custom_headers: Optional[Dict[str, str]] = None
    deduplicate: bool = True


class DeleteFileRequest(BaseModel):
    filename: str


LATEST_SCRAPE: Dict[str, Any] = {
    "df": None,
    "records": [],
    "columns": [],
    "url": "",
    "strategy": "",
}
SCRAPE_HISTORY: List[Dict[str, Any]] = []

MEDIA_URL_PATTERN = re.compile(
    r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|vimeo\.com/|tiktok\.com/|instagram\.com/(?:reel|p)/|x\.com/.+/status/|twitter\.com/.+/status/)[^\s\"'<>]+|https?://[^\s\"'<>]+\.(?:mp4|webm|mov|mkv|m3u8)(?:\?[^\s\"'<>]*)?)",
    re.IGNORECASE,
)


def _resolve_model_path(model_name_or_path: Optional[str]) -> Optional[str]:
    if not model_name_or_path:
        return None
    cleaned = model_name_or_path.strip()
    if not cleaned:
        return None
    if os.path.isfile(cleaned):
        return cleaned
    candidate = os.path.join(MODELS_DIR, os.path.basename(cleaned))
    return candidate if os.path.isfile(candidate) else None


def _build_enhanced_output_path(input_path: str, scale: int, target_dir: str) -> str:
    stem, _ = os.path.splitext(os.path.basename(input_path))
    return os.path.join(target_dir, f"{stem}_enhanced_{scale}x.mp4")


@app.post("/api/info")
def get_info(req: InfoRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    try:
        data = extract_info(req.url.strip(), use_chrome_cookies=req.use_chrome_cookies)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/batch-info")
def get_batch_info(req: BatchInfoRequest):
    valid_urls = [u.strip() for u in req.urls if u and u.strip()]
    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid URLs provided")

    def _fetch_one(u: str):
        try:
            return {
                "url": u,
                "success": True,
                "data": extract_info(u, use_chrome_cookies=req.use_chrome_cookies),
            }
        except Exception as e:
            return {"url": u, "success": False, "error": str(e)}

    results = list(thread_pool.map(_fetch_one, valid_urls))
    return {"success": True, "results": results}


def _run_download_job(
    job_id: str,
    url: str,
    quality: str,
    use_chrome_cookies: bool,
    target_dir: str,
    auto_enhance: bool = False,
    enhance_scale: int = 2,
    enhance_tile_size: int = 256,
    enhance_use_gpu: bool = True,
    enhance_model_path: Optional[str] = None,
):
    def dl_progress_callback(p: Dict[str, Any]):
        jobs[job_id]["progress"] = p

    def enh_progress_callback(p: Dict[str, Any]):
        jobs[job_id]["progress"] = p

    try:
        jobs[job_id]["status"] = "downloading"
        dl_res = download_video(
            url=url,
            output_dir=target_dir,
            quality=quality,
            use_chrome_cookies=use_chrome_cookies,
            progress_callback=dl_progress_callback,
        )

        if auto_enhance and quality != "audio":
            if enhance_video is None:
                raise RuntimeError(
                    f"AI Enhancer dependencies unavailable: {ENHANCER_IMPORT_ERROR}"
                )
            jobs[job_id]["status"] = "enhancing"
            jobs[job_id]["progress"] = {
                "status": "loading_model",
                "percent": 0.0,
                "message": "Download finished. Starting AI Enhancement...",
            }
            out_path = _build_enhanced_output_path(
                dl_res["filepath"], enhance_scale, target_dir
            )
            enh_res = enhance_video(
                input_path=dl_res["filepath"],
                output_path=out_path,
                model_path=_resolve_model_path(enhance_model_path),
                scale=enhance_scale,
                tile_size=enhance_tile_size,
                use_gpu=enhance_use_gpu,
                progress_callback=enh_progress_callback,
            )
            dl_res["enhanced"] = enh_res
            dl_res["filepath"] = enh_res["filepath"]
            dl_res["filename"] = enh_res["filename"]
            dl_res["filesize"] = enh_res["filesize"]

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = dl_res
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)


def _run_enhance_job(
    job_id: str,
    input_path: str,
    output_path: str,
    scale: int,
    tile_size: int,
    use_gpu: bool,
    model_path: Optional[str],
    cleanup_input: bool = False,
):
    def progress_callback(p: Dict[str, Any]):
        jobs[job_id]["progress"] = p

    try:
        if enhance_video is None:
            raise RuntimeError(
                f"AI Enhancer dependencies unavailable: {ENHANCER_IMPORT_ERROR}"
            )
        jobs[job_id]["status"] = "enhancing"
        res = enhance_video(
            input_path=input_path,
            output_path=output_path,
            model_path=_resolve_model_path(model_path),
            scale=scale,
            tile_size=tile_size,
            use_gpu=use_gpu,
            progress_callback=progress_callback,
        )
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = res
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
    finally:
        if cleanup_input and os.path.isfile(input_path):
            try:
                os.remove(input_path)
            except OSError:
                pass


@app.post("/api/download")
def start_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    target_dir = (
        req.custom_dir.strip()
        if req.custom_dir and os.path.isdir(req.custom_dir.strip())
        else DOWNLOAD_DIR
    )
    job_id = str(uuid.uuid4())[:8]

    jobs[job_id] = {
        "id": job_id,
        "type": "download+enhance" if req.auto_enhance else "download",
        "url": url,
        "quality": req.quality,
        "status": "queued",
        "progress": {"percent": 0, "status": "queued"},
        "result": None,
        "error": None,
    }

    background_tasks.add_task(
        _run_download_job,
        job_id,
        url,
        req.quality,
        req.use_chrome_cookies,
        target_dir,
        req.auto_enhance,
        req.enhance_scale,
        req.enhance_tile_size,
        req.enhance_use_gpu,
        req.enhance_model_path,
    )
    return {"success": True, "job_id": job_id, "output_dir": target_dir}


@app.post("/api/batch-download")
def start_batch_download(
    req: BatchDownloadRequest, background_tasks: BackgroundTasks
):
    valid_urls = [u.strip() for u in req.urls if u and u.strip()]
    if not valid_urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    target_dir = (
        req.custom_dir.strip()
        if req.custom_dir and os.path.isdir(req.custom_dir.strip())
        else DOWNLOAD_DIR
    )
    created_jobs = []

    for url in valid_urls:
        job_id = str(uuid.uuid4())[:8]
        jobs[job_id] = {
            "id": job_id,
            "type": "download+enhance" if req.auto_enhance else "download",
            "url": url,
            "quality": req.quality,
            "status": "queued",
            "progress": {"percent": 0, "status": "queued"},
            "result": None,
            "error": None,
        }
        background_tasks.add_task(
            _run_download_job,
            job_id,
            url,
            req.quality,
            req.use_chrome_cookies,
            target_dir,
            req.auto_enhance,
            req.enhance_scale,
            req.enhance_tile_size,
            req.enhance_use_gpu,
            req.enhance_model_path,
        )
        created_jobs.append({"id": job_id, "url": url})

    return {"success": True, "jobs": created_jobs, "output_dir": target_dir}


@app.get("/api/enhance/status")
def enhancer_status():
    checkpoints = (
        [
            f
            for f in os.listdir(MODELS_DIR)
            if f.lower().endswith((".pth", ".pt", ".safetensors"))
        ]
        if os.path.isdir(MODELS_DIR)
        else []
    )
    if get_enhancer_capabilities is None:
        return {
            "available": False,
            "error": ENHANCER_IMPORT_ERROR,
            "ffmpeg_available": FFMPEG_PATH is not None,
            "models": checkpoints,
        }
    caps = get_enhancer_capabilities()
    caps["available"] = True
    caps["models"] = checkpoints
    return caps


@app.post("/api/enhance")
def start_enhance(req: EnhanceRequest, background_tasks: BackgroundTasks):
    if enhance_video is None:
        raise HTTPException(
            status_code=503,
            detail=f"AI Enhancer unavailable: {ENHANCER_IMPORT_ERROR}",
        )

    if req.filename:
        clean_name = os.path.basename(req.filename)
        input_path = os.path.join(DOWNLOAD_DIR, clean_name)
    elif req.filepath:
        input_path = req.filepath.strip()
    else:
        raise HTTPException(
            status_code=400, detail="Provide either 'filename' or 'filepath'"
        )

    if not os.path.isfile(input_path):
        raise HTTPException(status_code=404, detail=f"Video not found: {input_path}")
    if req.scale not in (2, 4):
        raise HTTPException(status_code=400, detail="Scale must be 2 or 4")

    output_path = _build_enhanced_output_path(input_path, req.scale, DOWNLOAD_DIR)
    job_id = str(uuid.uuid4())[:8]

    jobs[job_id] = {
        "id": job_id,
        "type": "enhance",
        "filename": os.path.basename(input_path),
        "scale": req.scale,
        "status": "queued",
        "progress": {"percent": 0, "status": "queued"},
        "result": None,
        "error": None,
    }

    background_tasks.add_task(
        _run_enhance_job,
        job_id,
        input_path,
        output_path,
        req.scale,
        req.tile_size,
        req.use_gpu,
        req.model_path,
        False,
    )
    return {"success": True, "job_id": job_id, "output_path": output_path}


HAS_MULTIPART = (
    importlib.util.find_spec("python_multipart") is not None
    or importlib.util.find_spec("multipart") is not None
)

if HAS_MULTIPART:

    @app.post("/api/enhance-upload")
    async def start_enhance_upload(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        scale: int = Form(2),
        tile_size: int = Form(256),
        use_gpu: bool = Form(True),
        model_path: Optional[str] = Form(None),
    ):
        if enhance_video is None:
            raise HTTPException(
                status_code=503,
                detail=f"AI Enhancer unavailable: {ENHANCER_IMPORT_ERROR}",
            )
        if scale not in (2, 4):
            raise HTTPException(status_code=400, detail="Scale must be 2 or 4")

        safe_name = os.path.basename(file.filename or "upload.mp4")
        job_id = str(uuid.uuid4())[:8]
        upload_path = os.path.join(UPLOADS_DIR, f"{job_id}_{safe_name}")

        with open(upload_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        stem, _ = os.path.splitext(safe_name)
        output_path = os.path.join(DOWNLOAD_DIR, f"{stem}_enhanced_{scale}x.mp4")

        jobs[job_id] = {
            "id": job_id,
            "type": "enhance",
            "filename": safe_name,
            "scale": scale,
            "status": "queued",
            "progress": {"percent": 0, "status": "queued"},
            "result": None,
            "error": None,
        }

        background_tasks.add_task(
            _run_enhance_job,
            job_id,
            upload_path,
            output_path,
            scale,
            tile_size,
            use_gpu,
            model_path,
            True,
        )
        return {"success": True, "job_id": job_id, "output_path": output_path}

else:

    @app.post("/api/enhance-upload")
    async def start_enhance_upload_unavailable():
        raise HTTPException(
            status_code=503,
            detail="File upload requires 'python-multipart'. Run: pip install python-multipart",
        )


@app.get("/api/progress/{job_id}")
def get_progress(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": list(reversed(list(jobs.values())))[:30]}


@app.get("/api/scrape/status")
def scraper_status():
    return {
        "available": UniversalScraper is not None,
        "error": SCRAPER_IMPORT_ERROR,
    }


@app.post("/api/scrape")
def run_scrape(req: ScrapeRequest):
    if UniversalScraper is None or WebCrawler is None or DatasetExporter is None:
        raise HTTPException(
            status_code=503,
            detail=f"Web Scraper unavailable: {SCRAPER_IMPORT_ERROR}",
        )
    url = (req.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    pages = max(1, min(20, int(req.pages or 1)))
    try:
        scraper = UniversalScraper(
            delay=max(0.0, min(10.0, float(req.delay))),
            proxy=req.proxy.strip() if req.proxy and req.proxy.strip() else None,
            custom_headers=req.custom_headers,
        )
        crawler = WebCrawler(scraper=scraper)
        exporter = DatasetExporter(deduplicate=req.deduplicate)

        if pages > 1:
            records = crawler.crawl_pagination(
                url,
                max_pages=pages,
                mode=req.mode,
                item_selector=req.item_selector,
                fields=req.fields,
            )
            strategy = f"crawler ({pages} pages)"
        else:
            strategy, records = scraper.scrape(
                url,
                mode=req.mode,
                item_selector=req.item_selector,
                fields=req.fields,
            )

        if not records:
            raise ValueError(
                f"No records could be extracted from {url} using mode '{req.mode}'."
            )

        raw_count = len(records)
        processed = exporter.process_records(records, source_url=url)
        df = exporter.to_dataframe(processed)

        LATEST_SCRAPE["df"] = df
        LATEST_SCRAPE["records"] = processed
        LATEST_SCRAPE["columns"] = list(df.columns)
        LATEST_SCRAPE["url"] = url
        LATEST_SCRAPE["strategy"] = strategy

        # Build column schema & data quality analytics
        total_rows = int(len(df))
        schema_stats = []
        for col in df.columns:
            series = df[col]
            non_empty = int(((series.notna()) & (series.astype(str).str.strip() != "")).sum())
            unique_cnt = int(series.astype(str).nunique(dropna=True))
            sample_vals = [
                str(v) for v in series.dropna().astype(str).tolist() if v.strip()
            ][:1]
            schema_stats.append(
                {
                    "name": col,
                    "dtype": str(series.dtype),
                    "non_null": non_empty,
                    "completeness_pct": round((non_empty / total_rows) * 100, 1)
                    if total_rows
                    else 0.0,
                    "unique_count": unique_cnt,
                    "sample": (sample_vals[0][:80] if sample_vals else ""),
                }
            )

        # Discover any video/media URLs inside scraped records for 1-click download
        discovered_media: List[str] = []
        seen_media = set()
        for rec in processed[:300]:
            for val in rec.values():
                if isinstance(val, str):
                    for match in MEDIA_URL_PATTERN.findall(val):
                        if match not in seen_media:
                            seen_media.add(match)
                            discovered_media.append(match)

        safe_records = (
            df.head(300)
            .where(df.head(300).notna(), None)
            .to_dict(orient="records")
        )

        scrape_id = str(uuid.uuid4())[:8]
        telemetry = dict(scraper.last_telemetry or {})
        payload = {
            "success": True,
            "scrape_id": scrape_id,
            "url": url,
            "strategy": strategy,
            "total_rows": total_rows,
            "duplicates_removed": max(0, raw_count - len(processed)),
            "columns": list(df.columns),
            "schema_stats": schema_stats,
            "telemetry": telemetry,
            "records": safe_records,
            "discovered_media_urls": discovered_media[:30],
        }

        SCRAPE_HISTORY.insert(
            0,
            {
                "scrape_id": scrape_id,
                "url": url,
                "strategy": strategy,
                "total_rows": total_rows,
                "columns": list(df.columns),
                "df": df,
                "records": processed,
                "payload": payload,
            },
        )
        if len(SCRAPE_HISTORY) > 15:
            SCRAPE_HISTORY.pop()

        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/scrape/history")
def get_scrape_history():
    return {
        "history": [
            {
                "scrape_id": h["scrape_id"],
                "url": h["url"],
                "strategy": h["strategy"],
                "total_rows": h["total_rows"],
                "columns": len(h["columns"]),
            }
            for h in SCRAPE_HISTORY
        ]
    }


@app.get("/api/scrape/history/{scrape_id}")
def load_scrape_history(scrape_id: str):
    for h in SCRAPE_HISTORY:
        if h["scrape_id"] == scrape_id:
            LATEST_SCRAPE["df"] = h["df"]
            LATEST_SCRAPE["records"] = h["records"]
            LATEST_SCRAPE["columns"] = h["columns"]
            LATEST_SCRAPE["url"] = h["url"]
            LATEST_SCRAPE["strategy"] = h["strategy"]
            return h["payload"]
    raise HTTPException(status_code=404, detail="Scrape history entry not found")


@app.get("/api/scrape/export")
def export_scrape(format: str = "csv"):
    df = LATEST_SCRAPE.get("df")
    records = LATEST_SCRAPE.get("records") or []
    if df is None or not records:
        raise HTTPException(status_code=404, detail="No scraped dataset available.")

    fmt = format.lower().strip()
    if fmt == "csv":
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8-sig",
            headers={
                "Content-Disposition": 'attachment; filename="omniscrape_dataset.csv"'
            },
        )
    elif fmt == "json":
        payload = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=payload,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="omniscrape_dataset.json"'
            },
        )
    elif fmt == "jsonl":
        lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        return Response(
            content=lines.encode("utf-8"),
            media_type="application/x-ndjson; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="omniscrape_dataset.jsonl"'
            },
        )
    elif fmt == "md":
        cols = list(df.columns)
        header = "| " + " | ".join(cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        rows = []
        for _, r in df.head(500).iterrows():
            vals = [str(r[c] if r[c] is not None else "").replace("|", "\\|").replace("\n", " ") for c in cols]
            rows.append("| " + " | ".join(vals) + " |")
        md_text = "\n".join([header, sep] + rows)
        return Response(
            content=md_text.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="omniscrape_dataset.md"'
            },
        )
    raise HTTPException(status_code=400, detail="Format must be csv, json, jsonl, or md")


@app.post("/api/downloads/delete")
def delete_download(req: DeleteFileRequest):
    clean_name = os.path.basename(req.filename)
    file_path = os.path.join(DOWNLOAD_DIR, clean_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        os.remove(file_path)
        return {"success": True, "deleted": clean_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/open-folder")
def open_folder():
    if IS_VERCEL or not hasattr(os, "startfile"):
        return {
            "success": False,
            "path": DOWNLOAD_DIR,
            "message": "Opening local folder is only supported when running locally on Windows.",
        }
    try:
        os.startfile(DOWNLOAD_DIR)
        return {"success": True, "path": DOWNLOAD_DIR}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/downloads")
def list_downloads():
    if not os.path.isdir(DOWNLOAD_DIR):
        return {"files": [], "directory": DOWNLOAD_DIR}
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.startswith("."):
            continue
        full = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(full):
            files.append(
                {
                    "name": f,
                    "size_mb": round(os.path.getsize(full) / (1024 * 1024), 2),
                    "modified": os.path.getmtime(full),
                    "is_video": f.lower().endswith(
                        (".mp4", ".mkv", ".webm", ".avi", ".mov")
                    ),
                    "is_audio": f.lower().endswith(
                        (".mp3", ".m4a", ".aac", ".flac", ".wav")
                    ),
                    "is_enhanced": "_enhanced_" in f.lower(),
                }
            )
    files.sort(key=lambda x: x["modified"], reverse=True)
    return {"files": files, "directory": DOWNLOAD_DIR}


def send_bytes_range_requests(
    file_path: str, start: int, end: int, chunk_size: int = 1024 * 1024
):
    with open(file_path, mode="rb") as f:
        f.seek(start)
        while (pos := f.tell()) <= end:
            read_size = min(chunk_size, end + 1 - pos)
            yield f.read(read_size)


@app.get("/api/stream/{job_id}")
def stream_video(job_id: str, request: Request):
    job = jobs.get(job_id)
    if not job or not job.get("result") or not job["result"].get("filepath"):
        raise HTTPException(
            status_code=404, detail="Video file not found or not yet completed"
        )
    return _serve_file_range(job["result"]["filepath"], request)


@app.get("/api/stream-file")
def stream_named_file(filename: str, request: Request):
    clean_name = os.path.basename(filename)
    file_path = os.path.join(DOWNLOAD_DIR, clean_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File does not exist")
    return _serve_file_range(file_path, request)


def _serve_file_range(file_path: str, request: Request):
    file_size = os.stat(file_path).st_size
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "video/mp4"

    range_header = request.headers.get("range")
    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": content_type,
        }
        return StreamingResponse(
            send_bytes_range_requests(file_path, start, end),
            headers=headers,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
        )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": content_type,
    }
    return StreamingResponse(
        send_bytes_range_requests(file_path, 0, file_size - 1),
        headers=headers,
        status_code=status.HTTP_200_OK,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(BASE_DIR, "static", "index.html")
    if os.path.isfile(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>AI Video Downloader & Enhancer Studio API running.</h1>"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
