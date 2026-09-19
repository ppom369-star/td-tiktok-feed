# td-tiktok-feed

Standalone TikTok RSS XML Feed Engine powered by GitHub Actions and Playwright. Designed to provide static, 0MB-RAM RSS feeds for ChenBot / `td-discord-bot`.

## Architecture
- **Runner:** GitHub Actions (Public Repository - Unlimited Minutes)
- **Scraper:** Headless Chromium + `playwright-stealth`
- **Schedule:** Every 10 minutes (`*/10 * * * *`) + Manual `workflow_dispatch`
- **Output:** Static RSS 2.0 XML files in `feeds/<username>.xml` served directly via GitHub Raw CDN

## Feed URLs
Once the workflow runs, access the feed via:
```
https://raw.githubusercontent.com/ppom369-star/td-tiktok-feed/main/feeds/<username>.xml
```
Example for `@chengaming54`:
```
https://raw.githubusercontent.com/ppom369-star/td-tiktok-feed/main/feeds/chengaming54.xml
```

## Adding More Accounts
By default, the script tracks `chengaming54`. To track additional TikTok accounts without changing code:
1. Go to repository **Settings** -> **Secrets and variables** -> **Actions** -> **Variables**.
2. Create a variable named `TIKTOK_USERS`.
3. Set value as comma-separated usernames (e.g. `chengaming54,user2,user3`).

## GitHub Actions Permission Setup
Ensure GitHub Actions has permission to commit generated feeds:
1. Go to **Settings** -> **Actions** -> **General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Click **Save**.