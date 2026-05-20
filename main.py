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


# ─── VC DATABASE ──────────────────────────────────────────────────────────────

SG_VCS_BASE = [
    {"name":"Sequoia Capital SEA","website":"https://www.sequoiacap.com","stage":["Series A","Series B","Growth"],"sectors":["Tech","Fintech","Consumer"],"fund_size":"$850M+","hq":"Singapore","hiring_interns":True},
    {"name":"Vertex Ventures SEA","website":"https://www.vertexventures.com","stage":["Seed","Series A","Series B"],"sectors":["Fintech","SaaS","Healthtech"],"fund_size":"$305M","hq":"Singapore","hiring_interns":True},
    {"name":"East Ventures","website":"https://east.vc","stage":["Seed","Series A"],"sectors":["E-commerce","Fintech","SaaS"],"fund_size":"$550M+","hq":"Singapore","hiring_interns":True},
    {"name":"Golden Gate Ventures","website":"https://goldengate.vc","stage":["Seed","Series A"],"sectors":["Marketplace","Fintech","Consumer"],"fund_size":"$100M","hq":"Singapore","hiring_interns":False},
    {"name":"Insignia Ventures Partners","website":"https://insignia.vc","stage":["Seed","Series A"],"sectors":["Fintech","SaaS","Healthtech"],"fund_size":"$516M","hq":"Singapore","hiring_interns":True},
    {"name":"Monk's Hill Ventures","website":"https://www.monkshill.com","stage":["Series A","Series B"],"sectors":["Deep Tech","SaaS","Fintech"],"fund_size":"$200M","hq":"Singapore","hiring_interns":True},
    {"name":"Jungle Ventures","website":"https://jungle.vc","stage":["Series A","Series B","Growth"],"sectors":["Consumer","Fintech","B2B SaaS"],"fund_size":"$600M+","hq":"Singapore","hiring_interns":True},
    {"name":"Wavemaker Partners","website":"https://wavemaker.vc","stage":["Seed","Series A"],"sectors":["B2B","Deep Tech","Sustainability"],"fund_size":"$165M","hq":"Singapore","hiring_interns":True},
    {"name":"500 Global SEA","website":"https://500.co","stage":["Pre-Seed","Seed"],"sectors":["Broad","Fintech","Consumer"],"fund_size":"$1.8B (global)","hq":"Singapore","hiring_interns":False},
    {"name":"Openspace Ventures","website":"https://openspace.vc","stage":["Series A","Series B"],"sectors":["Fintech","Healthtech","EdTech"],"fund_size":"$200M","hq":"Singapore","hiring_interns":True},
    {"name":"Qualgro","website":"https://qualgro.com","stage":["Series A","Series B"],"sectors":["B2B SaaS","Data","AI"],"fund_size":"$120M","hq":"Singapore","hiring_interns":False},
    {"name":"Vickers Venture Partners","website":"https://vickersventure.com","stage":["Series A","Series B","Growth"],"sectors":["Deep Tech","Biotech","AI"],"fund_size":"$1B+","hq":"Singapore","hiring_interns":False},
    {"name":"Temasek Venture","website":"https://www.temasek.com.sg","stage":["Growth","Late"],"sectors":["Broad","Sustainability","Tech"],"fund_size":"$300B+ AUM","hq":"Singapore","hiring_interns":True},
    {"name":"EDBI","website":"https://www.edbi.com","stage":["Series A","Growth"],"sectors":["Tech","Biotech","Medtech"],"fund_size":"Govt-backed","hq":"Singapore","hiring_interns":True},
    {"name":"Antler","website":"https://www.antler.co","stage":["Pre-Seed","Seed"],"sectors":["Broad","Deep Tech","Fintech"],"fund_size":"$1B+","hq":"Singapore","hiring_interns":True},
    {"name":"Saison Capital","website":"https://www.saisoncapital.com","stage":["Pre-Seed","Seed"],"sectors":["Fintech","B2B","Emerging Markets"],"fund_size":"$100M+","hq":"Singapore","hiring_interns":True},
    {"name":"gumi Cryptos Capital","website":"https://gcc.fund","stage":["Seed","Series A"],"sectors":["Web3","DeFi","Gaming"],"fund_size":"$110M","hq":"Singapore","hiring_interns":True},
    {"name":"Pavilion Capital","website":"https://www.pavilioncapital.com.sg","stage":["Growth","Buyout"],"sectors":["Broad","Consumer","Tech"],"fund_size":"$1B+","hq":"Singapore","hiring_interns":False},
]

PEOPLE_DATA = [
    {"name":"Yinglan Tan","firm":"Insignia Ventures Partners","role":"Founding Managing Partner","linkedin":"https://www.linkedin.com/in/yinglantan/","background":"Ex-Sequoia, NUS alumnus","speaker_fit":5,"coffee_chat_fit":3,"tags":["Speaker","NUS Connection","VC Thought Leader"],"note":"Very active on LinkedIn, NUS alumnus — best cold outreach angle"},
    {"name":"Vinnie Lauria","firm":"Golden Gate Ventures","role":"Managing Partner","linkedin":"https://www.linkedin.com/in/vinnielauria/","background":"Serial entrepreneur, SEA VC pioneer","speaker_fit":5,"coffee_chat_fit":4,"tags":["Speaker","SEA Pioneer","Approachable"],"note":"Frequently speaks at NUS/NTU events"},
    {"name":"Carmen Yuen","firm":"Vertex Ventures SEA","role":"General Partner","linkedin":"https://www.linkedin.com/in/carmenyuen/","background":"Ex-investment banking, early-stage specialist","speaker_fit":4,"coffee_chat_fit":4,"tags":["Speaker","Coffee Chat","Female Leader","IBD Background"],"note":"Great for students transitioning from banking to VC"},
    {"name":"Kuo-Yi Lim","firm":"Monk's Hill Ventures","role":"Co-Founder & Managing Partner","linkedin":"https://www.linkedin.com/in/kuoyilim/","background":"Ex-McKinsey, Stanford MBA","speaker_fit":4,"coffee_chat_fit":3,"tags":["Speaker","Deep Tech Focus"],"note":"Strong B2B SaaS perspective"},
    {"name":"Hian Goh","firm":"Openspace Ventures","role":"Founding Partner","linkedin":"https://www.linkedin.com/in/hiangoh/","background":"Ex-BCG, SEA VC pioneer","speaker_fit":4,"coffee_chat_fit":4,"tags":["Speaker","Coffee Chat","SEA Expert"],"note":"Approachable, known for candid advice to students"},
    {"name":"Paul Santos","firm":"Wavemaker Partners","role":"Managing Partner","linkedin":"https://www.linkedin.com/in/paulsantosph/","background":"Ex-founder, B2B/deep tech focus","speaker_fit":4,"coffee_chat_fit":4,"tags":["Coffee Chat","Deep Tech","Approachable"],"note":"Very open to NUS student outreach"},
    {"name":"Willson Cuaca","firm":"East Ventures","role":"Co-Founder & Managing Partner","linkedin":"https://www.linkedin.com/in/willsoncuaca/","background":"Pioneered Indonesia/SEA VC ecosystem","speaker_fit":5,"coffee_chat_fit":2,"tags":["Speaker","SEA Pioneer"],"note":"Best for panel discussions"},
    {"name":"Jeffrey Paine","firm":"Golden Gate Ventures","role":"Founding Partner","linkedin":"https://www.linkedin.com/in/jeffreypaine/","background":"One of SEA earliest VC investors","speaker_fit":5,"coffee_chat_fit":3,"tags":["Speaker","SEA Pioneer","Ecosystem Builder"],"note":"Great historical perspective on SEA VC"},
    {"name":"Jayesh Parekh","firm":"Jungle Ventures","role":"Co-Founder","linkedin":"https://www.linkedin.com/in/jayeshparekh/","background":"Serial entrepreneur, investor","speaker_fit":4,"coffee_chat_fit":3,"tags":["Speaker","Entrepreneur Background"],"note":"Great for founder-investor dynamic talks"},
    {"name":"Dmitry Levit","firm":"Cento Ventures","role":"General Partner","linkedin":"https://www.linkedin.com/in/dmitrylevit/","background":"Data-driven VC, publishes SEA VC reports","speaker_fit":4,"coffee_chat_fit":4,"tags":["Coffee Chat","Data/Research","Approachable"],"note":"Publishes free SEA VC data — great for research collab"},
]


@app.get("/vcs")
async def get_vcs(stage: str = "", sector: str = "", hiring: str = ""):
    vcs = [v.copy() for v in SG_VCS_BASE]
    if stage:
        vcs = [v for v in vcs if any(stage.lower() in s.lower() for s in v["stage"])]
    if sector:
        vcs = [v for v in vcs if any(sector.lower() in s.lower() for s in v["sectors"])]
    if hiring == "true":
        vcs = [v for v in vcs if v["hiring_interns"]]
    for i, v in enumerate(vcs):
        v["id"] = i + 1
    return {"count": len(vcs), "vcs": vcs, "scraped_at": datetime.utcnow().isoformat() + "Z"}


@app.get("/people")
async def get_people(tag: str = "", speaker: str = "", coffee: str = ""):
    people = PEOPLE_DATA.copy()
    if tag:
        people = [p for p in people if any(tag.lower() in t.lower() for t in p["tags"])]
    if speaker == "true":
        people = [p for p in people if p["speaker_fit"] >= 4]
    if coffee == "true":
        people = [p for p in people if p["coffee_chat_fit"] >= 4]
    return {"count": len(people), "people": people}



# ─── EVENTS & SPEAKERS (SerpApi / DuckDuckGo fallback) ───────────────────────

import os
import re

EVENT_QUERIES = [
    "Singapore venture capital networking event 2026",
    "Singapore startup investor conference 2026 speaker",
    "NUS fintech VC talk speaker Singapore 2026",
    "Singapore PE VC summit 2026",
    "SEA venture capital founder event Singapore",
]


def score_relevance(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["venture capital", " vc ", "private equity", " pe ",
                              "investment bank", "fundraising", "series a", "pitch"]):
        return "High"
    if any(k in t for k in ["startup", "fintech", "founder", "investor",
                              "entrepreneur", "accelerator", "angel", "seed"]):
        return "Medium"
    return "General"


def extract_names(text: str) -> list:
    names = []
    pats = [
        r"(?:speaker|keynote|panelist|hosted by|featuring|by)\s*:?\s*([A-Z][a-z]+ [A-Z][a-z]+)",
        r"([A-Z][a-z]+ [A-Z][a-z]+),\s*(?:Partner|Managing|General|Founder|CEO|Director|Head|VP)",
    ]
    for pat in pats:
        names.extend(re.findall(pat, text))
    return list(set(names))[:3]


async def search_duckduckgo(client: httpx.AsyncClient, query: str) -> list:
    """Scrape DuckDuckGo HTML results - no API key needed"""
    results = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        encoded = query.replace(" ", "+")
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        r = await client.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")

        for result in soup.select(".result__body, .web-result, .result")[:6]:
            title_el = result.select_one(".result__title a, .result__a, a.result__url")
            snippet_el = result.select_one(".result__snippet, .result__extract")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            href = title_el.get("href", "")
            # DuckDuckGo wraps links, extract real URL
            if "uddg=" in href:
                import urllib.parse
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = parsed.get("uddg", [href])[0]
            if title and len(title) > 5:
                results.append({"title": title, "snippet": snippet, "url": href})
    except Exception as e:
        print(f"DuckDuckGo error for '{query}': {e}")
    return results


async def search_bing(client: httpx.AsyncClient, query: str) -> list:
    """Scrape Bing search results as fallback"""
    results = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        encoded = query.replace(" ", "+")
        url = f"https://www.bing.com/search?q={encoded}&count=8"
        r = await client.get(url, headers=headers, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for li in soup.select("li.b_algo")[:6]:
            title_el = li.select_one("h2 a")
            snippet_el = li.select_one(".b_caption p, .b_snippet")
            if not title_el:
                continue
            results.append({
                "title": title_el.get_text(strip=True),
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                "url": title_el.get("href", ""),
            })
    except Exception as e:
        print(f"Bing error for '{query}': {e}")
    return results


@app.get("/events")
async def get_events():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Try DuckDuckGo first, then Bing as fallback
        ddg_tasks = [search_duckduckgo(client, q) for q in EVENT_QUERIES]
        ddg_results = await asyncio.gather(*ddg_tasks, return_exceptions=True)

        all_raw = []
        for r in ddg_results:
            if isinstance(r, list) and r:
                all_raw.extend(r)

        # If DuckDuckGo got nothing, try Bing
        if len(all_raw) < 3:
            bing_tasks = [search_bing(client, q) for q in EVENT_QUERIES[:3]]
            bing_results = await asyncio.gather(*bing_tasks, return_exceptions=True)
            for r in bing_results:
                if isinstance(r, list):
                    all_raw.extend(r)

    seen, events = set(), []
    for item in all_raw:
        url = item.get("url", "")
        title = item.get("title", "")
        key = (title[:40].lower())
        if key in seen or not title or len(title) < 8:
            continue
        seen.add(key)
        snippet = item.get("snippet", "")
        rel = score_relevance(title + " " + snippet)
        # Extract domain as source
        try:
            from urllib.parse import urlparse
            source = urlparse(url).netloc.replace("www.", "")
        except:
            source = ""
        events.append({
            "id": len(events) + 1,
            "title": title,
            "url": url,
            "snippet": snippet[:200],
            "source": source,
            "speakers": extract_names(title + " " + snippet),
            "relevance": rel,
        })

    events.sort(key=lambda x: {"High": 0, "Medium": 1, "General": 2}.get(x["relevance"], 3))
    return {
        "count": len(events),
        "events": events,
        "scraped_at": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/discover-people")
async def discover_people():
    queries = [
        "Singapore venture capital managing partner speaker 2026",
        "Singapore VC investor keynote SEA ecosystem",
        "SEA venture capital general partner interview podcast",
    ]
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [search_duckduckgo(client, q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    seen, discovered = set(), []
    for items in results:
        if not isinstance(items, list):
            continue
        for item in items:
            url = item.get("url", "")
            title = item.get("title", "")
            key = title[:40].lower()
            if key in seen or not title:
                continue
            seen.add(key)
            snippet = item.get("snippet", "")
            names = extract_names(title + " " + snippet)
            discovered.append({
                "title": title, "url": url,
                "snippet": snippet[:200],
                "possible_people": names,
            })

    return {"count": len(discovered), "results": discovered, "scraped_at": datetime.utcnow().isoformat() + "Z"}
