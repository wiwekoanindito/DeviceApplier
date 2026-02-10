from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import os
import time
from playwright.sync_api import sync_playwright, TimeoutError


# =========================
# Utilities
# =========================

def read_lines(filename):
    if not os.path.exists(filename):
        print(f"❌ Error: {filename} not found!")
        return []
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def construct_campaign_url(base_url, campaign_id):
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["campaignId"] = [campaign_id]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


# =========================
# CORE HELPERS
# =========================

def expand_brand(modal, brand):
    """Expand brand/category using chevron only."""
    try:
        row = modal.locator(
            f"div[role='treeitem'][aria-label='{brand}'][aria-expanded='false']"
        ).first

        if row.count() == 0:
            return

        chevron = row.locator("material-icon.zippy[role='button']")

        if chevron.is_visible():
            row.scroll_into_view_if_needed()
            chevron.click()
            time.sleep(0.2)
    except:
        pass


def check_model(modal, model):
    """Tick model ONLY if aria-checked=false."""
    try:
        row = modal.locator("div[role='treeitem']").filter(has_text=model).first
        if row.count() == 0:
            return False

        checkbox = row.locator("material-checkbox[role='checkbox']").first
        if checkbox.get_attribute("aria-checked") == "true":
            return False

        row.scroll_into_view_if_needed()
        row.click()
        time.sleep(0.05)
        return True
    except:
        return False


# =========================
# MAIN LOGIC
# =========================

def apply_targeting_to_campaign(page, models, campaign_id):
    print(f"\n🎯 Campaign {campaign_id}")
    page.wait_for_load_state("networkidle")

    # -------------------------
    # Navigate UI
    # -------------------------

    try:
        page.get_by_text("Additional settings").click()
        time.sleep(0.8)
    except:
        pass

    try:
        page.get_by_text("Devices", exact=True).click()
        time.sleep(0.8)
    except:
        print("⚠️ Devices section not found")

    try:
        page.locator("div[role='button']").filter(
            has_text="Device Models"
        ).first.click()
        time.sleep(1.5)
    except:
        print("❌ Device Models button not found")
        return

    # -------------------------
    # Modal
    # -------------------------

    modal = page.get_by_role("dialog", name="Choose device models")
    modal.wait_for(state="visible", timeout=10000)
    print("✅ Device Models modal opened")

    # -------------------------
    # Expand OS + Brands
    # -------------------------

    level_1 = ["Android", "iOS", "Windows Phone", "Other/Unknown", "Unknown"]

    brands = [
        "Apple", "Samsung", "Xiaomi", "OPPO", "Realme", "Vivo",
        "Infinix", "Tecno", "HUAWEI", "Google", "Sony",
        "Nokia", "Motorola", "Lenovo", "LG"
    ]

    for name in level_1 + brands:
        expand_brand(modal, name)

    # -------------------------
    # Apply Models
    # -------------------------

    applied = 0
    skipped = 0

    for model in models:
        if check_model(modal, model):
            applied += 1
        else:
            skipped += 1

    print(f"✔ Applied: {applied} | Skipped: {skipped}")

    # -------------------------
    # DONE (inside modal)
    # -------------------------

    try:
        done_btn = modal.get_by_role("button", name="Done")
        done_btn.click(force=True)
        print("✔ Clicked Done")
        time.sleep(1.5)
    except TimeoutError:
        print("❌ Failed to click Done")
        return

    # -------------------------
    # SAVE (sticky footer – FORCE)
    # -------------------------

    try:
        time.sleep(1)

        save_btn = page.get_by_role("button", name="Save")
        save_btn.click(force=True)

        print("✔ Clicked Save")
        time.sleep(3)
    except Exception as e:
        page.screenshot(path=f"save_failed_{campaign_id}.png", full_page=True)
        print(f"❌ Failed to click Save: {e}")
        return


# =========================
# MAIN
# =========================

def main():
    models = read_lines("models.txt")
    campaigns = read_lines("campaigns.txt")

    if not models or not campaigns:
        print("❌ Missing models.txt or campaigns.txt")
        return

    template_url = input("🔗 Paste Campaign Settings URL: ").strip()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            "chrome_user_data",
            headless=False,
            args=["--start-maximized"],
            viewport=None
        )

        page = context.pages[0]
        page.goto(template_url)

        input("🛑 Log in, then press ENTER...")

        for i, cid in enumerate(campaigns, 1):
            print(f"\n[{i}/{len(campaigns)}] Campaign {cid}")
            page.goto(construct_campaign_url(template_url, cid))
            apply_targeting_to_campaign(page, models, cid)

        print("\n✅ ALL CAMPAIGNS DONE")
        input("Press ENTER to exit")
        context.close()


if __name__ == "__main__":
    main()
