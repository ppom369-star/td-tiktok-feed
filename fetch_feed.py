import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

raw_users = os.getenv("TIKTOK_USERS", "")
if raw_users.strip():
    TARGET_USERS = [u.strip().lstrip("@") for u in raw_users.split(",") if u.strip()]
else:
    TARGET_USERS = ["chengaming54"]

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
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    page.evaluate("window.scrollBy(0, 500)")
    page.wait_for_timeout(1000)
    
    videos = []
    links = page.locator("a[href*='/video/']").all()
    seen_ids = set()
    
    for link in links:
        href = link.get_attribute("href") or ""
        match = re.search(r'/video/(\d+)', href)
        if not match:
            continue
        video_id = match.group(1)
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        
        img = link.locator("img").first
        thumbnail = img.get_attribute("src") if img.count() > 0 else None
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
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="th-TH"
        )
        page = context.new_page()
        stealth_sync(page)
        
        for user in TARGET_USERS:
            try:
                videos = scrape_user_videos(page, user)
                if videos:
                    xml_data = generate_rss_xml(user, videos)
                    with open(f"feeds/{user}.xml", "w", encoding="utf-8") as f:
                        f.write(xml_data)
                    print(f"Successfully generated feed for {user} ({len(videos)} videos)")
            except Exception as e:
                print(f"Error scraping {user}: {e}")
                
        browser.close()

if __name__ == "__main__":
    main()
