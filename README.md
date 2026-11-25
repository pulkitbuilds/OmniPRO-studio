# OmniPRO Studio (Video Downloader + AI Enhancer + Web Scraper)

Full-fledged unified studio combining:
1. **Universal Video Downloader** (`yt-dlp` 8x parallel fragment engine + FastAPI + Chrome Extension)
2. **AI Video Enhancer** (`VideoSuperResolutionNet` RRDBNet PyTorch 2x/4x super-resolution + FFmpeg audio remuxing)
3. **OmniScrape Web Studio** (`omniscrape` intelligent web scraper, pagination crawler, schema inspector, and CSV/JSON/JSONL/Markdown dataset builder with automatic video link discovery)

## Deploy to Vercel

This repository is pre-configured for Vercel (`vercel.json`, `api/index.py`, and lightweight `requirements.txt` within Vercel's serverless size limit):

1. Push this repo to GitHub (`https://github.com/pulkitbuilds/OmniPRO-studio.git`).
2. Import the repository in [Vercel](https://vercel.com/new) and click **Deploy** (zero extra build config needed).

> **Note on Serverless vs Local Mode**: On Vercel, the **Web Studio UI**, **OmniScrape Web Scraper** (all 9 modes + CSV/JSON/JSONL/Markdown export), and **Video Info / Preview Analyzer** work out of the box. Heavy local-only workloads (`torch` / `opencv-python` 2x/4x AI Video Super-Resolution, FFmpeg muxing, and long-running 8x video downloads) require running locally.

## Run Locally (Full Features Including AI Enhancer)

### 1. Install Full Dependencies
```bash
pip install -r requirements-local.txt
```

### 2. Start the Web Studio
```bash
# Windows one-click launcher
run_web.bat

# Or directly
python server.py
```
Then open `http://127.0.0.1:8000`.

### 3. Use the Unified CLI
```bash
# Download a video
python cli.py "https://www.youtube.com/watch?v=..." -q 1080p

# Download and automatically AI-enhance (2x)
python cli.py "https://www.youtube.com/watch?v=..." --enhance --scale 2

# Enhance an existing local video file
python cli.py --enhance-file "C:\path\to\video.mp4" --scale 4

# Scrape a website into a clean CSV dataset
python cli.py --scrape "https://books.toscrape.com" --scrape-mode cards --scrape-pages 2 --scrape-out books.csv
```
