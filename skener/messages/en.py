"""English catalog. Each sentence claims exactly what the Serbian one claims, no more and no less.

Pregleda ga vlasnik po tri pravila iz IT-SKENER-002 §3.3: tvrdnja mora da se proveri, svaki
broj mora da potiče iz dokaza, a broj i imenica moraju da se slažu.
"""

from __future__ import annotations


def decimal(number: float) -> str:
    """„14.9", „22", „0.1" — no trailing „.0"."""
    return f"{number:.1f}".removesuffix(".0")


def plural(number: int, forms: list[str]) -> str:
    singular, many = forms
    return singular if number == 1 else many


DECIMAL = decimal

CODES: dict[str, dict[object, str]] = {
    "kodiranje": {None: "none"},
    "uzorak": {"sitemap": "sitemap", "links": "internal links from the home page", "none": "home page only"},
}

_WEIGHT = (
    "On a slower mobile connection ({brzina} Mb/s) that takes about {sekundi} s, and many visitors "
    "do not wait that long."
)

FINDINGS: dict[str, dict] = {
    # ------------------------------------------------------------------ perf
    "perf.compression.missing": {
        "client": (
            "The server sends the page uncompressed ({kb} kB). Compression would cut the transfer to "
            "roughly a quarter, which on a slower mobile connection ({brzina} Mb/s) shortens loading "
            "by about {usteda_s} s."
        ),
        "tech": "content-encoding={kodiranje}, html_bytes={bajtova} (decoded), saving ≈ {usteda_s} s",
    },
    "perf.redirect.chain": {
        "client": (
            "Opening the home page goes through {skokova:n:redirect|redirects} before anything is "
            "shown. Each of them adds waiting time, most of all on a mobile connection."
        ),
        "tech": "redirect_chain={skokova} hops: {lanac:join: → }",
    },
    "perf.html.size": {
        "client": (
            "The home page code alone weighs {kb} kB, before images and scripts. The browser has to "
            "download and process all of it, which slows down rendering, most of all on a phone."
        ),
        "tech": "html_bytes={bajtova} > {prag_kb} kB",
    },
    "perf.page.weight": {
        "client": "The home page transfers {mb} MB. " + _WEIGHT,
        "tech": (
            "total_bytes={bajtova}, without video {mb} MB, video {video_mb} MB, requests={zahteva}, "
            "unmeasured={nemereno}, reached={reached}"
        ),
        "variants": {
            "video": {"client": "The home page transfers {mb} MB (plus {video_mb} MB of video). " + _WEIGHT}
        },
    },
    "perf.request.count": {
        "client": (
            "Opening the home page starts {zahteva:n:separate download|separate downloads}. Each one "
            "carries its own overhead, which is felt most on a mobile connection."
        ),
        "tech": "request_count={zahteva} (reached={reached})",
    },
    "perf.load.time": {
        "client": (
            "The home page needs {sekundi} s to load completely. Many visitors do not wait that long, "
            "especially on a phone."
        ),
        "tech": "load_ms={load_ms}, reached={reached}",
    },
    "perf.img.oversized": {
        "client": (
            "The site sends images much larger than they are displayed — about {kb} kB of unnecessary "
            "transfer on the first visit."
        ),
        "tech": (
            "{broj_slika} images with ratio > {prag_odnosa}, estimated excess {kb} kB, "
            "unmeasured {nemereno}"
        ),
    },
    "qa.console.errors": {
        "client": (
            "The home page has {greske:n:JavaScript error|JavaScript errors}. Part of the page may "
            "therefore not work as intended."
        ),
        "tech": "console errors={greske}, warnings={upozorenja}",
    },
    # ------------------------------------------------------------------- seo
    "seo.canonical.missing": {
        "client": (
            "The home page does not tell Google which address is its official one. When the same "
            "content exists at several addresses (with and without www, with ad parameters), Google "
            "picks which one to show on its own — and it can pick the wrong one."
        ),
        "tech": "{stranica}: missing <link rel=canonical>",
    },
    "seo.canonical.duplicate": {
        "client": (
            "Several checked pages of the site ({stranica}) report the same address to Google as "
            "their official one ({canonical}). Google may therefore treat them as copies of a single "
            "page and leave them out of search results."
        ),
        "tech": (
            "canonical_normalized == {canonical} on {stranica} pages "
            "from {grupa_putanja} path groups (sample: {uzorak})"
        ),
    },
    "seo.title.missing": {
        "client": (
            "The home page has no title. The browser tab therefore shows a bare part of the address, "
            "and Google makes up a title from the page content in its results."
        ),
        "tech": "{stranica}: <title> empty or missing (length {duzina_naslova})",
    },
    "seo.title.duplicate": {
        "client": (
            "Different pages of the site have the same title (“{naslov}”). In Google results they look "
            "like {stranica:n:copy|copies} of the same page, so Google has a harder time choosing "
            "which one to show."
        ),
        "tech": "identical normalized <title> on {stranica} pages from {grupa_putanja} path groups",
    },
    "seo.description.missing": {
        "client": (
            "The home page has no short description for Google. Google then picks text from the page "
            "to show below the title, and that can be part of the menu or the cookie notice."
        ),
        "tech": "{stranica}: missing <meta name=description> (length {duzina_opisa})",
    },
    "seo.description.duplicate": {
        "client": (
            "Different pages of the site have the same description in Google results. A visitor "
            "coming from search therefore cannot tell the {stranica:n:page|pages} apart."
        ),
        "tech": "identical normalized meta description on {stranica} pages from {grupa_putanja} path groups",
    },
    "seo.h1.missing": {
        "client": (
            "The page has no main heading (h1). Headings are one of the signals Google uses to "
            "understand what a page is about, and screen reader users navigate the page by them."
        ),
        "tech": "h1_count == {h1_count} (measured in the browser, reached={reached})",
    },
    "seo.h1.multiple": {
        "client": (
            "The page has {h1_count:n:main heading|main headings} (h1) instead of one. Screen reader "
            "users then find it harder to recognize the main topic of the page."
        ),
        "tech": "h1_count == {h1_count} > {prag}",
    },
    # ---------------------------------------------------------------- social
    "social.og.title.missing": {
        "client": (
            "When someone shares a link to the site in a message or on Facebook, there is no prepared "
            "title for the link preview, so platforms use the plain page title or the address itself."
        ),
        "tech": "{stranica}: missing og:title (og tags in total: {og_oznaka_ukupno})",
    },
    "social.og.description.missing": {
        "client": (
            "When a link to the site is shared, platforms have no prepared description, so they pick "
            "text from the page themselves or show none at all."
        ),
        "tech": "{stranica}: missing og:description (og tags in total: {og_oznaka_ukupno})",
    },
    "social.og.image.missing": {
        "client": (
            "A shared link to the site has no prepared image. In Viber and WhatsApp groups, where "
            "recommendations are often sent, a link without an image easily goes unnoticed."
        ),
        "tech": "{stranica}: missing og:image (og tags in total: {og_oznaka_ukupno})",
    },
    # ------------------------------------------------------------------ i18n
    "i18n.lang.missing": {
        "client": (
            "Nowhere in the site's code does it say what language the site is in. Screen readers, "
            "used by blind and visually impaired visitors, therefore do not know which pronunciation "
            "to read it with."
        ),
        "tech": "{stranica}: <html> without a lang attribute",
    },
    "i18n.lang.invalid": {
        "client": (
            "The site is marked in its code with “{lang}”, which does not denote any language. "
            "For screen readers that is the same as having no language tag at all."
        ),
        "tech": '{stranica}: lang="{lang}" is not a usable BCP-47 code',
    },
    "i18n.lang.mismatch": {
        "client": (
            "The site content is in Serbian, but its code marks it as “{lang}”. Screen readers, used "
            "by blind and visually impaired visitors, therefore pronounce the Serbian text by the "
            "rules of that language, which makes it hard to understand."
        ),
        "tech": (
            '{stranica}: lang="{lang}", content detected as {prepoznat_jezik} '
            "(Cyrillic {cirilica_udeo}, diacritics {dijakritici_udeo}, {duzina_teksta} characters)"
        ),
    },
    # ----------------------------------------------------------------- infra
    "infra.sitemap.missing": {
        "client": (
            "The site has no page map (sitemap). Google therefore finds new and deeper pages only "
            "through links, more slowly, and may not find pages that no link leads to at all."
        ),
        "tech": "sitemap status={status}, urls={broj_urlova}",
    },
    "infra.robots.missing": {
        "client": (
            "The site has no robots.txt. Nothing breaks because of it, but it is the file every "
            "search engine asks for first, and its absence is a sign that the site was not set up "
            "for search."
        ),
        "tech": "robots.txt status={status}",
    },
    "infra.soft404": {
        "client": (
            "For an address that does not exist, the site returns an ordinary page instead of an "
            "error message — both made-up addresses we checked returned status {status}. Search "
            "engines therefore have a harder time telling real pages from nonexistent ones and "
            "spend their crawl of the site on empty addresses."
        ),
        "tech": "both probes status={status}, similarity to the home page {slicnost}",
    },
    "infra.tls.invalid": {
        "client": (
            "The site's certificate is not valid, so the browser shows visitors a red warning before "
            "they enter the site. Most of them turn back at that page."
        ),
        "tech": "TLS error: {greska}",
    },
    "infra.dns.unresolved": {
        "client": (
            "The domain does not open at all — there is no record linking it to a server. "
            "For visitors and for Google, the site currently does not exist."
        ),
        "tech": "DNS does not resolve: {detalj}",
    },
    # ------------------------------------------------------------------ a11y
    "a11y.img.alt.missing": {
        "client": (
            "{bez_alta} of {ukupno:n:image|images} have no text description (alt). Visitors who use "
            "screen readers do not learn what is on them, and Google has less data for image search."
        ),
        "tech": (
            "images_without_alt_attr={bez_alta}/{ukupno} (share {udeo}), "
            "images_empty_alt={prazan_alt} deliberately not counted, unmeasured={nemereno}"
        ),
    },
}

TEXT: dict[str, str] = {
    "page_title": "Skener — report",
    "heading": "Website scanner — report",
    "run_of": "Run of {generated} · tool version {version}",
    "card_domains": "Domains",
    "card_scanned": "Scanned",
    "card_partial": "Partial",
    "card_failed": "Failed",
    "card_level2": "On level 2",
    "card_excluded": "Excluded on request",
    "card_duration": "Duration",
    "ranked": "Ranked domains",
    "ranked_note": (
        "The order is by the single worst finding, and only then by the total: a site with\n"
        "one disaster is a better lead than a site with ten small issues."
    ),
    "col_domain": "Domain",
    "col_industry": "Industry",
    "col_score": "Score",
    "col_worst": "Worst finding",
    "col_findings": "Findings",
    "col_level2": "Level 2",
    "col_status": "Status",
    "yes": "yes",
    "no": "no",
    "by_domain": "By domain",
    "assumption_html": (
        "<b>Assumption for the loading time estimate:</b> effective speed\n"
        "{speed} Mb/s ({mb_per_s} MB/s, a slow 4G connection) plus {overhead} s of overhead\n"
        "time. A number you send to a client is one you must be able to defend, and a number without\n"
        "a stated assumption is not."
    ),
    "read_only_html": (
        "The tool reads, it never writes. It does not scan ports, attempt logins, look for\n"
        "vulnerabilities, or touch paths that <code>robots.txt</code> disallows."
    ),
    "summary_meta": "{industry} · score {score} ·\nworst {worst} · {findings:n:finding|findings}",
    "copy_draft": "Copy email draft",
    "copied": "Copied ✓",
    "no_findings": "No findings — the site is in order on the checked points.",
    "unknowns": "Could not be checked ({count})",
    "escalated_because": "Sent to level 2 because: ",
    "finding_meta": "· level {level} · {weight} points",
    "draft_clean": "I did not find any significant problems on {domain}.",
    "draft_opening": "Hello,\n\nI reviewed the site {domain} and noticed the following:\n\n",
    "draft_closing": (
        "\n\nIf you are interested, I can send a detailed review with a suggestion of what to fix first.\n"
    ),
    "severity_critical": "CRITICAL",
    "severity_high": "HIGH",
    "severity_medium": "MEDIUM",
    "severity_low": "LOW",
}
