"""
app.py — Flask backend for the Stock Screener.

Endpoints:
  GET  /                    → serve UI
  GET  /api/tickers/<mkt>   → return ticker list for market
  POST /api/scan            → start a scan, return job_id
  GET  /api/stream/<job_id> → SSE stream of results + progress
"""

import json
import queue
import threading
import uuid
import logging
from flask import Flask, render_template, jsonify, request, Response, stream_with_context

from tickers import get_tickers
from screener import screen

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# job_id → {"queue": Queue, "market": str, "total": int, "done": int}
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()

PORT = 5050


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_scan(job_id: str, market: str, tickers: list[str]):
    """Background thread: runs screener and pushes events onto the job queue."""
    q = JOBS[job_id]["queue"]
    total = len(tickers)

    def progress(done, total):
        with JOBS_LOCK:
            JOBS[job_id]["done"] = done
        q.put({"type": "progress", "done": done, "total": total})

    results = []
    try:
        for result in screen(tickers, progress_cb=progress):
            results.append(result)
            # Sort results by score desc and push updated ranked list
            ranked = sorted(results, key=lambda r: r["score"], reverse=True)
            for rank, r in enumerate(ranked, 1):
                r["rank"] = rank
            q.put({"type": "result", "data": result, "ranked": ranked})
    except Exception as e:
        log.exception("Scan error for job %s", job_id)
        q.put({"type": "error", "message": str(e)})
    finally:
        q.put({"type": "done", "total_passed": len(results)})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tickers/<market>")
def api_tickers(market: str):
    tickers = get_tickers(market)
    if not tickers:
        return jsonify({"error": f"Unknown market: {market}"}), 404
    return jsonify({"market": market, "count": len(tickers), "tickers": tickers})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data   = request.get_json(force=True) or {}
    market = data.get("market", "").lower()
    if market not in ("nse", "nyse"):
        return jsonify({"error": "market must be 'nse' or 'nyse'"}), 400

    tickers = get_tickers(market)
    job_id  = str(uuid.uuid4())

    with JOBS_LOCK:
        JOBS[job_id] = {
            "queue":  queue.Queue(),
            "market": market,
            "total":  len(tickers),
            "done":   0,
        }

    t = threading.Thread(target=_run_scan, args=(job_id, market, tickers), daemon=True)
    t.start()
    log.info("Started scan job %s for market=%s (%d tickers)", job_id, market, len(tickers))

    return jsonify({"job_id": job_id, "total": len(tickers)})


@app.route("/api/stream/<job_id>")
def api_stream(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job_id"}), 404

    q = job["queue"]

    def generate():
        while True:
            try:
                event = q.get(timeout=60)
            except queue.Empty:
                # keep-alive ping
                yield "event: ping\ndata: {}\n\n"
                continue

            payload = json.dumps(event)
            yield f"data: {payload}\n\n"

            if event.get("type") in ("done", "error"):
                # Clean up job after a short delay
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    print(f"\n🚀  Stock Screener running at  http://localhost:{PORT}\n")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
