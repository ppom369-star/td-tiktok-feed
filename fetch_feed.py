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

def generate_rss_xml(username: str, videos: list[dict], avatar_url: str | None = None) -> str:
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:media": "http://search.yahoo.com/mrss/"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = f"{username} | TikTok Feed"
    ET.SubElement(channel, "link").text = f"https://www.tiktok.com/@{username}"
    ET.SubElement(channel, "description").text = f"Latest TikTok videos from @{username}"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    if avatar_url:
        image_el = ET.SubElement(channel, "image")
        ET.SubElement(image_el, "url").text = avatar_url
        ET.SubElement(image_el, "title").text = f"{username} | TikTok Feed"
        ET.SubElement(image_el, "link").text = f"https://www.tiktok.com/@{username}"

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

def extract_avatar_from_user_obj(user_obj: dict) -> str | None:
    if not isinstance(user_obj, dict):
        return None
    for key in ("avatarLarger", "avatarMedium", "avatarThumb"):
        val = user_obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None

def extract_avatar_from_dict(data: dict, username: str) -> str | None:
    if not isinstance(data, dict):
        return None
    user_lower = username.lower()

    user_module = data.get("UserModule")
    if isinstance(user_module, dict):
        users = user_module.get("users")
        if isinstance(users, dict):
            direct = users.get(username) or users.get(user_lower)
            avatar = extract_avatar_from_user_obj(direct)
            if avatar:
                return avatar
            for u_obj in users.values():
                if isinstance(u_obj, dict) and str(u_obj.get("uniqueId", "")).lower() == user_lower:
                    avatar = extract_avatar_from_user_obj(u_obj)
                    if avatar:
                        return avatar

    default_scope = data.get("__DEFAULT_SCOPE__")
    if isinstance(default_scope, dict):
        user_detail = default_scope.get("webapp.user-detail")
        if isinstance(user_detail, dict):
            user_info = user_detail.get("userInfo")
            if isinstance(user_info, dict):
                avatar = extract_avatar_from_user_obj(user_info.get("user"))
                if avatar:
                    return avatar
            item_list = user_detail.get("itemList")
            if isinstance(item_list, list):
                for item in item_list:
                    if not isinstance(item, dict):
                        continue
                    author_obj = item.get("author")
                    if isinstance(author_obj, dict):
                        unique_id = str(author_obj.get("uniqueId", "")).lower()
                        if not unique_id or unique_id == user_lower:
                            avatar = extract_avatar_from_user_obj(author_obj)
                            if avatar:
                                return avatar

    user_info_top = data.get("userInfo")
    if isinstance(user_info_top, dict):
        avatar = extract_avatar_from_user_obj(user_info_top.get("user"))
        if avatar:
            return avatar

    item_module = data.get("ItemModule")
    if isinstance(item_module, dict):
        for item in item_module.values():
            if not isinstance(item, dict):
                continue
            author_obj = item.get("author")
            if isinstance(author_obj, dict):
                unique_id = str(author_obj.get("uniqueId", "")).lower()
                if not unique_id or unique_id == user_lower:
                    avatar = extract_avatar_from_user_obj(author_obj)
                    if avatar:
                        return avatar

    return None

def extract_avatar_from_page(page, username: str) -> str | None:
    try:
        script_payloads = page.evaluate("""() => {
            const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
            return el && el.textContent ? [el.textContent] : [];
        }""")
        for payload in script_payloads:
            try:
                data = json.loads(payload)
                avatar = extract_avatar_from_dict(data, username)
                if avatar:
                    return avatar
            except Exception:
                pass
    except Exception:
        pass

    avatar_selectors = [
        "[data-e2e='user-avatar'] img",
        "img[class*='ImgAvatar']",
        "div[data-e2e='user-page'] img[src*='tiktokcdn']"
    ]
    for sel in avatar_selectors:
        try:
            img = page.locator(sel).first
            if img.count() > 0:
                src = img.get_attribute("src")
                if isinstance(src, str) and src.startswith("http"):
                    return src
        except Exception:
            pass
    return None

def sort_and_dedupe_videos(videos: list[dict], limit: int = 10) -> list[dict]:
    seen = set()
    unique = []
    for v in videos:
        vid = str(v.get("video_id", ""))
        if not vid or vid in seen:
            continue
        seen.add(vid)
        unique.append(v)
    unique.sort(
        key=lambda v: int(v["video_id"]) if str(v.get("video_id", "")).isdigit() else 0,
        reverse=True
    )
    return unique[:limit]

def extract_videos_from_dict(data: dict, username: str) -> list[dict]:
    videos = []
    user_lower = username.lower()
    
    # 1. ItemModule structure
    item_module = data.get("ItemModule")
    if isinstance(item_module, dict):
        for vid_id, item in item_module.items():
            if not isinstance(item, dict):
                continue
            author_obj = item.get("author")
            author_name = ""
            if isinstance(author_obj, dict):
                author_name = str(author_obj.get("uniqueId", "")).lower()
            elif author_obj:
                author_name = str(author_obj).lower()
            if author_name and author_name != user_lower:
                continue
            title = item.get("desc", f"คลิป TikTok ใหม่ #{vid_id}")
            cover = item.get("video", {}).get("cover", "") or item.get("video", {}).get("originCover", "")
            clean_url = f"https://www.tiktok.com/@{username}/video/{vid_id}"
            videos.append({
                "video_id": str(vid_id),
                "url": clean_url,
                "title": title.split("\n")[0] if "\n" in title else title,
                "thumbnail": cover
            })

    if videos:
        return videos

    # 2. __DEFAULT_SCOPE__ structure
    default_scope = data.get("__DEFAULT_SCOPE__", {})
    user_detail = default_scope.get("webapp.user-detail", {})
    item_list = user_detail.get("itemList", [])
    if isinstance(item_list, list):
        for item in item_list:
            if not isinstance(item, dict):
                continue
            author_obj = item.get("author")
            author_name = ""
            if isinstance(author_obj, dict):
                author_name = str(author_obj.get("uniqueId", "")).lower()
            elif author_obj:
                author_name = str(author_obj).lower()
            if author_name and author_name != user_lower:
                continue
            vid_id = str(item.get("id"))
            title = item.get("desc", f"คลิป TikTok ใหม่ #{vid_id}")
            cover = item.get("video", {}).get("cover", "") or item.get("video", {}).get("originCover", "")
            clean_url = f"https://www.tiktok.com/@{username}/video/{vid_id}"
            videos.append({
                "video_id": vid_id,
                "url": clean_url,
                "title": title.split("\n")[0] if "\n" in title else title,
                "thumbnail": cover
            })

    return videos

def parse_dom_video_links(page, username: str) -> list[dict]:
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

    seen_ids = set()
    videos = []
    for link in links:
        href = link.get_attribute("href") or ""
        match = user_pattern.search(href)
        if not match:
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
        img_alt = None
        try:
            img = link.locator("img").first
            if img.count() > 0:
                thumbnail = img.get_attribute("src")
                img_alt = img.get_attribute("alt")
        except Exception:
            thumbnail = None
            img_alt = None
            
        aria_label = link.get_attribute("aria-label") or link.get_attribute("title")
        raw_text = link.inner_text().strip()
        
        candidate_title = img_alt or aria_label
        if not candidate_title or candidate_title.isdigit() or re.match(r'^\d+(\.\d+)?[KkMm]?$', candidate_title):
            if raw_text and not raw_text.isdigit() and not re.match(r'^\d+(\.\d+)?[KkMm]?$', raw_text):
                candidate_title = raw_text
            else:
                candidate_title = f"คลิป TikTok ใหม่ #{video_id}"
                
        clean_title = candidate_title.split("\n")[0] if "\n" in candidate_title else candidate_title
        clean_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
        
        videos.append({
            "video_id": video_id,
            "url": clean_url,
            "title": clean_title,
            "thumbnail": thumbnail
        })
        if len(videos) >= 15:
            break
            
    return videos

def build_response_handler(username: str, videos_out: list[dict], avatar_state: dict):
    def handle_response(response):
        url_lower = response.url.lower()
        if "recommend" in url_lower or "related" in url_lower or "explore" in url_lower:
            return
        if "item_list" in url_lower or "itemlist" in url_lower or "user/detail" in url_lower:
            try:
                data = response.json()
                if not avatar_state.get("url"):
                    found_avatar = extract_avatar_from_dict(data, username)
                    if found_avatar:
                        avatar_state["url"] = found_avatar
                if "item_list" in url_lower or "itemlist" in url_lower:
                    parsed = extract_videos_from_dict(data, username)
                    if parsed:
                        videos_out.extend(parsed)
            except Exception:
                pass
    return handle_response

def scrape_user_videos(browser, username: str) -> tuple[list[dict], str | None]:
    url = f"https://www.tiktok.com/@{username}"
    intercepted_videos = []
    avatar_state = {"url": None}

    context = browser.new_context(
        locale="th-TH",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    apply_stealth(page)
    page.on("response", build_response_handler(username, intercepted_videos, avatar_state))

    print(f"[{username}] Navigating to {url} (Desktop)...")
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)

    try:
        cookie_selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('Allow all')",
            "[data-e2e='cookie-banner-accept']"
        ]
        for sel in cookie_selectors:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                print(f"[{username}] Clicked cookie consent banner")
                page.wait_for_timeout(1500)
                break
    except Exception:
        pass
    
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    for retry in range(2):
        refresh_btn = page.locator("button:has-text('รีเฟรช'), button:has-text('Refresh')").first
        if refresh_btn.count() > 0 and refresh_btn.is_visible():
            print(f"[{username}] Error card found! Clicking 'รีเฟรช' button (attempt {retry + 1})...")
            refresh_btn.click()
            page.wait_for_timeout(4000)
        else:
            break

    try:
        page.evaluate("window.scrollBy(0, 600)")
    except Exception:
        pass
    page.wait_for_timeout(2000)

    avatar_url = avatar_state.get("url") or extract_avatar_from_page(page, username)

    if intercepted_videos:
        unique = sort_and_dedupe_videos(intercepted_videos, limit=10)
        if unique:
            print(f"[{username}] Intercepted {len(unique)} author-verified videos from network API")
            context.close()
            return unique, avatar_url

    dom_videos = parse_dom_video_links(page, username)
    if dom_videos:
        unique_dom = sort_and_dedupe_videos(dom_videos, limit=10)
        print(f"[{username}] Found {len(unique_dom)} videos from Desktop DOM")
        context.close()
        return unique_dom, avatar_url

    try:
        page.screenshot(path=f"debug_{username}.png", full_page=True)
        with open(f"debug_{username}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception:
        pass
    context.close()

    print(f"[{username}] Desktop returned 0 videos. Attempting Mobile Emulation fallback...")
    mobile_context = browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        locale="th-TH"
    )
    mobile_page = mobile_context.new_page()
    apply_stealth(mobile_page)

    mobile_intercepted = []
    mobile_avatar_state = {"url": avatar_url}
    mobile_page.on("response", build_response_handler(username, mobile_intercepted, mobile_avatar_state))

    mobile_page.goto(url, wait_until="domcontentloaded", timeout=45000)
    mobile_page.wait_for_timeout(3000)

    try:
        mobile_page.evaluate("window.scrollBy(0, 500)")
    except Exception:
        pass
    mobile_page.wait_for_timeout(2000)

    try:
        script_payloads = mobile_page.evaluate("""() => {
            const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
            return el && el.textContent ? [el.textContent] : [];
        }""")
        for payload in script_payloads:
            try:
                data = json.loads(payload)
                if not mobile_avatar_state.get("url"):
                    mobile_avatar_state["url"] = extract_avatar_from_dict(data, username)
                parsed = extract_videos_from_dict(data, username)
                if parsed:
                    unique_rehyd = sort_and_dedupe_videos(parsed, limit=10)
                    print(f"[{username}] Found {len(unique_rehyd)} videos in Mobile Rehydration Script")
                    mobile_context.close()
                    return unique_rehyd, mobile_avatar_state.get("url")
            except Exception:
                pass
    except Exception:
        pass

    final_mobile_avatar = mobile_avatar_state.get("url") or extract_avatar_from_page(mobile_page, username)

    if mobile_intercepted:
        unique = sort_and_dedupe_videos(mobile_intercepted, limit=10)
        if unique:
            print(f"[{username}] Intercepted {len(unique)} videos in Mobile Network API")
            mobile_context.close()
            return unique, final_mobile_avatar

    mobile_dom_videos = parse_dom_video_links(mobile_page, username)
    if mobile_dom_videos:
        unique_dom = sort_and_dedupe_videos(mobile_dom_videos, limit=10)
        print(f"[{username}] Found {len(unique_dom)} videos in Mobile DOM")
        mobile_context.close()
        return unique_dom, final_mobile_avatar

    try:
        mobile_page.screenshot(path=f"debug_mobile_{username}.png")
    except Exception:
        pass

    mobile_context.close()
    return [], final_mobile_avatar

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
        
        for user in TARGET_USERS:
            try:
                videos, avatar_url = scrape_user_videos(browser, user)
                if videos:
                    xml_data = generate_rss_xml(user, videos, avatar_url=avatar_url)
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
