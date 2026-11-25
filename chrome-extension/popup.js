const API_BASE = "http://127.0.0.1:8000";

const loading = document.getElementById('loading');
const videoContainer = document.getElementById('videoContainer');
const errorArea = document.getElementById('errorArea');
const thumbImg = document.getElementById('thumbImg');
const durationTag = document.getElementById('durationTag');
const videoTitle = document.getElementById('videoTitle');
const videoAuthor = document.getElementById('videoAuthor');
const qualitySelect = document.getElementById('qualitySelect');
const downloadBtn = document.getElementById('downloadBtn');
const progressArea = document.getElementById('progressArea');
const progressFill = document.getElementById('progressFill');
const speedTxt = document.getElementById('speedTxt');
const pctTxt = document.getElementById('pctTxt');
const etaTxt = document.getElementById('etaTxt');
const stateTxt = document.getElementById('stateTxt');
const openWebBtn = document.getElementById('openWebBtn');

let activeUrl = "";
let pollTimer = null;

openWebBtn.addEventListener('click', () => {
  chrome.tabs.create({ url: API_BASE });
});

async function init() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url) {
      showError("No active web page detected.");
      return;
    }
    activeUrl = tab.url;

    // Call local engine
    const res = await fetch(`${API_BASE}/api/info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: activeUrl, use_chrome_cookies: true })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Could not detect video on this tab.");
    }

    const json = await res.json();
    const info = json.data;

    loading.style.display = 'none';
    videoContainer.style.display = 'block';

    videoTitle.textContent = info.title;
    videoAuthor.textContent = `${info.uploader} • ${info.extractor}`;
    durationTag.textContent = info.duration_string || "00:00";
    if (info.thumbnail) {
      thumbImg.src = info.thumbnail;
    }

    // Direct preview video player if stream url available
    if (info.preview_stream_url) {
      const previewArea = document.getElementById('previewArea');
      previewArea.innerHTML = `<video src="${info.preview_stream_url}" controls style="width:100%;height:100%;"></video>`;
    }

  } catch (err) {
    loading.style.display = 'none';
    showError(err.message || "Ensure the Downloader server is running.");
  }
}

downloadBtn.addEventListener('click', async () => {
  if (!activeUrl) return;

  downloadBtn.disabled = true;
  downloadBtn.textContent = "Starting high-speed download...";
  progressArea.style.display = 'block';

  try {
    const res = await fetch(`${API_BASE}/api/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: activeUrl,
        quality: qualitySelect.value,
        use_chrome_cookies: true
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);

    const jobId = data.job_id;
    pollProgress(jobId);
  } catch (err) {
    showError(err.message);
    downloadBtn.disabled = false;
    downloadBtn.textContent = "⚡ Fast Download Video";
  }
});

function pollProgress(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/progress/${jobId}`);
      if (!res.ok) return;
      const job = await res.json();

      if (job.status === 'downloading') {
        const p = job.progress || {};
        const pct = p.percent || 0;
        progressFill.style.width = pct + '%';
        pctTxt.textContent = Math.round(pct) + '%';
        speedTxt.textContent = `Speed: ${p.speed_str || '--'}`;
        etaTxt.textContent = `ETA: ${p.eta_str || '--'}`;
        stateTxt.textContent = p.message || 'Downloading...';
      } else if (job.status === 'completed') {
        clearInterval(pollTimer);
        progressFill.style.width = '100%';
        pctTxt.textContent = '100%';
        stateTxt.textContent = '✓ Saved to Downloads!';
        downloadBtn.disabled = false;
        downloadBtn.textContent = "✓ Download Finished!";
      } else if (job.status === 'failed') {
        clearInterval(pollTimer);
        showError(job.error || "Download failed");
        downloadBtn.disabled = false;
        downloadBtn.textContent = "⚡ Retry Download";
      }
    } catch (e) {
      console.error(e);
    }
  }, 700);
}

function showError(msg) {
  errorArea.textContent = msg;
  errorArea.style.display = 'block';
}

init();
