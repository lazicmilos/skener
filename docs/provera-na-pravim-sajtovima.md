# Provera na pravim sajtovima — uslov za v2

Svih 327 offline testova prolazi, ali nijedan nije dotakao pravi sajt. Fixture-i su ručno pisani, a
lokalni server odgovara za mikrosekunde. Četiri baga ispravljena pred ovu proveru (budžet, merenje
vremena, sonde, TLS dokaz) bila su nevidljiva baš zbog toga. Ova lista postoji da nađe **peti**.

Radi se lokalno, na mašini sa pravom mrežom. Rezultat nije „prošlo/palo", nego `docs/kalibracija.md`.

## 0. Priprema (5 min)

```bash
git pull origin claude/quirky-wozniak-u6p6xn
pip install -e '.[dev]'
playwright install chromium
pytest -q                          # mora biti zeleno pre ičega drugog
```

## 1. Ispitni skup: specifikacija naspram stvarnosti (10 min)

```bash
pytest -m live -v 2>&1 | tee live.txt
skener record domains.example.csv --out snimci/      # NE preko tests/fixtures/ — još
python scripts/metrike.py snimci/
```

Svaki pad u `live.txt` je jedno od tri, i treba reći koje:

| Uzrok | Primer | Šta se radi |
|---|---|---|
| sajt se promenio | Mensa popravila canonical | beleška u `kalibracija.md`; fixture se osvežava |
| prag je loš | `lang.mismatch` ne pali na očigledno srpskom sajtu | izmena u `skener.toml`, proveri sa `recheck` |
| bag | provera kaže `ok`, a ručno vidiš problem | test koji pada + popravka, kao B1–B4 |

## 2. Pravi prolaz: 30–50 domena iz tvoje liste leadova (20 min)

```bash
time skener scan leads.csv --out izvestaj/ 2>&1 | tee prolaz.log
python scripts/metrike.py izvestaj/snapshots/ | tee metrike.txt
```

Kad neki domen izgleda čudno:

```bash
skener scan leads.csv --only cudan.rs --debug-domain cudan.rs --out /tmp/debug/
```

## 3. Kriterijumi — uslov za v2

| Metrika | Granica | Zašto baš ta |
|---|---|---|
| padovi procesa | **0** | U2: koliko domena uđe, toliko redova izađe |
| `partial` među domenima koji rade | **< 10 %** | iznad toga budžet ili prag ne odgovara stvarnosti |
| `unknown` za jednu proveru | **< 20 %** živih domena | proveru koja najčešće ne zna ne treba ni imati |
| vreme za 50 domena | **< 4 min** | linearno do U1: 200 domena ≤ 15 min |
| protetica.com | **≤ 2 nalaza** | U4: kontrolni čist sajt |
| prvih 5 u rangiranju | **ručno potvrđeni** | ako #1 nije bolji lead od #10, rangiranje ne radi svoj posao |

Za ručnu potvrdu otvori sajt, uporedi sa `message_client` iz `findings.csv`, i za svaki nalaz zapiši:
tačan / lažno pozitivan / tačan ali nebitan. Isto za poslednjih 5, da proveriš da nisu promašeni loši sajtovi.

## 4. Šta mi šalješ nazad

1. `live.txt`
2. `metrike.txt` za oba prolaza (ispitni skup i leadovi)
3. `izvestaj/summary.csv` i `izvestaj/findings.csv`
4. ručne ocene za prvih 5 i poslednjih 5
5. sve što ti je zapalo za oko, čak i ako ne umeš da objasniš zašto

Snapshote ne šalji. Sadrže sirovi HTML tuđih sajtova, a sve što nam treba iz njih daje `metrike.py`.

## 5. Posle toga

Svaka odluka ide u `docs/kalibracija.md` u obliku **prag — zapažanje — odluka**, a izmene u `skener.toml`
se proveravaju sa `skener recheck izvestaj/snapshots/ --out novi/`, bez ponovnog skidanja sajtova.
Tek kad su svi kriterijumi iz tačke 3 zeleni: `skener record … --out tests/fixtures/`, `git diff`, i v2.
