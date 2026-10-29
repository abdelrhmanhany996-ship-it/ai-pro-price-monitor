"""Log a compact structural summary of a page when parsing fails (no secrets, truncated)."""
import json
import logging
import re

log = logging.getLogger("aipro.diag")


def summarize(html: str, label: str) -> None:
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    log.warning("DIAG[%s] len=%d title=%r", label, len(html), (title.group(1).strip() if title else "")[:80])
    for i, m in enumerate(re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I)):
        try:
            data = json.loads(m.group(1))
            nodes = data if isinstance(data, list) else [data]
            log.warning("DIAG[%s] ld+json#%d types=%s keys=%s", label, i,
                        [str(n.get("@type")) for n in nodes if isinstance(n, dict)],
                        sorted({k for n in nodes if isinstance(n, dict) for k in n})[:15])
        except ValueError:
            log.warning("DIAG[%s] ld+json#%d invalid json", label, i)
    hits = re.findall(r".{60}(?:€|EUR|EGP|£|\$)\s?\d[\d.,]*.{20}|.{60}\"(?:price|finalPrice|minPrice|lowPrice)\"\s*:\s*[\d.\"]+.{20}", html)
    for h in hits[:8]:
        log.warning("DIAG[%s] hit: %s", label, re.sub(r"\s+", " ", h)[:170])
    log.warning("DIAG[%s] next_data=%s", label, "__NEXT_DATA__" in html)
