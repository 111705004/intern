from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from bs4 import BeautifulSoup
import asyncio
import re
from datetime import datetime, timedelta
import random

app = FastAPI(title="Finance Internship Scraper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

KEYWORDS = ["venture capital intern", "private equity intern", "investment banking intern",
            "corporate development intern", "VC analyst intern", "PE analyst intern",
            "IBD summer analyst", "M&A intern"]

LOCATIONS = ["Singapore", "Hong Kong"]

# ─── scrapers ────────────────────────────────────────────────────────────────

async def scrape_mycareers(client: httpx.AsyncClient, keyword: str) -> list[dict]:
    """MyCareersFuture.gov.sg — Singapore government jobs portal"""
    results = []
    try:
        url = (
            "https://api.mycareersfuture.gov.sg/v2/jobs/search"
            f"?search={keyword.replace(' ', '%20')}"
            "&limit=10&sortBy=new_posting_date"
        )
        r = await client.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        for job in data.get("results", []):
            results.append({
                "title": job.get("title", ""),
                "company": job.get("postedCompany", {}).get("name", ""),
                "location": "Singapore",
                "url": f"https://www.mycareersfuture.gov.sg/job/{job.get('uuid','')}",
                "source": "MyCareersFuture",
                "posted": job.get("postingDate", "")[:10] if job.get("postingDate") else "",
                "type": classify_type(job.get("title", "")),
            })
    except Exception as e:
        print(f"MyCareersFuture error: {e}")
    return results


async def scrape_linkedin_rss(client: httpx.AsyncClient, keyword: str, location: str) -> list[dict]:
    """LinkedIn public job RSS feed"""
    results = []
    try:
        url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={keyword.replace(' ', '%20')}&location={location}&start=0"
        )
        r = await client.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("li")
        for card in cards[:8]:
            title_el = card.select_one(".base-search-card__title")
            company_el = card.select_one(".base-search-card__subtitle")
            link_el = card.select_one("a.base-card__full-link")
            date_el = card.select_one("time")
            if not title_el:
                continue
            results.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "",
                "location": location,
                "url": link_el["href"].split("?")[0] if link_el else "https://linkedin.com/jobs",
                "source": "LinkedIn",
                "posted": date_el.get("datetime", "")[:10] if date_el else "",
                "type": classify_type(title_el.get_text(strip=True)),
            })
    except Exception as e:
        print(f"LinkedIn error ({keyword}/{location}): {e}")
    return results


async def scrape_efinancialcareers(client: httpx.AsyncClient, keyword: str) -> list[dict]:
    """eFinancialCareers — finance-focused job board"""
    results = []
    try:
        url = f"https://www.efinancialcareers.sg/jobs-Singapore-in-Internship.html"
        r = await client.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("article.job-item, div.job-listing, .job__details")
        for card in cards[:10]:
            title_el = card.select_one("h2 a, h3 a, .job-title a, a.job-title")
            company_el = card.select_one(".employer-name, .company-name, [data-at='job-item-employer-name']")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not any(kw.lower() in title.lower() for kw in ["intern","analyst","associate","summer"]):
                continue
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.efinancialcareers.sg" + href
            results.append({
                "title": title,
                "company": company_el.get_text(strip=True) if company_el else "",
                "location": "Singapore",
                "url": href or "https://www.efinancialcareers.sg",
                "source": "eFinancialCareers",
                "posted": "",
                "type": classify_type(title),
            })
    except Exception as e:
        print(f"eFinancialCareers error: {e}")
    return results


async def scrape_internsg(client: httpx.AsyncClient) -> list[dict]:
    """InternSG — Singapore internship portal"""
    results = []
    try:
        url = "https://www.internsg.com/jobs/?s=finance+investment"
        r = await client.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(".job-listing, .job_listing, article.type-job_listing")
        for card in cards[:10]:
            title_el = card.select_one("h3 a, h2 a, .job-title a")
            company_el = card.select_one(".company, .employer, strong")
            if not title_el:
                continue
            href = title_el.get("href", "https://internsg.com")
            results.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else "",
                "location": "Singapore",
                "url": href,
                "source": "InternSG",
                "posted": "",
                "type": classify_type(title_el.get_text(strip=True)),
            })
    except Exception as e:
        print(f"InternSG error: {e}")
    return results


def classify_type(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["venture", "vc", "seed", "startup invest"]):
        return "VC"
    if any(k in t for k in ["private equity", "pe ", "buyout", "leveraged"]):
        return "PE"
    if any(k in t for k in ["investment bank", "ibd", "m&a", "mergers", "capital markets",
                              "ecm", "dcm", "equity capital", "debt capital", "syndicate"]):
        return "IBD"
    if any(k in t for k in ["corporate dev", "corp dev", "strategy", "business development",
                              "bd intern", "strategic finance"]):
        return "Corp Dev"
    return "IBD"  # default for finance roles


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for j in jobs:
        key = (j["title"].lower()[:40], j["company"].lower()[:30])
        if key not in seen and j["title"] and j["company"]:
            seen.add(key)
            j["id"] = len(out) + 1
            out.append(j)
    return out


# ─── routes ──────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "Finance Internship Scraper API"}


@app.get("/jobs")
async def get_jobs(keyword: str = "", type_filter: str = "", location: str = ""):
    """Scrape all sources in parallel and return deduplicated jobs"""
    keywords_to_use = [keyword] if keyword else KEYWORDS[:4]  # limit for speed

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = []

        # MyCareersFuture (Singapore only)
        for kw in keywords_to_use[:3]:
            tasks.append(scrape_mycareers(client, kw))

        # LinkedIn (both SG + HK)
        for kw in keywords_to_use[:2]:
            for loc in LOCATIONS:
                tasks.append(scrape_linkedin_rss(client, kw, loc))

        # eFinancialCareers
        tasks.append(scrape_efinancialcareers(client, ""))

        # InternSG
        tasks.append(scrape_internsg(client))

        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_jobs = []
    for r in results:
        if isinstance(r, list):
            all_jobs.extend(r)

    jobs = deduplicate(all_jobs)

    # apply filters
    if type_filter:
        jobs = [j for j in jobs if j["type"].lower() == type_filter.lower()]
    if location:
        jobs = [j for j in jobs if location.lower() in j["location"].lower()]

    return {
        "count": len(jobs),
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "jobs": jobs,
    }


@app.get("/health")
def health():
    return {"status": "healthy", "time": datetime.utcnow().isoformat()}
