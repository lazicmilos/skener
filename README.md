# Skener sajtova

Nad listom od ~200 domena proizvodi **rangiranu listu onih koji zaslužuju pun ručni audit**, sa po
nekoliko rečenica na srpskom koje se mogu prekopirati u mejl. Alat ne zamenjuje audit — alat odlučuje
redosled tvog vremena.

![Izveštaj](docs/izvestaj.png)

> Gornji izveštaj je napravljen nad ispitnim skupom iz specifikacije. Ceo HTML je
> [`docs/primer-izvestaja.html`](docs/primer-izvestaja.html) — jedan fajl, bez CDN-a, otvara se bez mreže.

## Šta alat namerno ne radi

- Ne skenira portove, ne pokušava prijavu, ne traži ranjivosti, ne fuzz-uje forme.
- Ne crawl-uje dublje od početne strane i uzorka iz `sitemap.xml` (uz fallback na interne linkove).
- Ne dira nijednu putanju koju `robots.txt` zabranjuje.
- Ne pogađa delatnost sajta — delatnost je ulazni podatak, ne zaključak.
- Ne popravlja ništa. **Alat čita, nikad ne piše.**

## Instalacija

```bash
git clone https://github.com/lazicmilos/skener.git
cd skener
pip install -e .                 # nivo 1: httpx + selectolax
pip install -e '.[browser]'      # nivo 2: + Playwright
playwright install chromium      # jednom, za nivo 2
```

Traži Python 3.11+ (`tomllib` je od tada u standardnoj biblioteci).

## Upotreba

```bash
skener scan domains.example.csv --out izvestaj/
```

Ulaz je CSV sa zaglavljem, ne gola lista domena:

```csv
domain,industry,note
ariaclubzlatibor.rs,hotel,Zlatibor
restoranmb.com,restoran,
protetica.com,zdravstvo,kontrolni cist sajt
```

`industry` ∈ `hotel`, `restoran`, `zdravstvo`, `ecommerce`, `b2b`, `institucija`, `ostalo`.
Prazno polje pada na `ostalo`. Delatnost menja koliko koji nalaz vredi — nedostajuća `og:image` je
skupa hotelu, a skoro nebitna b2b sajtu.

Izlaz su `izvestaj/index.html`, `findings.csv` (red po nalazu), `summary.csv` (red po domenu) i
`izvestaj/snapshots/` sa sirovim podacima svakog domena.

### Ostale komande

```bash
skener recheck izvestaj/snapshots/ --out novi/   # ponovo boduje sačuvano, bez ijednog zahteva
skener record domains.example.csv --out tests/fixtures/
skener explain seo.canonical.duplicate
skener explain --all --markdown                  # tabela provera ispod je odavde
skener scan domains.csv --level 1 --concurrency 4 --only mensa.rs --debug-domain mensa.rs
```

`recheck` je glavno oruđe pri kalibraciji: menjaš prag u `skener.toml` i za sekund vidiš razliku nad
istim podacima, bez ponovnog skidanja 200 sajtova.

## Kako je podeljen

Najvažnija odluka nije podela na nivo 1 i nivo 2, nego ova:

> **Kod koji dodiruje mrežu i kod koji donosi zaključke su dva odvojena sloja. Provera nikad ne
> otvara vezu.** Provera dobija već prikupljene podatke i vraća nalaze.

```
domains.csv → Fetcher L1 (httpx, async) → SiteSnapshot na disk → provere L1 → nalazi
                                                                      ↓
                                                            politika eskalacije
                                                                      ↓
                                     Fetcher L2 (Playwright) → BrowserSnapshot → provere L2
                                                                      ↓
                                              bodovanje → rangiranje → CSV + HTML
```

Zbog te podele testovi rade offline i deterministički, kalibracija ne traži novi prolaz, a kad neki
domen da čudan rezultat imaš tačan ulaz koji ga je proizveo, sačuvan na disku.

| Modul | Odgovornost | Mreža | Disk |
|---|---|---|---|
| `cli` | argumenti, orkestracija faza | ne | ne |
| `config` | pragovi iz TOML-a | ne | čita |
| `models` | šeme podataka, serijalizacija | ne | ne |
| `fetch.urls`, `fetch.page`, `fetch.robots`, `fetch.sitemap` | normalizacija i parsiranje | delom | ne |
| `fetch.http` | nivo 1 | da | — |
| `fetch.browser` | nivo 2 | da | — |
| `checks.*` | pravila; ulaz snapshot, izlaz nalazi | **ne** | ne |
| `score` | bodovanje, rangiranje, eskalacija | ne | ne |
| `store`, `report.*` | snapshoti i izveštaji | ne | piše |

`checks.*` ne uvozi `httpx`, `playwright`, ni `fetch.*` osim `fetch.urls`. Kad zatreba nešto sa
mreže — znači da u snapshotu fali polje, pa se dodaje polje.

## Provere

Tabela je generisana iz registra (`skener explain --all --markdown`), pa se ne može razići sa kodom.

| `check_id` | Nivo | Kategorija | Ozbiljnost | Prag |
|---|---|---|---|---|
| `i18n.lang.invalid` | 1 | i18n | medium | lang ∈ {zxx, und, prazno} ili ne parsira kao BCP-47 |
| `i18n.lang.mismatch` | 1 | i18n | high | sadržaj prepoznat kao sr (ćirilica > 30 % ili dijakritici > 0,5 %) uz lang koji ne počinje sa sr |
| `i18n.lang.missing` | 1 | i18n | medium | atribut lang ne postoji |
| `infra.dns.unresolved` | 1 | infra | critical | DNS upit nije vratio adresu |
| `infra.robots.missing` | 1 | infra | low | status ≠ 200 |
| `infra.sitemap.missing` | 1 | infra | medium | status ≠ 200, ili 200 sa 0 URL-ova |
| `infra.soft404` | 1 | infra | high | obe sonde vraćaju konačni status 200 |
| `infra.tls.invalid` | 1 | infra | high | TLS provera odbila sertifikat |
| `perf.compression.missing` | 1 | perf | medium | content-encoding ∉ {gzip, br, zstd, deflate} i HTML > 50 kB |
| `perf.html.size` | 1 | perf | low | html_bytes > 500 kB |
| `perf.redirect.chain` | 1 | perf | low | broj skokova ≥ 3 |
| `seo.canonical.duplicate` | 1 | seo | critical | ≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim canonical-om |
| `seo.canonical.missing` | 1 | seo | high | nema oznake na početnoj |
| `seo.description.duplicate` | 1 | seo | medium | ≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim opisom |
| `seo.description.missing` | 1 | seo | medium | prazan ili nepostojeći meta opis |
| `seo.title.duplicate` | 1 | seo | high | ≥ 3 stranice iz ≥ 3 različite grupe putanja sa istim naslovom |
| `seo.title.missing` | 1 | seo | high | prazan ili nepostojeći `<title>` |
| `social.og.description.missing` | 1 | social | medium | nedostaje `og:description` |
| `social.og.image.missing` | 1 | social | medium | nedostaje `og:image` |
| `social.og.title.missing` | 1 | social | high | nedostaje `og:title` |
| `a11y.img.alt.missing` | 2 | a11y | low | ≥ 5 slika i udeo bez alt atributa > 0,5; > 0,8 uz ≥ 15 slika → high; zdravstvo/institucija → bar medium |
| `perf.img.oversized` | 2 | perf | medium | ≥ 3 slike sa odnosom > 2,5 ili procenjen višak > 700 kB |
| `perf.load.time` | 2 | perf | high | > 4 s medium · > 8 s high · prekid posle tvrdog limita = high |
| `perf.page.weight` | 2 | perf | critical | > 1,5 MB medium · > 3 MB high · > 8 MB critical |
| `perf.request.count` | 2 | perf | high | > 100 medium · > 150 high |
| `qa.console.errors` | 2 | qa | low | > 3 greške u konzoli |
| `seo.h1.missing` | 2 | seo | high | h1_count == 0 posle učitavanja u browseru |
| `seo.h1.multiple` | 2 | seo | low | h1_count > 3 |

Svaka provera vraća jedno od tri stanja: `ok`, `finding` ili **`unknown` sa obaveznim razlogom**.
Bez trećeg ne razlikuješ „čisto" od „nije provereno", a to je razlika koja te za mesec dana košta
poverenja u sopstveni izveštaj.

## Zašto su pragovi baš takvi

| Prag | Vrednost | Obrazloženje |
|---|---|---|
| dijakritici za prepoznavanje srpskog | **0,005** | Srpski latinicom ima 2–5 % dijakritika, engleski 0 %. Prag je deset puta niži od očekivanog da izdrži kratke tekstove, i i dalje desetostruko iznad šuma. |
| odnos za predimenzionirane slike | **2,5** | Ekrani sa `devicePixelRatio` 2 legitimno traže duplo veću sliku. Prag 2 bi svaki ispravno urađen retina sajt proglasio pokvarenim; 2,5 ostavlja marginu. |
| duplikati | **≥ 3 stranice iz ≥ 3 grupe putanja** | Osam blog postova sa istim naslovom šablona nije isto što i ceo sajt koji se Google-u predstavlja kao jedna stranica. Zahtev za različitim grupama je ono što čuva odsustvo lažnih pozitiva. |
| prazan HTML za eskalaciju | **800 znakova** | Razlikuje se od praga jezičke heuristike (400) namerno: 400 je granica pouzdanosti prepoznavanja jezika, 800 je granica „ovo izgleda kao prazan HTML". |
| spora početna za eskalaciju | **1500 ms** | Jedini uslov koji hvata sajt sa čistim SEO-om i sporom stranicom. Bez njega takav domen nikad ne stigne na nivo 2 i alat ga proglasi čistim. |
| nemereni odgovori | **> 5 → `unknown`** | Merenje u koje nemaš poverenja gore je od merenja kojeg nema. |
| gornji limit za nivo 2 | **60 domena** | Ako 180 od 200 domena ima bar jedan nalaz, bez limita sve ide na nivo 2 i prolaz traje sat vremena. |
| bodovi po ozbiljnosti | **40 / 20 / 8 / 3** | Razmak je namerno nelinearan: jedan `critical` mora da nadjača pet `low`-ova, jer u praksi i nadjačava. |
| brzina mobilne veze | **4,8 Mb/s (0,6 MB/s)** | Spora 4G veza, uz 1 s režije. Stoji u fusnoti svakog izveštaja: broj koji šalješ klijentu moraš umeti da odbraniš. |

Rangiranje ne ide po zbiru nego po `(najteži pojedinačni nalaz, zbir)`. Sajt sa jednom katastrofom je
bolji lead od sajta sa deset sitnica: prvi ima jedan razlog zbog koga će ti odgovoriti, drugi ima
listu na koju se ne reaguje.

Svi pragovi žive u [`skener.toml`](skener.toml), ne u kodu — `git diff` nad njim je čitljiv istorijat
tvojih odluka tokom kalibracije.

## Testovi

```bash
pytest                    # offline, bez mreže, ~15 s
pytest -m live            # pravi prolaz nad ispitnim skupom (traži mrežu)
pytest -m browser         # nivo 2 protiv pravog Chromiuma i lokalnog servera
```

Dva sloja. Prvi radi bez mreže i vrti se na svaki commit: sve provere nad snapshotima, bodovanje,
normalizacija URL-ova, parsiranje sitemapa, plus integracioni testovi protiv **lokalnog HTTP servera**
koji servira namerno pokvaren sajt — tako se stvarno proveravaju retry politika, budžet po domenu,
semafor po hostu i merenje težine u browseru. Drugi sloj je označen markerom i isključen, inače CI
pada kad nekom sajtu istekne sertifikat.

Osnova svih testova je **čist sajt na kome nijedna provera ne sme da nađe ništa**. Svaki pozitivan
test kvari tačno jednu stvar i tvrdi da nije probudio ostale provere.

> **Fixture-i u `tests/fixtures/` su ručno napisani, nisu snimljeni sa pravih sajtova.** Napravljeni
> su bez pristupa mreži i opisuju ono što specifikacija tvrdi da je na tih osam domena, ne ono što je
> tamo danas. Proveravaju da lanac provera radi — ne da su domeni u tom stanju. Zameni ih pravim
> snimcima sa `skener record domains.example.csv --out tests/fixtures/` i pogledaj `git diff`.

## Etika

```
User-Agent: MlazicSiteScanner/1.0 (+https://github.com/lazicmilos/skener; miloslazic458@gmail.com)
```

Ime alata, adresa gde piše šta radi, kontakt — sva tri su obavezna. Bez toga si anonimni bot koji sa
jedne adrese udara dvesta sajtova, i administrator koji te blokira postupa ispravno.

- **Nikad dva paralelna zahteva ka istom sajtu.** Globalni semafor ograničava tebe; po-hostu semafor
  (uvek 1) štiti njih. To je granica između alata i napada.
- Pauza 0,5–1,0 s između uzastopnih zahteva ka istom hostu, uz `Crawl-delay` iz `robots.txt`.
- `Disallow` se poštuje. Alat koji prijavljuje da `robots.txt` nedostaje a ignoriše ga kad postoji je
  nekonzistentan na način koji se primeti.
- Tvrd budžet: najviše 16 zahteva i 25 sekundi po domenu.
- Na `429` ili `503` se odustaje od domena za taj prolaz, bez ponovnog pokušaja.

## Planirano, nije u v1

- Kanonizacija hosta (sve četiri varijante `http/https` × `www/bez www`) kao podrazumevana provera.
- Core Web Vitals (LCP, CLS) — vredni brojevi, ali traže pažljivije merenje nego što v1 zaslužuje.
- `skener diff` između dva prolaza: „sajt je od marta postao 3 MB teži" je jak uvod u mejl.
- Provera strukturiranih podataka (`schema.org`) — za restorane i klinike ima stvarnu vrednost.
- Prepoznavanje CMS-a (WordPress, Wix, custom) — menja formulaciju ponude.

