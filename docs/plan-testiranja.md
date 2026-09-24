# Plan testiranja — skener

```
Oznaka:    PT-SKENER-001
Verzija:   1.0
Datum:     24.09.2026.
Autor:     Milos Lazic
Status:    Nacrt
```

## 1. Uvod

Plan pokriva ciklus testiranja posle prvog prolaza nad 100 pravih domena
([`izvestaj-testiranja-100.md`](izvestaj-testiranja-100.md)): potvrdno testiranje ispravki BUG-003 do
BUG-007, sistematsko testiranje celog alata i ponovljen prolaz nad istih 100 domena. Pravila i pragovi
koje alat mora da poštuje su u README-u (tabela provera je izvedena iz registra) i u `skener.toml`.

## 2. Kontekst

- **Predmet:** skener na grani `main`, Docker slika sa Playwright 1.56.0 i Python 3.12.
- **Obim — jeste:** sve provere nivoa 1 i 2, bodovanje, rangiranje, politika eskalacije, fetcher
  (budžet, semafori, greške), merenje u browseru, CLI (`scan`, `recheck`, `record`, `explain`),
  konfiguracija, izveštaji, ulazni CSV, poruke za klijenta.
- **Obim — nije:** opterećenje tuđih sajtova (alat je namerno pristojan i nije predmet testa
  opterećenja); bezbednost samog Chromium-a; pravna usklađenost načina na koji kupac koristi izveštaj.
- **Pretpostavke:** testovi ne zavise od mreže, osim onih označenih sa `live`; pravi prolaz radi
  operater sa svoje veze.

## 3. Strategija

| Nivo | Šta | Alat | Kada |
|---|---|---|---|
| jedinično | provere nad snapshotima, bodovanje, normalizacija URL-a, konfiguracija | pytest | svaki commit (CI) |
| integraciono | fetcher i browser protiv lokalnog servera; CLI od kraja do kraja | pytest, pravi Chromium | svaki commit (CI, i u Docker slici) |
| sistemsko | ceo prolaz nad 100 pravih domena | `skener scan` u Docker-u | pred prekretnicu (v2) |
| prijemno | ručna ocena vrha rangiranja | vlasnik proizvoda | pred prekretnicu |

**Tehnike**, redom iz skripte: klase ekvivalencije, granične vrednosti (za svaki prag iz README-a,
trotačkasto), tabele odlučivanja (eskalacija, status domena, izbor za nivo 2, statusi sondi i fajlova),
prelazi stanja (ulazni zahtev: https, sertifikat, rukovanje, http, DNS), negativni testovi, pogađanje
grešaka (ćirilica, Excel CSV, nule u konfiguraciji), merenje pokrivenosti grana i mutaciono testiranje.
Svaki parametrizovani slučaj nosi `id` sa tehnikom: `ke-` klasa ekvivalencije, `gv-` granična vrednost,
`tab-` tabela odlučivanja, `st-` prelaz stanja, `nv-` nevažeća klasa, `pg-` pogađanje grešaka.

**Statičko testiranje:** recenzija svih rečenica za klijenta — svaka tvrdnja mora biti tačna i
proverljiva, a svaki broj mora poticati iz dokaza.

**Test podaci:** sintetički snapshoti (`tests/factories.py`), lokalni server (`tests/localserver.py`),
ručno pisani ispitni skup (`tests/fixtures/`). Lista od 100 pravih domena i rezultati po domenu ostaju
van repozitorijuma (`rad/`), jer sadrže poslovne kontakte.

## 4. Kriterijumi

**Ulazni:** Docker slika se gradi; postojeći testovi prolaze; ispravke imaju test koji je pao pre
ispravke.

**Obustava:** pad procesa ili zastoj u pravom prolazu — prolaz se prekida, defekt se prijavljuje i
ispravlja pre nastavka.

**Izlazni** (svi moraju biti ispunjeni):

| Kriterijum | Granica |
|---|---|
| automatizovani testovi | 100 % prolazi, u CI-ju i u Docker slici |
| pokrivenost (linije i grane, ukupno) | ≥ 92 %, bez pada ni u jednom modulu |
| pokrivenost `cli.py` | ≥ 85 % |
| granične vrednosti | svaki prag iz README-a ima test granica − 1, granica, granica + 1 |
| mutacioni skor (provere, bodovanje, konfiguracija) | ≥ 70 % |
| otvoreni defekti | nijedan blocker, critical ni major |
| pravi prolaz | 0 padova; `partial` < 10 %; nijedan poznat lažni nalaz; procena za 200 domena ≤ 15 min |
| merenje vremena učitavanja | u prolazu najviše 1,3× duže nego kad se sajt meri sam |

## 5. Organizacija

Autor testova i izvršilac: razvoj. Prijemna ocena vrha rangiranja: vlasnik proizvoda. Defekti se
vode u izveštaju o testiranju, u formatu iz skripte (BUG-xxx).

## 6. Raspored

1. Potvrdno testiranje BUG-003 do BUG-007 (gotovo: 388/388).
2. Sistematski testovi, pokrivenost, mutaciono testiranje, recenzija poruka.
3. Ponovljen prolaz nad 100 domena (regresija) i provera vremena učitavanja.
4. Izveštaj o testiranju IT-SKENER-002.

## 7. Rizici testiranja

| ID | Rizik | V | U | Mera |
|---|---|---|---|---|
| R1 | pravi sajtovi se menjaju između dva prolaza, pa razlika nije samo posledica ispravki | 4 | 3 | poređenje po grupama nalaza, ne po domenu; sumnjivo se proverava van alata |
| R2 | testovi sa vremenom (pauze, budžet) su nestabilni na sporoj mašini | 2 | 3 | vreme se proverava sa marginom, a mehanizam preko redosleda događaja |
| R3 | mutaciono testiranje traje predugo | 3 | 2 | samo moduli sa logikom; ostalo pokriva integraciono testiranje |
| R4 | lista leadova procuri u javni repozitorijum | 2 | 5 | `rad/` je u `.gitignore`; izveštaji sadrže samo zbirne brojeve |

## 8. Upravljanje defektima

Ozbiljnost: blocker (prolaz stane), critical (pogrešan rezultat za sve), major (lažan nalaz ili
lažno negativan rezultat za klijenta), minor, trivial. Prioritet određuje uticaj na kupca.
Životni ciklus: Novi → Ispravljen → Potvrdno testiran → Zatvoren.

## 9. Isporuke

Testovi u `tests/`, ovaj plan, izveštaj o testiranju, merenja pokrivenosti i mutacionog testiranja.

## 10. Odobrenja

Vlasnik proizvoda odobrava prelazak na v2 na osnovu izveštaja o testiranju.
