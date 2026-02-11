from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import os
import time
import csv
from multiprocessing import Process, Lock
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError


# =========================
# CONFIG
# =========================
WORKERS = 3
MAX_RETRIES = 3
RESET_EVERY = 2        # hard reset page every N campaigns
PROFILE_ROOT = "chrome_user_data"
CSV_PATH = "campaign_results.csv"

csv_lock = Lock()


# =========================
# LOGGING
# =========================
def log(worker_id, msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [W{worker_id}] [{level:<5}] {msg}", flush=True)


# =========================
# CSV
# =========================
def init_master_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                "timestamp",
                "worker_id",
                "campaign_id",
                "attempt",
                "applied",
                "skipped",
                "status",
                "message"
            ])


def write_csv(row):
    with csv_lock:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)


# =========================
# UTILITIES
# =========================
def read_lines(path):
    if not os.path.exists(path):
        print(f"[MAIN][ERROR] {path} not found", flush=True)
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def construct_campaign_url(base, cid):
    parsed = urlparse(base)
    q = parse_qs(parsed.query)
    q["campaignId"] = [cid]
    return urlunparse(parsed._replace(query=urlencode(q, doseq=True)))


def chunk_list(lst, n):
    size = (len(lst) + n - 1) // n
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


# =========================
# UI HELPERS
# =========================
def expand_brand(modal, name):
    try:
        row = modal.locator(
            f"div[role='treeitem'][aria-label='{name}'][aria-expanded='false']"
        ).first
        if row.count() == 0:
            return
        icon = row.locator("material-icon.zippy[role='button']")
        if icon.is_visible():
            row.scroll_into_view_if_needed()
            icon.click()
            time.sleep(0.2)
    except:
        pass


def check_model(modal, model):
    try:
        row = modal.locator("div[role='treeitem']").filter(has_text=model).first
        if row.count() == 0:
            return False

        checkbox = row.locator("material-checkbox[role='checkbox']").first
        if checkbox.get_attribute("aria-checked") == "true":
            return False

        row.scroll_into_view_if_needed()
        row.click()
        time.sleep(0.06)
        return True
    except:
        return False


# =========================
# CAMPAIGN CORE
# =========================
def apply_targeting(page, models, cid, worker_id):

    log(worker_id, f"Campaign {cid}")

    # DOM-ready is enough for Google Ads
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_selector("text=Additional settings", timeout=20000)

    page.get_by_text("Additional settings").click()
    page.get_by_text("Devices", exact=True).click()

    page.locator("div[role='button']").filter(
        has_text="Device Models"
    ).first.click()

    modal = page.get_by_role("dialog", name="Choose device models")
    modal.wait_for(state="visible", timeout=15000)

    log(worker_id, "Device modal opened", "OK")

    brands = [
        "Android", "iOS", "Windows Phone", "Other/Unknown", "Unknown",
        "Apple", "Samsung", "Xiaomi", "OPPO", "Realme", "Vivo",
        "Infinix", "Tecno", "HUAWEI", "Google", "Sony",
        "Nokia", "Motorola", "Lenovo", "LG"
    ]

    for b in brands:
        expand_brand(modal, b)

    applied = skipped = 0

    for m in models:
        if check_model(modal, m):
            applied += 1
        else:
            skipped += 1

    modal.get_by_role("button", name="Done").click(force=True)
    page.get_by_role("button", name="Save").click(force=True)

    log(worker_id, f"Applied={applied} Skipped={skipped}", "OK")
    log(worker_id, "Saved successfully", "OK")

    return applied, skipped


# =========================
# SAFE WRAPPER
# =========================
def safe_apply(page, models, cid, worker_id):

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            applied, skipped = apply_targeting(page, models, cid, worker_id)

            write_csv([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                worker_id,
                cid,
                attempt,
                applied,
                skipped,
                "SAVED",
                "OK"
            ])
            return

        except Exception as e:
            log(worker_id, f"Attempt {attempt} failed", "WARN")

            write_csv([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                worker_id,
                cid,
                attempt,
                "",
                "",
                "RETRY",
                type(e).__name__
            ])

            if attempt == MAX_RETRIES:
                write_csv([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    worker_id,
                    cid,
                    attempt,
                    "",
                    "",
                    "SKIPPED",
                    "MAX_RETRIES"
                ])
                log(worker_id, f"Campaign {cid} skipped", "ERROR")
                return

            time.sleep(2 * attempt)


# =========================
# WORKER
# =========================
def run_worker(worker_id, campaigns, models, template_url):

    profile = os.path.join(PROFILE_ROOT, f"worker_{worker_id}")
    os.makedirs(profile, exist_ok=True)

    log(worker_id, f"Starting worker with {len(campaigns)} campaigns")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile,
            headless=False,
            args=["--start-maximized"],
            viewport=None
        )

        page = context.pages[0]
        page.goto(template_url)

        for idx, cid in enumerate(campaigns, 1):

            # 🔁 HARD RESET TO PREVENT UI DEGRADATION
            if idx % RESET_EVERY == 0:
                log(worker_id, "Resetting page state", "INFO")
                page.goto("about:blank")
                time.sleep(2)
                page.goto(template_url)
                page.wait_for_load_state("domcontentloaded")

            page.goto(construct_campaign_url(template_url, cid))
            safe_apply(page, models, cid, worker_id)
            time.sleep(1.5)

        context.close()
        log(worker_id, "Worker finished", "DONE")


# =========================
# MAIN
# =========================
def main():
    init_master_csv()

    models = read_lines("models.txt")
    campaigns = read_lines("campaigns.txt")

    template_url = input("🔗 Paste Campaign Settings URL: ").strip()

    chunks = list(chunk_list(campaigns, WORKERS))
    procs = []

    print(f"[MAIN][INFO ] Starting {WORKERS} workers", flush=True)

    for i, chunk in enumerate(chunks):
        p = Process(
            target=run_worker,
            args=(i, chunk, models, template_url)
        )
        p.start()
        procs.append(p)

    for p in procs:
        p.join()

    print("[MAIN][OK   ] ALL CAMPAIGNS DONE", flush=True)


if __name__ == "__main__":
    main()
