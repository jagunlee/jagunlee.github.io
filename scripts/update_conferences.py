#!/usr/bin/env python3
"""Update conference dates from WikiCFP, then fall back to official sites.

The script is intentionally conservative: it keeps existing values whenever a
new page is ambiguous, and never replaces a confirmed value with a lower-
confidence guess. WikiCFP requests are throttled to respect its crawler policy.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data.json"
DATA_JS_PATH = ROOT / "data.js"
CONFIG_PATH = ROOT / "conference_sources.json"
REPORT_PATH = ROOT / ".update-report.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 "
    "CG-Conference-Timeline/1.0"
)
DATE_FIELDS = (
    "abstract",
    "submission",
    "notification",
    "cameraReady",
    "conferenceStart",
    "conferenceEnd",
)
AGGREGATOR_DOMAINS = {
    "wikicfp.com",
    "www.wikicfp.com",
    "dblp.org",
    "researchr.org",
    "conferencealerts.com",
    "allconferencealert.com",
    "call4paper.com",
    "easychair.org",
    "paperdigest.org",
    "10times.com",
    "conferenceindex.org",
    "linkedin.com",
    "facebook.com",
    "x.com",
    "twitter.com",
}
MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

LABEL_PATTERNS: dict[str, tuple[str, ...]] = {
    "abstract": (
        r"abstract\s+(?:registration|submission)?\s*(?:deadline|due)?",
        r"abstracts?\s+due",
    ),
    "submission": (
        r"(?:full\s+)?paper\s+submission\s*(?:deadline|due)?",
        r"submission\s+deadline",
        r"papers?\s+due",
        r"deadline\s+for\s+(?:paper\s+)?submission",
    ),
    "notification": (
        r"notification\s*(?:of\s+acceptance)?\s*(?:date|deadline|due)?",
        r"acceptance\s+notification",
        r"author\s+notification",
        r"decision\s+notification",
    ),
    "cameraReady": (
        r"camera[- ]ready\s*(?:deadline|due|version)?",
        r"final\s+(?:paper|version|manuscript)\s*(?:deadline|due)?",
        r"final\s+submission",
    ),
    "conference": (
        r"conference\s+dates?",
        r"symposium\s+dates?",
        r"workshop\s+dates?",
        r"event\s+dates?",
        r"dates?\s+of\s+(?:the\s+)?conference",
        r"^when\b",
    ),
    "location": (r"^location\b", r"^venue\b", r"^where\b"),
}


@dataclass
class FetchResult:
    url: str
    text: str
    content_type: str


@dataclass
class Candidate:
    source_type: str
    source_url: str
    official_url: str | None = None
    wikicfp_url: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    location: str | None = None
    confidence: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class HttpClient:
    def __init__(
        self,
        wikicfp_delay: float,
        *,
        wikicfp_connect_timeout: float = 4.0,
        wikicfp_read_timeout: float = 8.0,
        wikicfp_attempts: int = 1,
        wikicfp_failure_threshold: int = 1,
        general_connect_timeout: float = 8.0,
        general_read_timeout: float = 15.0,
        general_attempts: int = 2,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        self.wikicfp_delay = wikicfp_delay
        self.wikicfp_connect_timeout = wikicfp_connect_timeout
        self.wikicfp_read_timeout = wikicfp_read_timeout
        self.wikicfp_attempts = max(1, wikicfp_attempts)
        self.wikicfp_failure_threshold = max(1, wikicfp_failure_threshold)
        self.general_connect_timeout = general_connect_timeout
        self.general_read_timeout = general_read_timeout
        self.general_attempts = max(1, general_attempts)
        self.last_wikicfp_request = 0.0
        self.wikicfp_failures = 0
        self.wikicfp_disabled = False
        self.wikicfp_disable_reason: str | None = None
        self.cache: dict[str, FetchResult | None] = {}

    def _disable_wikicfp(self, reason: str) -> None:
        if self.wikicfp_disabled:
            return
        self.wikicfp_disabled = True
        self.wikicfp_disable_reason = reason
        logging.warning(
            "WikiCFP is unavailable; skipping all remaining WikiCFP requests in this run "
            "and continuing with official-site discovery. Reason: %s",
            reason,
        )

    def get(self, url: str, *, timeout: int | float | tuple[float, float] | None = None) -> FetchResult | None:
        url = normalize_url(url)
        if url in self.cache:
            return self.cache[url]

        wiki = is_wikicfp(url)
        if wiki and self.wikicfp_disabled:
            logging.info("Skipping WikiCFP request because the circuit breaker is open: %s", url)
            self.cache[url] = None
            return None

        if wiki:
            wait = self.wikicfp_delay - (time.monotonic() - self.last_wikicfp_request)
            if wait > 0:
                time.sleep(wait)
            request_timeout = timeout or (self.wikicfp_connect_timeout, self.wikicfp_read_timeout)
            attempts = self.wikicfp_attempts
        else:
            request_timeout = timeout or (self.general_connect_timeout, self.general_read_timeout)
            attempts = self.general_attempts

        for attempt in range(attempts):
            try:
                response = self.session.get(url, timeout=request_timeout, allow_redirects=True)
                if wiki:
                    self.last_wikicfp_request = time.monotonic()
                if response.status_code == 429:
                    if wiki:
                        self.wikicfp_failures += 1
                        self._disable_wikicfp("HTTP 429 rate limit")
                        break
                    time.sleep(5 * (attempt + 1))
                    continue
                response.raise_for_status()
                result = FetchResult(
                    url=response.url,
                    text=response.text,
                    content_type=response.headers.get("content-type", ""),
                )
                self.cache[url] = result
                return result
            except requests.RequestException as exc:
                if wiki:
                    self.last_wikicfp_request = time.monotonic()
                    self.wikicfp_failures += 1
                logging.warning("Fetch failed (%s/%s) %s: %s", attempt + 1, attempts, url, exc)
                if wiki and self.wikicfp_failures >= self.wikicfp_failure_threshold:
                    self._disable_wikicfp(str(exc))
                    break
                if attempt + 1 < attempts:
                    time.sleep(2 * (attempt + 1))

        self.cache[url] = None
        return None


def normalize_url(url: str) -> str:
    url = html.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    return url.split("#", 1)[0]


def is_wikicfp(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("wikicfp.com")


def domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def normalized_text(value: str) -> str:
    value = html.unescape(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def token_overlap(a: str, b: str) -> float:
    stop = {"the", "of", "on", "and", "for", "in", "international", "conference", "symposium", "workshop"}
    aa = {x for x in normalized_text(a).split() if x not in stop and len(x) > 2}
    bb = {x for x in normalized_text(b).split() if x not in stop and len(x) > 2}
    return len(aa & bb) / max(1, len(aa))


def acronym_present(text: str, acronym: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(acronym)}(?![A-Za-z0-9])", text, re.I))


def contains_date_signal(text: str) -> bool:
    return bool(
        re.search(MONTH_PATTERN, text, re.I)
        or re.search(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b", text)
        or re.search(r"\b\d{1,2}[-/.]\d{1,2}[-/.]20\d{2}\b", text)
    )


def iso(d: datetime | date) -> str:
    return d.strftime("%Y-%m-%d")


def unique_dates(values: Iterable[datetime]) -> list[datetime]:
    result: list[datetime] = []
    seen: set[str] = set()
    for value in values:
        key = iso(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def month_number(value: str) -> int | None:
    return MONTHS.get(value.lower().rstrip("."))


def inferred_year(month: int, year_hint: int, allowed_years: set[int] | None) -> int:
    if not allowed_years:
        return year_hint
    if len(allowed_years) == 1:
        return next(iter(allowed_years))
    # For CFP deadlines without an explicit year, Sep-Dec commonly belong to
    # the year before the conference; other months usually belong to the event year.
    previous = year_hint - 1
    if month >= 9 and previous in allowed_years:
        return previous
    if year_hint in allowed_years:
        return year_hint
    return max(allowed_years)


def safe_datetime(year: int, month: int, day: int) -> datetime | None:
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def extract_dates(text: str, year_hint: int, allowed_years: set[int] | None = None) -> list[datetime]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text or not contains_date_signal(text):
        return []

    hits: list[tuple[float, datetime]] = []

    def add_hit(position: float, year: int, month: int, day: int) -> None:
        if allowed_years is not None and year not in allowed_years:
            return
        if allowed_years is None and not (year_hint - 1 <= year <= year_hint + 1):
            return
        value = safe_datetime(year, month, day)
        if value:
            hits.append((position, value))

    # ISO dates.
    for match in re.finditer(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text):
        add_hit(match.start(), int(match.group(1)), int(match.group(2)), int(match.group(3)))

    # Month-name ranges: June 17-19, 2026.
    same_month_re = re.compile(
        rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|—|to)\s*"
        rf"(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(20\d{{2}}))?\b",
        re.I,
    )
    for match in same_month_re.finditer(text):
        month = month_number(match.group(1))
        if not month:
            continue
        year = int(match.group(4)) if match.group(4) else inferred_year(month, year_hint, allowed_years)
        add_hit(match.start(), year, month, int(match.group(2)))
        add_hit(match.start() + 0.1, year, month, int(match.group(3)))

    # Cross-month ranges: June 30 - July 2, 2026.
    cross_month_re = re.compile(
        rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:-|–|—|to)\s*"
        rf"({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(20\d{{2}}))?\b",
        re.I,
    )
    for match in cross_month_re.finditer(text):
        month1 = month_number(match.group(1))
        month2 = month_number(match.group(3))
        if not month1 or not month2:
            continue
        year2 = int(match.group(5)) if match.group(5) else inferred_year(month2, year_hint, allowed_years)
        year1 = year2 - 1 if month1 > month2 else year2
        add_hit(match.start(), year1, month1, int(match.group(2)))
        add_hit(match.start() + 0.1, year2, month2, int(match.group(4)))

    # Month day, year (year optional).
    month_first_re = re.compile(
        rf"\b({MONTH_PATTERN})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(20\d{{2}}))?\b",
        re.I,
    )
    for match in month_first_re.finditer(text):
        month = month_number(match.group(1))
        if not month:
            continue
        year = int(match.group(3)) if match.group(3) else inferred_year(month, year_hint, allowed_years)
        add_hit(match.start(), year, month, int(match.group(2)))

    # Day month year (European style).
    day_first_re = re.compile(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN})\.?(?:,?\s*(20\d{{2}}))?\b",
        re.I,
    )
    for match in day_first_re.finditer(text):
        month = month_number(match.group(2))
        if not month:
            continue
        year = int(match.group(3)) if match.group(3) else inferred_year(month, year_hint, allowed_years)
        add_hit(match.start(), year, month, int(match.group(1)))

    # Numeric US-style dates. If the first component is >12, interpret it as day/month.
    for match in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})[/.](20\d{2})\b", text):
        first, second, year = map(int, match.groups())
        month, day = (second, first) if first > 12 else (first, second)
        add_hit(match.start(), year, month, day)

    hits.sort(key=lambda item: item[0])
    result: list[datetime] = []
    seen: set[str] = set()
    for _, value in hits:
        key = iso(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def page_blocks(soup: BeautifulSoup) -> list[str]:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    result: list[str] = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "p", "li", "tr", "dt", "dd"]):
        value = " ".join(tag.get_text(" ", strip=True).split())
        if 2 <= len(value) <= 800 and value not in result:
            result.append(value)
    if len(result) < 10:
        result.extend(x.strip() for x in soup.get_text("\n", strip=True).splitlines() if 2 <= len(x.strip()) <= 800)
    return result


def find_context_dates(
    blocks: list[str], patterns: tuple[str, ...], year: int, *, conference: bool = False
) -> tuple[list[datetime], str | None]:
    allowed = {year} if conference else {year - 1, year}
    for index, block in enumerate(blocks):
        if not any(re.search(pattern, block, re.I) for pattern in patterns):
            continue
        context = " | ".join(blocks[index : min(len(blocks), index + 3)])
        dates = extract_dates(context, year, allowed)
        if dates:
            return dates, context
    return [], None


def choose_deadline(dates: list[datetime], context: str | None) -> datetime | None:
    if not dates:
        return None
    if context and re.search(r"extend(?:ed|sion)|new\s+deadline", context, re.I):
        return max(dates)
    return dates[0]


def extract_labeled_rows(soup: BeautifulSoup) -> dict[str, str]:
    rows: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in tr.find_all(["th", "td"])]
        if len(cells) >= 2 and 0 < len(cells[0]) < 80:
            rows[normalized_text(cells[0])] = " ".join(cells[1:])
    return rows


def row_value(rows: dict[str, str], *labels: str) -> str | None:
    for key, value in rows.items():
        if any(label in key for label in labels):
            return value
    return None


def score_wikicfp_candidate(text: str, conf: dict[str, Any], year: int) -> float:
    score = 0.0
    if str(year) not in text:
        return -100.0
    score += 20
    if acronym_present(text, conf["acronym"]):
        score += 45
    overlap = max(token_overlap(alias, text) for alias in [conf["name"], *conf.get("aliases", [])])
    score += 35 * overlap
    if overlap < 0.15 and not acronym_present(text, conf["acronym"]):
        score -= 100
    return score


def search_wikicfp(client: HttpClient, settings: dict[str, Any], conf: dict[str, Any], year: int) -> str | None:
    queries = [f'{conf["acronym"]} {year}', f'{conf["name"]} {year}']
    templates = settings.get("searchUrls") or [settings["searchUrl"]]
    for query in queries:
        for template in templates:
            url = template.format(query=quote_plus(query))
            result = client.get(url)
            if not result:
                # A failed WikiCFP request may open the circuit breaker. In that case,
                # trying the second hostname/protocol in the same run adds no value.
                if client.wikicfp_disabled:
                    return None
                continue
            soup = BeautifulSoup(result.text, "html.parser")
            candidates: list[tuple[float, str]] = []
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"]
                if "event.showcfp" not in href:
                    continue
                row = anchor.find_parent("tr")
                context = row.get_text(" ", strip=True) if row else anchor.get_text(" ", strip=True)
                score = score_wikicfp_candidate(context, conf, year)
                candidates.append((score, urljoin(result.url, href)))
            if candidates:
                score, best = max(candidates, key=lambda x: x[0])
                if score >= 55:
                    return best
    return None


def external_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, anchor["href"]))
        if not href.startswith(("http://", "https://")):
            continue
        label = " ".join(anchor.get_text(" ", strip=True).split())
        output.append((href, label))
    return output


def official_link_score(url: str, label: str, conf: dict[str, Any], year: int) -> float:
    host = domain(url)
    if host in AGGREGATOR_DOMAINS or host.endswith("wikicfp.com"):
        return -100
    text = f"{url} {label}"
    score = 0.0
    official_domains = conf.get("officialDomains", [])
    if any(host == d or host.endswith("." + d) for d in official_domains):
        score += 60
    if acronym_present(text, conf["acronym"]):
        score += 18
    if str(year) in text:
        score += 18
    score += 25 * max(token_overlap(alias, text) for alias in [conf["name"], *conf.get("aliases", [])])
    if re.search(r"cfp|call[-_/ ]for[-_/ ]papers|important[-_/ ]dates", text, re.I):
        score += 8
    return score


def parse_wikicfp_event(client: HttpClient, event_url: str, conf: dict[str, Any], year: int) -> Candidate | None:
    result = client.get(event_url)
    if not result:
        return None
    soup = BeautifulSoup(result.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    page_text = soup.get_text(" ", strip=True)
    if score_wikicfp_candidate(f"{title} {page_text[:1000]}", conf, year) < 40:
        return None

    rows = extract_labeled_rows(soup)
    blocks = page_blocks(soup)
    candidate = Candidate("wikicfp", result.url, wikicfp_url=result.url, notes=["WikiCFP exact acronym/year match"])

    when = row_value(rows, "when")
    if when:
        dates = extract_dates(when, year, {year})
        if dates:
            candidate.values["conferenceStart"] = iso(dates[0])
            candidate.values["conferenceEnd"] = iso(dates[-1])
            candidate.confidence["conferenceStart"] = 0.82
            candidate.confidence["conferenceEnd"] = 0.82

    where = row_value(rows, "where")
    if where and normalized_text(where) not in {"n a", "tbd", "online"}:
        candidate.location = where.strip()
        candidate.confidence["location"] = 0.78

    deadline = row_value(rows, "submission deadline", "deadline")
    if deadline:
        dates = extract_dates(deadline, year, {year - 1, year})
        chosen = choose_deadline(dates, deadline)
        if chosen:
            candidate.values["submission"] = iso(chosen)
            candidate.confidence["submission"] = 0.84

    for field_name in ("abstract", "notification", "cameraReady"):
        dates, context = find_context_dates(blocks, LABEL_PATTERNS[field_name], year)
        chosen = choose_deadline(dates, context)
        if chosen:
            candidate.values[field_name] = iso(chosen)
            candidate.confidence[field_name] = 0.78

    links = external_links(soup, result.url)
    ranked = sorted(
        ((official_link_score(url, label, conf, year), url) for url, label in links),
        reverse=True,
    )
    if ranked and ranked[0][0] >= 35:
        candidate.official_url = ranked[0][1]
    return candidate


def mutate_year_url(url: str, year: int) -> str | None:
    if re.search(r"20\d{2}", url):
        return re.sub(r"20\d{2}", str(year), url)
    return None


def unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc:
        value = parse_qs(parsed.query).get("uddg", [""])[0]
        if value:
            return unquote(value)
    return url


def duckduckgo_search(client: HttpClient, conf: dict[str, Any], year: int) -> list[tuple[str, str]]:
    query = f'"{conf["acronym"]} {year}" "{conf["name"]}" conference official'
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    result = client.get(url)
    if not result:
        return []
    soup = BeautifulSoup(result.text, "html.parser")
    output: list[tuple[str, str]] = []
    for anchor in soup.select("a.result__a, .result a[href]"):
        href = unwrap_duckduckgo_url(normalize_url(urljoin(result.url, anchor.get("href", ""))))
        label = anchor.get_text(" ", strip=True)
        if href.startswith("http"):
            output.append((href, label))
    return output[:12]


def candidate_urls_from_existing(conference: dict[str, Any], conf: dict[str, Any], year: int) -> list[str]:
    urls: list[str] = [conf.get("seriesHomepage", ""), conference.get("homepage", "")]
    for edition in conference.get("editions", []):
        if edition.get("year") == year:
            urls.append(edition.get("source", ""))
        for raw in (edition.get("source", ""), conference.get("homepage", "")):
            mutated = mutate_year_url(raw, year) if raw else None
            if mutated:
                urls.append(mutated)
    return list(dict.fromkeys(normalize_url(x) for x in urls if x))


def crawl_seed_links(client: HttpClient, seed_url: str, conf: dict[str, Any], year: int) -> list[tuple[str, str]]:
    result = client.get(seed_url)
    if not result or "html" not in result.content_type.lower():
        return []
    soup = BeautifulSoup(result.text, "html.parser")
    output: list[tuple[str, str]] = []
    for url, label in external_links(soup, result.url):
        text = f"{url} {label}"
        if str(year) in text or acronym_present(text, conf["acronym"]):
            output.append((url, label))
    return output[:20]


def validate_official_page(client: HttpClient, url: str, conf: dict[str, Any], year: int) -> tuple[float, FetchResult | None]:
    if domain(url) in AGGREGATOR_DOMAINS or is_wikicfp(url):
        return -100, None
    result = client.get(url)
    if not result or "html" not in result.content_type.lower():
        return -100, result
    soup = BeautifulSoup(result.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headings = " ".join(x.get_text(" ", strip=True) for x in soup.find_all(["h1", "h2", "h3"])[:12])
    text = f"{result.url} {title} {headings}"
    score = official_link_score(result.url, text, conf, year)
    if str(year) not in text and not re.search(str(year), soup.get_text(" ", strip=True)[:10000]):
        score -= 10
    return score, result


def discover_official_page(
    client: HttpClient,
    conference: dict[str, Any],
    conf: dict[str, Any],
    year: int,
    preferred_url: str | None,
) -> FetchResult | None:
    candidates: list[tuple[float, str]] = []
    if preferred_url:
        candidates.append((100, preferred_url))

    seeds = candidate_urls_from_existing(conference, conf, year)
    for url in seeds:
        candidates.append((official_link_score(url, url, conf, year), url))
    for seed in seeds[:3]:
        for url, label in crawl_seed_links(client, seed, conf, year):
            candidates.append((official_link_score(url, label, conf, year), url))

    # Search the open web only when WikiCFP/series pages did not provide a strong edition URL.
    if not candidates or max(score for score, _ in candidates) < 55:
        for url, label in duckduckgo_search(client, conf, year):
            candidates.append((official_link_score(url, label, conf, year), url))

    seen: set[str] = set()
    for _, url in sorted(candidates, reverse=True):
        url = normalize_url(url)
        if url in seen:
            continue
        seen.add(url)
        score, result = validate_official_page(client, url, conf, year)
        if result and score >= 35:
            return result
    return None


def clean_location(value: str) -> str | None:
    value = re.sub(r"^(location|venue|where)\s*[:\-–—]?\s*", "", value.strip(), flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" |;,-")
    if not value or len(value) > 180 or normalized_text(value) in {"tbd", "to be determined", "n a", "online"}:
        return None
    if contains_date_signal(value) and len(value.split()) < 4:
        return None
    return value


def parse_official_page(result: FetchResult, conf: dict[str, Any], year: int) -> Candidate:
    soup = BeautifulSoup(result.text, "html.parser")
    blocks = page_blocks(soup)
    candidate = Candidate("official", result.url, official_url=result.url, notes=["Official-page fallback/cross-check"])

    for field_name in ("abstract", "submission", "notification", "cameraReady"):
        dates, context = find_context_dates(blocks, LABEL_PATTERNS[field_name], year)
        chosen = choose_deadline(dates, context)
        if chosen:
            candidate.values[field_name] = iso(chosen)
            candidate.confidence[field_name] = 0.93

    dates, context = find_context_dates(blocks, LABEL_PATTERNS["conference"], year, conference=True)
    if dates:
        candidate.values["conferenceStart"] = iso(dates[0])
        candidate.values["conferenceEnd"] = iso(dates[-1])
        candidate.confidence["conferenceStart"] = 0.91
        candidate.confidence["conferenceEnd"] = 0.91

    for block in blocks:
        if any(re.search(pattern, block, re.I) for pattern in LABEL_PATTERNS["location"]):
            location = clean_location(block)
            if location:
                candidate.location = location
                candidate.confidence["location"] = 0.88
                break
    return candidate


def merge_candidates(wiki: Candidate | None, official: Candidate | None) -> Candidate | None:
    if not wiki and not official:
        return None
    base = copy.deepcopy(wiki or official)
    assert base is not None
    if wiki and official:
        base.source_type = "official+wikicfp"
        base.source_url = official.source_url
        base.official_url = official.official_url
        base.wikicfp_url = wiki.wikicfp_url or wiki.source_url
        base.notes.extend(official.notes)
        for key, value in official.values.items():
            base.values[key] = value
            base.confidence[key] = official.confidence.get(key, 0.9)
        if official.location:
            base.location = official.location
            base.confidence["location"] = official.confidence.get("location", 0.88)
    return base


def field_is_estimated(edition: dict[str, Any], field_name: str) -> bool:
    return field_name in edition.get("estimated", [])


def plausible(field_name: str, value: str, year: int) -> bool:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False
    if field_name in {"conferenceStart", "conferenceEnd"}:
        return parsed.year == year
    return parsed.year in {year - 1, year}


def apply_candidate(
    conference: dict[str, Any], year: int, candidate: Candidate, changes: list[dict[str, Any]], conflicts: list[dict[str, Any]]
) -> bool:
    editions = conference.setdefault("editions", [])
    edition = next((item for item in editions if item.get("year") == year), None)
    if edition is None:
        if not ({"submission", "conferenceStart"} & candidate.values.keys()):
            return False
        edition = {"year": year, "location": "미정"}
        editions.append(edition)

    changed = False
    estimated = set(edition.get("estimated", []))
    for field_name, new_value in candidate.values.items():
        if not plausible(field_name, new_value, year):
            continue
        old_value = edition.get(field_name)
        confidence = candidate.confidence.get(field_name, 0.0)
        can_replace = old_value is None or field_name in estimated or confidence >= 0.9
        if old_value != new_value and can_replace:
            edition[field_name] = new_value
            estimated.discard(field_name)
            changes.append({
                "conference": conference["acronym"], "year": year, "field": field_name,
                "old": old_value, "new": new_value, "source": candidate.source_url,
            })
            changed = True
        elif old_value != new_value and old_value is not None:
            conflicts.append({
                "conference": conference["acronym"], "year": year, "field": field_name,
                "kept": old_value, "found": new_value, "source": candidate.source_url,
            })

    if candidate.location:
        old_location = edition.get("location")
        confidence = candidate.confidence.get("location", 0.0)
        if old_location in {None, "미정", "TBD"} or confidence >= 0.88:
            if old_location != candidate.location:
                edition["location"] = candidate.location
                changes.append({
                    "conference": conference["acronym"], "year": year, "field": "location",
                    "old": old_location, "new": candidate.location, "source": candidate.source_url,
                })
                changed = True

    source_url = candidate.official_url or candidate.source_url
    if source_url and edition.get("source") != source_url:
        # Source-only changes are useful but do not overwrite a known official source with WikiCFP.
        existing_source = edition.get("source", "")
        if not existing_source or is_wikicfp(existing_source) or candidate.official_url:
            edition["source"] = source_url
            changed = True
    edition["sourceType"] = candidate.source_type
    if candidate.source_type.startswith("official") and candidate.source_url:
        edition["officialSource"] = candidate.source_url
    if candidate.wikicfp_url:
        edition["wikicfpSource"] = candidate.wikicfp_url

    if estimated:
        edition["estimated"] = sorted(estimated)
    else:
        edition.pop("estimated", None)
    editions.sort(key=lambda item: item.get("year", 0))
    return changed


def target_years(conf: dict[str, Any], existing: dict[str, Any], horizon: int) -> list[int]:
    current = date.today().year
    years = set(range(current, current + horizon))
    years.update(int(x["year"]) for x in existing.get("editions", []) if int(x["year"]) >= current - 1)
    parity = conf.get("years")
    if parity == "odd":
        years = {year for year in years if year % 2 == 1}
    elif parity == "even":
        years = {year for year in years if year % 2 == 0}
    return sorted(years)


def write_dataset(data: dict[str, Any]) -> None:
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    DATA_JS_PATH.write_text(
        "window.CONFERENCE_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )


def run(args: argparse.Namespace) -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    original = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    data = copy.deepcopy(original)
    conference_map = {item["acronym"]: item for item in data["conferences"]}
    wiki_settings = config.get("wikicfp", {})
    http_settings = config.get("http", {})
    client = HttpClient(
        float(wiki_settings.get("minimumDelaySeconds", 5.2)),
        wikicfp_connect_timeout=float(wiki_settings.get("connectTimeoutSeconds", 4)),
        wikicfp_read_timeout=float(wiki_settings.get("readTimeoutSeconds", 8)),
        wikicfp_attempts=int(wiki_settings.get("maxAttempts", 1)),
        wikicfp_failure_threshold=int(wiki_settings.get("failureThreshold", 1)),
        general_connect_timeout=float(http_settings.get("connectTimeoutSeconds", 8)),
        general_read_timeout=float(http_settings.get("readTimeoutSeconds", 15)),
        general_attempts=int(http_settings.get("maxAttempts", 2)),
    )

    changes: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for conf in config["conferences"]:
        conference = conference_map.get(conf["acronym"])
        if not conference:
            failures.append({"conference": conf["acronym"], "error": "Missing from data.json"})
            continue
        for year in target_years(conf, conference, int(config.get("horizonYears", 3))):
            logging.info("Checking %s %s", conf["acronym"], year)
            try:
                event_url = search_wikicfp(client, config["wikicfp"], conf, year)
                wiki = parse_wikicfp_event(client, event_url, conf, year) if event_url else None
                official_result = discover_official_page(
                    client, conference, conf, year, wiki.official_url if wiki else None
                )
                official = parse_official_page(official_result, conf, year) if official_result else None
                candidate = merge_candidates(wiki, official)
                if candidate:
                    apply_candidate(conference, year, candidate, changes, conflicts)
                else:
                    failures.append({
                        "conference": conf["acronym"], "year": year,
                        "error": "No validated WikiCFP or official page found; existing data kept",
                    })
            except Exception as exc:  # keep the daily job resilient per conference
                logging.exception("Failed while checking %s %s", conf["acronym"], year)
                failures.append({"conference": conf["acronym"], "year": year, "error": str(exc)})

    # Compare content before changing the public 'updated' date.
    before_compare = copy.deepcopy(original)
    after_compare = copy.deepcopy(data)
    before_compare.pop("updated", None)
    after_compare.pop("updated", None)
    meaningful_change = before_compare != after_compare
    if meaningful_change:
        data["updated"] = date.today().isoformat()
        write_dataset(data)

    report = {
        "checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "meaningfulChange": meaningful_change,
        "changes": changes,
        "conflictsKept": conflicts,
        "failures": failures,
        "wikicfpStatus": {
            "disabledForThisRun": client.wikicfp_disabled,
            "failureCount": client.wikicfp_failures,
            "reason": client.wikicfp_disable_reason,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.strict and failures:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Return a non-zero status when any lookup fails")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
