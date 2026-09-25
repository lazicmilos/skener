"""Srpski katalog. Rečenica ide pravo u mejl, pa mora biti tačna i pravilna (§3.5)."""

from __future__ import annotations


def decimalni(broj: float) -> str:
    """„14,9", „22", „0,1" — decimalni zarez i bez „,0", kako se piše u mejlu (BUG-015)."""
    return f"{broj:.1f}".removesuffix(".0").replace(".", ",")


def oblik(broj: int, jednina: str, paukal: str, mnozina: str) -> str:
    """Srpski bira oblik po poslednjoj cifri, osim za 11–14: jednina posle 1 (ali ne
    11), paukal posle 2–4 (ali ne 12–14), množina za sve ostalo. Oblike daje šablon,
    jer zavise i od padeža: „ima 21 grešku", ali „od 21 slike".
    """
    if broj % 10 == 1 and broj % 100 != 11:
        return jednina
    if 2 <= broj % 10 <= 4 and not 12 <= broj % 100 <= 14:
        return paukal
    return mnozina


def sa_brojem(broj: int, jednina: str, paukal: str, mnozina: str) -> str:
    """„1 stranica", „3 stranice", „5 stranica", „21 stranica", „12 stranica"."""
    return f"{broj} {oblik(broj, jednina, paukal, mnozina)}"


def plural(broj: int, oblici: list[str]) -> str:
    return oblik(broj, *oblici)


DECIMAL = decimalni

# Tehnički kodovi iz dokaza, onako kako se čitaju u rečenici.
CODES: dict[str, dict[object, str]] = {
    "kodiranje": {None: "nema"},
    "uzorak": {"sitemap": "sitemap", "links": "interni linkovi sa početne", "none": "samo početna"},
}

_TEZINA = (
    "Na sporijoj mobilnoj vezi ({brzina} Mb/s) za to je potrebno oko {sekundi} s, a mnogi posetioci "
    "ne čekaju toliko."
)

FINDINGS: dict[str, dict] = {
    # ------------------------------------------------------------------ perf
    "perf.compression.missing": {
        "client": (
            "Server šalje stranicu nesažetu ({kb} kB). Sažimanje bi prenos smanjilo na otprilike "
            "četvrtinu, što na sporijoj mobilnoj vezi ({brzina} Mb/s) skraćuje učitavanje za oko "
            "{usteda_s} s."
        ),
        "tech": "content-encoding={kodiranje}, html_bytes={bajtova} (dekodirano), ušteda ≈ {usteda_s} s",
    },
    "perf.redirect.chain": {
        "client": (
            "Otvaranje početne strane prolazi kroz {skokova} preusmerenja pre nego što se nešto "
            "prikaže. Svako od njih dodaje čekanje, najviše na mobilnoj vezi."
        ),
        "tech": "redirect_chain={skokova} skokova: {lanac:join: → }",
    },
    "perf.html.size": {
        "client": (
            "Sam kod početne strane teži {kb} kB, pre slika i skripti. Pretraživač mora sve to "
            "da preuzme i obradi, što usporava prikaz, najviše na telefonu."
        ),
        "tech": "html_bytes={bajtova} > {prag_kb} kB",
    },
    "perf.page.weight": {
        "client": "Početna strana prenosi {mb} MB. " + _TEZINA,
        "tech": (
            "total_bytes={bajtova}, bez videa {mb} MB, video {video_mb} MB, zahteva={zahteva}, "
            "nemereno={nemereno}, reached={reached}"
        ),
        "variants": {
            "video": {"client": "Početna strana prenosi {mb} MB (video dodatno {video_mb} MB). " + _TEZINA}
        },
    },
    "perf.request.count": {
        "client": (
            "Otvaranje početne strane pokreće "
            "{zahteva:n:odvojeno preuzimanje|odvojena preuzimanja|odvojenih preuzimanja}. Svako ima "
            "svoju režiju, što se najviše oseti na mobilnoj vezi."
        ),
        "tech": "request_count={zahteva} (reached={reached})",
    },
    "perf.load.time": {
        "client": (
            "Početnoj strani treba {sekundi} s da se do kraja učita. Mnogi posetioci ne čekaju "
            "toliko, naročito na telefonu."
        ),
        "tech": "load_ms={load_ms}, reached={reached}",
    },
    "perf.img.oversized": {
        "client": (
            "Sajt šalje slike znatno veće nego što se prikazuju — oko {kb} kB nepotrebnog prenosa "
            "pri prvoj poseti."
        ),
        "tech": "{broj_slika} slika sa ratio > {prag_odnosa}, procenjen višak {kb} kB, nemereno {nemereno}",
    },
    "qa.console.errors": {
        "client": (
            "Na početnoj strani ima {greske:n:JavaScript grešku|JavaScript greške|JavaScript grešaka}. "
            "Deo stranice zato možda ne radi kako treba."
        ),
        "tech": "console errors={greske}, warnings={upozorenja}",
    },
    # ------------------------------------------------------------------- seo
    "seo.canonical.missing": {
        "client": (
            "Početna strana ne govori Google-u koja joj je zvanična adresa. Kad isti sadržaj "
            "postoji na više adresa (sa www i bez, sa parametrima iz reklama), Google sam bira "
            "koju će prikazati — i ume da izabere pogrešnu."
        ),
        "tech": "{stranica}: nedostaje <link rel=canonical>",
    },
    "seo.canonical.duplicate": {
        "client": (
            "Više proverenih stranica sajta ({stranica}) prijavljuje Google-u istu adresu kao "
            "zvaničnu ({canonical}). Google ih zato može smatrati kopijama jedne stranice i "
            "izostaviti iz pretrage."
        ),
        "tech": (
            "canonical_normalized == {canonical} na {stranica} stranica "
            "iz {grupa_putanja} grupa putanja (uzorak: {uzorak})"
        ),
    },
    "seo.title.missing": {
        "client": (
            "Početna strana nema naslov. U kartici pretraživača zato stoji goli deo adrese, a "
            "Google u rezultatima sam smišlja naslov iz sadržaja strane."
        ),
        "tech": "{stranica}: <title> prazan ili nedostaje (dužina {duzina_naslova})",
    },
    "seo.title.duplicate": {
        "client": (
            "Različite stranice sajta imaju isti naslov („{naslov}”). U Google rezultatima "
            "izgledaju kao {stranica:n:kopija|kopije|kopija} iste stranice, pa Google teže bira "
            "koju da prikaže."
        ),
        "tech": "identičan normalizovan <title> na {stranica} stranica iz {grupa_putanja} grupa putanja",
    },
    "seo.description.missing": {
        "client": (
            "Početna strana nema kratak opis za Google. Google tada sam bira tekst sa strane za "
            "prikaz ispod naslova, a to ume da bude deo menija ili obaveštenja o kolačićima."
        ),
        "tech": "{stranica}: nedostaje <meta name=description> (dužina {duzina_opisa})",
    },
    "seo.description.duplicate": {
        "client": (
            "Različite stranice sajta imaju isti opis u Google rezultatima. Posetilac iz pretrage "
            "zato ne vidi razliku između {stranica:n:stranice|stranice|stranica}."
        ),
        "tech": "identičan normalizovan meta opis na {stranica} stranica iz {grupa_putanja} grupa putanja",
    },
    "seo.h1.missing": {
        "client": (
            "Stranica nema glavni naslov (h1). Naslovi su jedan od signala po kojima Google "
            "razume o čemu je strana, a korisnici čitača ekrana se po njima kreću kroz stranicu."
        ),
        "tech": "h1_count == {h1_count} (mereno u browseru, reached={reached})",
    },
    "seo.h1.multiple": {
        "client": (
            "Stranica ima {h1_count:n:glavni naslov|glavna naslova|glavnih naslova} (h1) umesto "
            "jednog. Korisnicima čitača ekrana je tada teže da prepoznaju glavnu temu strane."
        ),
        "tech": "h1_count == {h1_count} > {prag}",
    },
    # ---------------------------------------------------------------- social
    "social.og.title.missing": {
        "client": (
            "Kada neko podeli link sajta u poruci ili na Facebook-u, nema pripremljenog naslova "
            "za pregled linka, pa platforme uzimaju običan naslov strane ili samu adresu."
        ),
        "tech": "{stranica}: nedostaje og:title (ukupno og oznaka: {og_oznaka_ukupno})",
    },
    "social.og.description.missing": {
        "client": (
            "Kad se link sajta podeli, platforme nemaju pripremljen opis, pa same biraju tekst sa "
            "strane ili ne prikazuju nijedan."
        ),
        "tech": "{stranica}: nedostaje og:description (ukupno og oznaka: {og_oznaka_ukupno})",
    },
    "social.og.image.missing": {
        "client": (
            "Podeljen link sajta nema pripremljenu sliku. U Viber i WhatsApp grupama, gde se "
            "preporuke često šalju, link bez slike lako prođe neprimećeno."
        ),
        "tech": "{stranica}: nedostaje og:image (ukupno og oznaka: {og_oznaka_ukupno})",
    },
    # ------------------------------------------------------------------ i18n
    "i18n.lang.missing": {
        "client": (
            "U kodu sajta nigde ne piše na kom je jeziku. Čitači ekrana, koje koriste slepi i "
            "slabovidi posetioci, zato ne znaju kojim izgovorom da ga čitaju."
        ),
        "tech": "{stranica}: <html> bez lang atributa",
    },
    "i18n.lang.invalid": {
        "client": (
            "Sajt je u kodu označen oznakom „{lang}”, koja ne označava nijedan jezik. "
            "Za čitače ekrana je to isto kao da oznake nema."
        ),
        "tech": '{stranica}: lang="{lang}" nije upotrebljiv BCP-47 kod',
    },
    "i18n.lang.mismatch": {
        "client": (
            "Sadržaj sajta je na srpskom, ali je u kodu označen kao „{lang}”. Čitači ekrana, koje "
            "koriste slepi i slabovidi posetioci, zato srpski tekst izgovaraju po pravilima tog "
            "jezika, pa je teško razumljiv."
        ),
        "tech": (
            '{stranica}: lang="{lang}", sadržaj prepoznat kao {prepoznat_jezik} '
            "(ćirilica {cirilica_udeo}, dijakritici {dijakritici_udeo}, {duzina_teksta} znakova)"
        ),
    },
    # ----------------------------------------------------------------- infra
    "infra.sitemap.missing": {
        "client": (
            "Sajt nema mapu stranica (sitemap). Google zato nove i dublje stranice pronalazi samo "
            "preko linkova, sporije, a stranice do kojih ne vodi nijedan link može i da ne pronađe."
        ),
        "tech": "sitemap status={status}, urls={broj_urlova}",
    },
    "infra.robots.missing": {
        "client": (
            "Sajt nema robots.txt. Ništa se time ne lomi, ali je to fajl koji svaki pretraživač "
            "prvo traži, i njegov izostanak je znak da se sajt nije podešavao za pretragu."
        ),
        "tech": "robots.txt status={status}",
    },
    "infra.soft404": {
        "client": (
            "Na nepostojeću adresu sajt vraća običnu stranicu umesto poruke o grešci — obe "
            "proverene izmišljene adrese vratile su status {status}. Pretraživači zato teže "
            "razlikuju prave stranice od nepostojećih i troše obilazak sajta na prazne adrese."
        ),
        "tech": "obe sonde status={status}, sličnost sa početnom {slicnost}",
    },
    "infra.tls.invalid": {
        "client": (
            "Sertifikat sajta nije valjan, pa pretraživač posetiocima prikazuje crveno upozorenje "
            "pre nego što uđu na sajt. Većina se na toj strani vrati nazad."
        ),
        "tech": "TLS greška: {greska}",
    },
    "infra.dns.unresolved": {
        "client": (
            "Domen se uopšte ne otvara — ne postoji zapis koji ga povezuje sa serverom. "
            "Za posetioca i za Google sajt trenutno ne postoji."
        ),
        "tech": "DNS ne razrešava: {detalj}",
    },
    # ------------------------------------------------------------------ a11y
    "a11y.img.alt.missing": {
        "client": (
            "{bez_alta} od {ukupno:n:slike|slike|slika} nema tekstualni opis (alt). Posetioci koji "
            "koriste čitače ekrana ne saznaju šta je na njima, a Google ima manje podataka za "
            "pretragu slika."
        ),
        "tech": (
            "images_without_alt_attr={bez_alta}/{ukupno} (udeo {udeo}), "
            "images_empty_alt={prazan_alt} se namerno ne broji, nemereno={nemereno}"
        ),
    },
}

# Oznake u HTML izveštaju i nacrt mejla. Ključevi sa `_html` smeju da sadrže oznake.
TEXT: dict[str, str] = {
    "page_title": "Skener — izveštaj",
    "heading": "Skener sajtova — izveštaj",
    "run_of": "Prolaz od {generated} · verzija alata {version}",
    "card_domains": "Domena",
    "card_scanned": "Skenirano",
    "card_partial": "Delimično",
    "card_failed": "Neuspešno",
    "card_level2": "Na nivou 2",
    "card_excluded": "Izuzeto na zahtev",
    "card_duration": "Trajanje",
    "ranked": "Rangirani domeni",
    "ranked_note": (
        "Redosled je po najtežem pojedinačnom nalazu, pa tek onda po zbiru: sajt sa\n"
        "jednom katastrofom je bolji lead od sajta sa deset sitnica."
    ),
    "col_domain": "Domen",
    "col_industry": "Delatnost",
    "col_score": "Skor",
    "col_worst": "Najteži nalaz",
    "col_findings": "Nalaza",
    "col_level2": "Nivo 2",
    "col_status": "Stanje",
    "yes": "da",
    "no": "ne",
    "by_domain": "Po domenu",
    "assumption_html": (
        "<b>Pretpostavka za procenu vremena učitavanja:</b> efektivna brzina\n"
        "{speed} Mb/s ({mb_per_s} MB/s, spora 4G veza) uz {overhead} s režijskog\n"
        "vremena. Broj koji šalješ klijentu moraš umeti da odbraniš, a broj bez navedene pretpostavke\n"
        "ne možeš."
    ),
    "read_only_html": (
        "Alat čita, nikad ne piše. Ne skenira portove, ne pokušava prijavu, ne traži ranjivosti i\n"
        "ne dira putanje koje <code>robots.txt</code> zabranjuje."
    ),
    "summary_meta": (
        "{industry} · skor {score} ·\nnajteži {worst} · {findings:n:nalaz|nalaza|nalaza}"
    ),
    "copy_draft": "Kopiraj nacrt mejla",
    "copied": "Kopirano ✓",
    "no_findings": "Nijedan nalaz — sajt je na proverenim tačkama uredan.",
    "unknowns": "Nije moglo da se proveri ({count})",
    "escalated_because": "Na nivo 2 poslat jer: ",
    "finding_meta": "· nivo {level} · {weight} bodova",
    "draft_clean": "Na sajtu {domain} nisam našao značajnije probleme.",
    "draft_opening": "Poštovani,\n\npregledao sam sajt {domain} i primetio sledeće:\n\n",
    "draft_closing": (
        "\n\nAko vas zanima, mogu da pošaljem detaljan pregled sa predlogom šta prvo popraviti.\n"
    ),
    "severity_critical": "KRITIČNO",
    "severity_high": "VISOKO",
    "severity_medium": "SREDNJE",
    "severity_low": "NISKO",
}
