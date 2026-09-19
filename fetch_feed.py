import os
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

raw_users = os.getenv("TIKTOK_USERS", "")
if raw_users.strip():
    TARGET_USERS = [u.strip().lstrip("@") for u in raw_users.split(",") if u.strip()]
else:
    TARGET_USERS = ["chengaming54"]

def apply_stealth(page):
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        return
    except Exception:
        pass
    try:
        from playwright_stealth import Stealth
        Stealth().apply_stealth_sync(page.context)
    except Exception:
        pass

def generate_rss_xml(username: str, videos: list[dict]) -> str:
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:media": "http://search.yahoo.com/mrss/"})
    channel = ET.SubElement(rss, "channel")
    
    ET.SubElement(channel, "title").text = f"{username} | TikTok Feed"
    ET.SubElement(channel, "link").text = f"https://www.tiktok.com/@{username}"
    ET.SubElement(channel, "description").text = f"Latest TikTok videos from @{username}"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    for v in videos:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = v["title"]
        ET.SubElement(item, "link").text = v["url"]
        ET.SubElement(item, "guid").text = v["video_id"]
        
        desc_parts = []
        if v.get("thumbnail"):
            ET.SubElement(item, "media:content", attrib={"url": v["thumbnail"], "medium": "image"})
            desc_parts.append(f'<img src="{v["thumbnail"]}" />')
        if v.get("title"):
            desc_parts.append(f'<p>{v["title"]}</p>')
            
        ET.SubElement(item, "description").text = "".join(desc_parts)
            
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")

def scrape_user_videos(page, username: str) -> list[dict]:
    url = f"https://www.tiktok.com/@{username}"
    intercepted_videos = []
    user_lower = username.lower()

    def handle_response(response):
        url_lower = response.url.lower()
        if "recommend" in url_lower or "related" in url_lower or "explore" in url_lower:
            return
        if "item_list" in url_lower or "itemlist" in url_lower:
            try:
                data = response.json()
                items = data.get("itemList", [])
                for item in items:
                    author_obj = item.get("author")
                    if isinstance(author_obj, dict):
                        author_name = str(author_obj.get("uniqueId", "")).lower()
                        if author_name and author_name != user_lower:
                            continue
                    elif isinstance(author_obj, str) and author_obj.lower() != user_lower:
                        continue
                        
                    vid_id = str(item.get("id"))
                    title = item.get("desc", f"คลิป TikTok ใหม่ #{vid_id}")
                    cover = item.get("video", {}).get("cover", "")
                    clean_url = f"https://www.tiktok.com/@{username}/video/{vid_id}"
                    intercepted_videos.append({
                        "video_id": vid_id,
                        "url": clean_url,
                        "title": title.split("\n")[0] if "\n" in title else title,
                        "thumbnail": cover
                    })
            except Exception:
                pass

    page.on("response", handle_response)

    print(f"[{username}] Navigating to {url}...")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
        
    try:
        page.wait_for_selector("[data-e2e='user-post-item'], [data-e2e='user-post-item-list']", timeout=5000)
    except Exception:
        pass

    try:
        page.evaluate("window.scrollBy(0, 500)")
    except Exception:
        pass
    page.wait_for_timeout(2000)

    print(f"[{username}] Page title: '{page.title()}' | URL: {page.url}")

    if intercepted_videos:
        print(f"[{username}] Intercepted {len(intercepted_videos)} author-verified videos from network API")
        return intercepted_videos[:10]

    try:
        script_element = page.locator("script#__UNIVERSAL_DATA_FOR_REHYDRATION__").first
        if script_element.count() > 0:
            raw_text = script_element.inner_text()
            if raw_text:
                data = json.loads(raw_text)
                default_scope = data.get("__DEFAULT_SCOPE__", {})
                detail = default_scope.get("webapp.user-detail", {})
                item_list = detail.get("itemList", [])
                rehydration_videos = []
                for item in item_list:
                    author_obj = item.get("author")
                    if isinstance(author_obj, dict):
                        author_name = str(author_obj.get("uniqueId", "")).lower()
                        if author_name and author_name != user_lower:
                            continue
                    vid_id = str(item.get("id"))
                    title = item.get("desc", f"คลิป TikTok ใหม่ #{vid_id}")
                    cover = item.get("video", {}).get("cover", "")
                    clean_url = f"https://www.tiktok.com/@{username}/video/{vid_id}"
                    rehydration_videos.append({
                        "video_id": vid_id,
                        "url": clean_url,
                        "title": title.split("\n")[0] if "\n" in title else title,
                        "thumbnail": cover
                    })
                if rehydration_videos:
                    print(f"[{username}] Found {len(rehydration_videos)} author-verified videos in rehydration script")
                    return rehydration_videos[:10]
    except Exception as e:
        print(f"[{username}] Rehydration check error: {e}")

    videos = []
    user_pattern = re.compile(rf'/@?{re.escape(username)}/video/(\d+)', re.IGNORECASE)
    
    target_selectors = [
        "[data-e2e='user-post-item'] a[href*='/video/']",
        "[data-e2e='user-post-item-list'] a[href*='/video/']",
        f"a[href*='/@{username}/video/']",
        f"a[href*='/{username}/video/']",
        "a[href*='/video/']"
    ]
    links = []
    for sel in target_selectors:
        found = page.locator(sel).all()
        if found:
            links = found
            break

    print(f"[{username}] Found {len(links)} candidate DOM video links")
    seen_ids = set()
    
    for link in links:
        href = link.get_attribute("href") or ""
        match = user_pattern.search(href)
        if not match:
            # Check if link is inside user-post-item and href has /video/(\d+)
            fallback_match = re.search(r'/video/(\d+)', href)
            if fallback_match and "/@" not in href:
                video_id = fallback_match.group(1)
            else:
                continue
        else:
            video_id = match.group(1)

        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        
        thumbnail = None
        try:
            img = link.locator("img").first
            if img.count() > 0:
                thumbnail = img.get_attribute("src")
        except Exception:
            thumbnail = None
            
        title = link.inner_text().strip() or f"คลิป TikTok ใหม่ #{video_id}"
        clean_title = title.split("\n")[0] if "\n" in title else title
        clean_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
        
        videos.append({
            "video_id": video_id,
            "url": clean_url,
            "title": clean_title,
            "thumbnail": thumbnail
        })
        if len(videos) >= 10:
            break
            
    return videos

def main():
    os.makedirs("feeds", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="th-TH",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        apply_stealth(page)
        
        for user in TARGET_USERS:
            try:
                videos = scrape_user_videos(page, user)
                if videos:
                    xml_data = generate_rss_xml(user, videos)
                    feed_path = f"feeds/{user}.xml"
                    with open(feed_path, "w", encoding="utf-8") as f:
                        f.write(xml_data)
                    print(f"Successfully generated feed for {user} ({len(videos)} videos) -> {feed_path}")
                else:
                    print(f"No videos found for {user}")
            except Exception as e:
                print(f"Error scraping {user}: {e}")
                
        browser.close()

if __name__ == "__main__":
    main()
