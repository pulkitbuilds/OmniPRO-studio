import http.server
import json
import os
import socketserver
import urllib.parse
from typing import Any, Dict, List
import pandas as pd

from .scraper import UniversalScraper
from .crawler import WebCrawler
from .dataset import DatasetExporter

LATEST_DATA: Dict[str, Any] = {
    "df": None,
    "records": [],
    "columns": [],
    "url": "",
    "strategy": "",
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OmniScrape - Universal Dataset Builder</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #111827;
      --card-border: #1f2937;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --primary: #6366f1;
      --primary-hover: #4f46e5;
      --accent: #10b981;
      --input-bg: #1e293b;
      --input-border: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
    body { background-color: var(--bg); color: var(--text); min-height: 100vh; padding: 2rem 1.5rem; }
    .container { max-width: 1200px; margin: 0 auto; }
    .header { text-align: center; margin-bottom: 2rem; }
    .badge { display: inline-block; background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3); padding: 0.35rem 0.85rem; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
    h1 { font-size: 2.25rem; font-weight: 800; background: linear-gradient(135deg, #fff 0%, #cbd5e1 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }
    p.subtitle { color: var(--text-muted); font-size: 1rem; max-width: 600px; margin: 0 auto; }
    
    .panel { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 1rem; padding: 1.75rem; margin-bottom: 2rem; box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); }
    .form-grid { display: grid; grid-template-columns: 2fr 1fr 100px auto; gap: 1rem; align-items: end; }
    @media (max-width: 800px) { .form-grid { grid-template-columns: 1fr; } }
    
    label { display: block; font-size: 0.825rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.4rem; }
    input, select { width: 100%; background: var(--input-bg); border: 1px solid var(--input-border); color: #fff; padding: 0.75rem 1rem; border-radius: 0.5rem; font-size: 0.95rem; outline: none; transition: border-color 0.2s; }
    input:focus, select:focus { border-color: var(--primary); }
    
    button.btn-primary { background: linear-gradient(135deg, #6366f1, #4f46e5); color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 0.5rem; font-weight: 600; font-size: 0.95rem; cursor: pointer; transition: opacity 0.2s, transform 0.1s; height: 46px; }
    button.btn-primary:hover { opacity: 0.95; }
    button.btn-primary:active { transform: scale(0.98); }
    
    .stats-bar { display: flex; gap: 1.5rem; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; padding-bottom: 1.25rem; border-bottom: 1px solid var(--card-border); flex-wrap: wrap; }
    .stat-pill { display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; color: var(--text-muted); }
    .stat-pill strong { color: #fff; }
    .btn-download { display: inline-flex; align-items: center; gap: 0.5rem; background: var(--accent); color: #022c22; font-weight: 700; padding: 0.6rem 1.25rem; border-radius: 0.5rem; text-decoration: none; font-size: 0.9rem; transition: background 0.2s; }
    .btn-download:hover { background: #34d399; }
    
    .table-container { overflow-x: auto; max-height: 520px; border-radius: 0.5rem; border: 1px solid var(--card-border); }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; text-align: left; }
    th { position: sticky; top: 0; background: #1e293b; color: #cbd5e1; font-weight: 600; padding: 0.85rem 1rem; border-bottom: 2px solid var(--card-border); white-space: nowrap; }
    td { padding: 0.75rem 1rem; border-bottom: 1px solid #1e293b; color: #e2e8f0; max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    tr:hover td { background: rgba(255, 255, 255, 0.03); }
    
    .empty-state { text-align: center; padding: 4rem 1rem; color: var(--text-muted); }
    .empty-icon { font-size: 3rem; margin-bottom: 1rem; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 3px solid rgba(255,255,255,.3); border-radius: 50%; border-top-color: #fff; animation: spin 1s ease-in-out infinite; margin-right: 0.5rem; vertical-align: middle; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <span class="badge">Universal Intelligent Dataset Engine</span>
      <h1>OmniScrape Web Studio</h1>
      <p class="subtitle">Extract clean, machine-learning-ready CSV datasets from any website in seconds.</p>
    </div>

    <div class="panel">
      <form id="scrapeForm" class="form-grid">
        <div>
          <label>Target Website URL</label>
          <input type="url" id="url" name="url" placeholder="https://example.com/products or articles..." required>
        </div>
        <div>
          <label>Extraction Mode</label>
          <select id="mode" name="mode">
            <option value="auto">✨ Smart Auto-Detect</option>
            <option value="cards">🛍️ Product & Listing Cards</option>
            <option value="tables">📊 HTML Tables</option>
            <option value="json_ld">🧬 Schema.org JSON-LD</option>
            <option value="article">📰 Full Article & Text</option>
          </select>
        </div>
        <div>
          <label>Max Pages</label>
          <input type="number" id="pages" name="pages" value="1" min="1" max="20">
        </div>
        <div>
          <button type="submit" id="submitBtn" class="btn-primary">Scrape to CSV</button>
        </div>
      </form>
    </div>

    <div class="panel" id="resultsPanel" style="display: none;">
      <div class="stats-bar">
        <div style="display: flex; gap: 1.5rem; flex-wrap: wrap;">
          <div class="stat-pill">Strategy: <strong id="statStrategy">-</strong></div>
          <div class="stat-pill">Extracted Rows: <strong id="statRows">0</strong></div>
          <div class="stat-pill">Columns: <strong id="statCols">0</strong></div>
        </div>
        <div>
          <a href="/download-csv" id="downloadBtn" class="btn-download" download="dataset.csv">
            📥 Download CSV
          </a>
        </div>
      </div>

      <div class="table-container">
        <table id="dataTable">
          <thead><tr id="tableHead"></tr></thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
    </div>

    <div class="panel empty-state" id="initialState">
      <div class="empty-icon">🌐</div>
      <h3>Ready to Build Your Dataset</h3>
      <p style="margin-top: 0.5rem;">Enter any website address above and choose an extraction mode. OmniScrape will auto-detect structured patterns, clean the records, and export a ready-to-use CSV.</p>
    </div>
  </div>

  <script>
    const form = document.getElementById('scrapeForm');
    const submitBtn = document.getElementById('submitBtn');
    const resultsPanel = document.getElementById('resultsPanel');
    const initialState = document.getElementById('initialState');
    const statStrategy = document.getElementById('statStrategy');
    const statRows = document.getElementById('statRows');
    const statCols = document.getElementById('statCols');
    const tableHead = document.getElementById('tableHead');
    const tableBody = document.getElementById('tableBody');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const url = document.getElementById('url').value;
      const mode = document.getElementById('mode').value;
      const pages = parseInt(document.getElementById('pages').value) || 1;

      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner"></span> Scraping...';

      try {
        const res = await fetch('/api/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, mode, pages })
        });
        const data = await res.json();

        if (data.error) {
          alert('Scrape error: ' + data.error);
          return;
        }

        statStrategy.textContent = data.strategy;
        statRows.textContent = data.total_rows;
        statCols.textContent = data.columns.length;

        // Render Headers
        tableHead.innerHTML = '';
        data.columns.forEach(col => {
          const th = document.createElement('th');
          th.textContent = col;
          tableHead.appendChild(th);
        });

        // Render Rows
        tableBody.innerHTML = '';
        data.records.forEach(row => {
          const tr = document.createElement('tr');
          data.columns.forEach(col => {
            const td = document.createElement('td');
            const val = row[col] !== undefined && row[col] !== null ? String(row[col]) : '';
            td.textContent = val;
            td.title = val;
            tr.appendChild(td);
          });
          tableBody.appendChild(tr);
        });

        initialState.style.display = 'none';
        resultsPanel.style.display = 'block';
      } catch (err) {
        alert('Network error: ' + err.message);
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Scrape to CSV';
      }
    });
  </script>
</body>
</html>
"""


class ScraperHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif parsed.path == "/download-csv":
            if LATEST_DATA["df"] is not None:
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8-sig")
                self.send_header("Content-Disposition", 'attachment; filename="scraped_dataset.csv"')
                self.end_headers()
                csv_bytes = LATEST_DATA["df"].to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                self.wfile.write(csv_bytes)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"No data available to download.")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/scrape":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body.decode("utf-8"))
                url = payload.get("url")
                mode = payload.get("mode", "auto")
                pages = int(payload.get("pages", 1))

                if not url:
                    raise ValueError("URL is required.")

                scraper = UniversalScraper()
                crawler = WebCrawler(scraper=scraper)
                exporter = DatasetExporter()

                if pages > 1:
                    records = crawler.crawl_pagination(url, max_pages=pages, mode=mode)
                    strategy = f"crawler ({pages} pages)"
                else:
                    strategy, records = scraper.scrape(url, mode=mode)

                if not records:
                    raise ValueError("No records could be extracted with this mode.")

                processed = exporter.process_records(records, source_url=url)
                df = exporter.to_dataframe(processed)

                LATEST_DATA["df"] = df
                LATEST_DATA["records"] = processed
                LATEST_DATA["columns"] = list(df.columns)
                LATEST_DATA["url"] = url
                LATEST_DATA["strategy"] = strategy

                resp_data = {
                    "strategy": strategy,
                    "total_rows": len(df),
                    "columns": list(df.columns),
                    "records": df.head(100).to_dict(orient="records"),
                }

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(resp_data).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def run_server(port: int = 8080):
    handler = ScraperHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"\n[✓] OmniScrape Studio running at: http://localhost:{port}")
        print("    Press Ctrl+C to stop the server.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
