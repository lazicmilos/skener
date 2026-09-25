# Izmene

Ovde su izmene koje primeti onaj ko koristi alat ili čita njegov izlaz. Verzije prate semver:
izmena koja lomi kompatibilnost (status domena, `check_id`, oblik nalaza, JSON) podiže prvi broj.

## 2.0.0 — u izradi

Tokom rada verzija je `2.0.0.dev0`. Postaje `2.0.0`, uz tag `v2.0.0`, kad su ispunjeni izlazni
kriterijumi v2 iz [plana testiranja](docs/plan-testiranja.md).

### Izmene koje lome kompatibilnost

Svaka takva izmena upisuje se ovde u istom commit-u u kom je urađena.

- `Finding` više nema `message_client` ni `message_tech`. Rečenicu pravi
  `skener.messages.render(finding, lang)` pri prikazu, a nalaz dobija `variant`
  ([ADR-009](docs/adr/ADR-009-katalog-poruka.md)). Kolona `message_client` u `findings.csv` ostaje.
- Dokaz nalaza je samo podatak. Nestali su složeni oblici `uz_video`, `preuzimanja`,
  `greske_tekst`, `kopije`, `stranice`, `naslovi` i `od_slika`. `uzorak` je kod (`sitemap`,
  `links`, `none`), nedostajuće kodiranje je `null` umesto „nema", a `lanac` preusmerenja je
  lista URL-ova umesto teksta sa strelicama.
- Privatne i posebne adrese se više ne otvaraju (SSRF, [ADR-006](docs/adr/ADR-006-ssrf.md)).
  Domen sa IP adresom, portom ili korisničkim imenom je `failed` bez ijednog zahteva, osim kad je
  `host:port` naveden u `[net] allowed_private`. Nivo 1 više ne čita `HTTP(S)_PROXY`.
- `CheckSpec` više nema šablone `message_template` i `tech_template`, a `check()` ne prima
  `message` ni `tech`. Modul `skener.checks.srpski` je prešao u `skener.messages.sr`.

### Dodato

- JSON izveštaj `report.json` sa verzijom šeme (`skener/schema/report-2.json`), otiskom
  konfiguracije i okruženjem. `--format` ga podrazumevano piše uz HTML i CSV.
- Snapshot nivoa 2 beleži verziju Chromium-a kojim je meren.
- Izuzeti domeni: `[identitet] izuzeti` ili `--exclude FILE`, jedan domen po redu, uz sve
  poddomene. Izuzet domen ne dobija nijedan zahtev; u izveštaju je samo njihov broj (status
  `excluded` u zbiru).
- Izveštaji na srpskom i engleskom: `--lang sr|en` za `scan` i `recheck`. `skener explain`
  ispisuje rečenice na oba jezika.
- Ceo prolaz je u modulu `skener.pipeline`, pa ga web aplikacija zove isto kao komandna linija
  ([ADR-008](docs/adr/ADR-008-pipeline.md)).
- Log tokom prolaza ima brojač napretka („nivo 1: 43/200 gotovo").
- Greška i upozorenje u listi domena navode red u kom su, onako kako ga prikazuje Excel
  („red 3: domen se ponavlja u listi").

### Ispravljeno

- U HTML izveštaju je pisalo „1 nalaza"; sada se broj i imenica slažu („1 nalaz", „3 nalaza").
- Bez instaliranog Playwright-a (`pip install skener` bez `[browser]`) prolaz sa nivoom 2 je
  pucao. Sada se nivo 2 preskače uz poruku, a nivo 1 radi.

## 1.0.0 — 24.09.2026.

Prvo izdanje: 28 provera na dva nivoa (sirovi HTTP i pravi browser), bodovanje po delatnosti,
rangiranje, HTML i CSV izveštaj sa rečenicama za klijenta na srpskom, `recheck` nad sačuvanim
snapshotima i identitet operatera u User-Agent-u. Provereno u tri prolaza nad 100 pravih domena
([IT-SKENER-002](docs/izvestaj-testiranja-2.md)).
