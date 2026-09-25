# Izmene

Ovde su izmene koje primeti onaj ko koristi alat ili čita njegov izlaz. Verzije prate semver:
izmena koja lomi kompatibilnost (status domena, `check_id`, oblik nalaza, JSON) podiže prvi broj.

## 2.0.0 — u izradi

Tokom rada verzija je `2.0.0.dev0`. Postaje `2.0.0`, uz tag `v2.0.0`, kad su ispunjeni izlazni
kriterijumi v2 iz [plana testiranja](docs/plan-testiranja.md).

### Izmene koje lome kompatibilnost

Još nijedna. Svaka takva izmena upisuje se ovde u istom commit-u u kom je urađena.

### Dodato

- Ceo prolaz je u modulu `skener.pipeline`, pa ga web aplikacija zove isto kao komandna linija
  ([ADR-008](docs/adr/ADR-008-pipeline.md)).
- Log tokom prolaza ima brojač napretka („nivo 1: 43/200 gotovo").
- Greška i upozorenje u listi domena navode red u kom su, onako kako ga prikazuje Excel
  („red 3: domen se ponavlja u listi").

### Ispravljeno

- Bez instaliranog Playwright-a (`pip install skener` bez `[browser]`) prolaz sa nivoom 2 je
  pucao. Sada se nivo 2 preskače uz poruku, a nivo 1 radi.

## 1.0.0 — 24.09.2026.

Prvo izdanje: 28 provera na dva nivoa (sirovi HTTP i pravi browser), bodovanje po delatnosti,
rangiranje, HTML i CSV izveštaj sa rečenicama za klijenta na srpskom, `recheck` nad sačuvanim
snapshotima i identitet operatera u User-Agent-u. Provereno u tri prolaza nad 100 pravih domena
([IT-SKENER-002](docs/izvestaj-testiranja-2.md)).
