# Kalibracija

Dnevnik odluka iz provera na pravim sajtovima. Oblik: **zapažanje — uzrok — odluka**.
Kako se provera radi, piše u [`provera-na-pravim-sajtovima.md`](provera-na-pravim-sajtovima.md).

## 2026-09-26 — `seo.canonical.duplicate` broji samo tuđi canonical (Z-23)

- **Zapažanje:** u IT-SKENER-002 (O-9) dve podstranice od sedam, koje upućuju na početnu, dale su
  `critical` i prvo mesto u rangiranju. Treća stranica u pravilu „≥ 3" bila je sama početna, a ona
  sa canonical-om na sebe je ispravna.
- **Uzrok:** pravilo je brojalo svaku stranicu sa istim canonical-om, i onu koja upućuje na sebe, a
  ozbiljnost je uvek bila `critical`, bez obzira na to koliki deo sajta je pogođen.
- **Odluka:** broje se samo stranice čiji canonical upućuje na drugu adresu
  (`canonical_foreign_min = 2`, iz bar dve grupe putanja, da paginacija jednog bloga ne bude
  nalaz). Ozbiljnost po udelu u uzorku: `canonical_share = { high = 0.4, critical = 0.6 }`, ispod
  toga `medium`. To su početne vrednosti iz specifikacije; granice se biraju u Z-50, posle
  `recheck`-a nad snapshotima liste A i provere svakog nalaza `curl`-om.

## 2026-09-24 — treći prolaz: težina iz prenetih bajtova

Ceo izveštaj: [`izvestaj-testiranja-2.md`](izvestaj-testiranja-2.md).

| Prag ili pravilo | Zapažanje | Odluka |
|---|---|---|
| šta se broji u težini | brojač je sabirao raspakovano telo; isti sajt: 25,3 MB raspakovano, 3,8 MB preneto (BUG-016) | broje se preneti bajtovi (`responseBodySize`) |
| `perf.page.weight` | preneto bez videa, 60 sajtova: medijana 2,8 MB, p75 5,2, p90 8,1, najviše 22,1 | 3 / 5 / 8 MB; zamenjuje 5 / 10 / 20 MB iz reda ispod |
| ispravka primera za video | „8,5 MB jednom, 26,9 MB drugi put" nije bio video: taj sajt nema nijedan video bajt, razliku prave skripte i stilovi koji se učitavaju i posle `load` | odluka o videu ostaje; pravi primer je sajt koji je u jednom prolazu preneo 77 MB videa, a u drugom 39 MB |

## 2026-09-24 — odluke posle prolaza nad 100 domena

| Prag ili pravilo | Zapažanje | Odluka |
|---|---|---|
| `perf.page.weight` | 55 od 60 sajtova preko 1,5 MB; medijana 4,4 MB, p75 10,6, p90 17,2 (raspakovani bajtovi) | 5 / 10 / 20 MB, bez videa (zamenjeno, vidi gore) |
| video u težini | isti sajt: 8,5 MB jednom, 26,9 MB drugi put (pogrešan primer, vidi ispravku gore) | ne ulazi u prag; u rečenici stoji posebno |
| vreme učitavanja | u prolazu do 4,6× duže nego kad se sajt meri sam | učitava se jedan po jedan; ostatak merenja paralelno |
| `http.max_seconds_per_domain` | 19 domena potrošilo 25 s; strana na sporom hostingu 1–3 s | 40 s; broj zahteva ostaje 16 |
| izbor za nivo 2 | 9 od 18 odsečenih kandidata bez ijednog nalaza nivoa 1 | prvo kandidati bez jakog nalaza nivoa 1 |
| `i18n.lang.mismatch` | tačan 28 od 28, ali poruka je tvrdila nešto o Google-u što nije tačno | poruka o čitačima ekrana; high → medium |
| `perf.compression.missing` | poruka je tvrdila „sekunda i po"; stvarna ušteda je desetinke sekunde | ušteda se računa iz veličine; medium → low |
| statusi 401/403/429/5xx | sajt iza zaštite od botova dobijao nalaze o robots.txt i mapi sajta | samo 404 i 410 znače „ne postoji"; ostalo je `unknown` |

## 2026-09-24 — prolaz nad 100 pravih domena

Ceo izveštaj: [`izvestaj-testiranja-100.md`](izvestaj-testiranja-100.md). Ukratko: 0 padova i 7,7 min
za 100 domena, ali `partial` 30 %, četiri otvorena defekta (BUG-003 do BUG-006) i šest zapažanja
(O-1 do O-6) koja čekaju odluku. Najvažnije među njima: prag težine stranice pali na 55 od 60 sajtova,
a vreme učitavanja je naduvano jer se meri dok tri sajta dele vezu.

## 2026-09-24 — prvi prolaz nad ispitnim skupom (8 domena)

Rezultat: 11/12 live testova, `partial` 3/8 (38 %), `unknown` za `infra.soft404` 25 %.

### mensa.rs je popravljen

- **Zapažanje:** nema `seo.canonical.duplicate` ni `infra.soft404`, koje specifikacija očekuje.
- **Uzrok:** sajt je popravljen. Svih 8 stranica u uzorku ima sopstveni canonical, a obe sonde vraćaju 404.
- **Odluka:** alat radi ispravno. Oba nalaza su u `POPRAVLJENO` u `tests/test_live.py`; fixture-i ostaju kao u specifikaciji.

### Velika mapa sajta pojede budžet pre sondi za lažni 404 (bag)

- **Zapažanje:** cdei.rs (6 mapa) i domaceizsrbije.rs (9 mapa) su potrošili 16/16 zahteva i nemaju nijednu sondu.
- **Uzrok:** sonde su išle poslednje, posle do 10 fajlova mape sajta i 7 stranica uzorka.
- **Odluka:** sonde idu pre uzorka, a `sitemap.max_files` je spušten sa 10 na 4.
  Budžet: početna 1 + robots 1 + sonde 2 + mape 4 + uzorak 7 = 15 od 16.
  Test: `test_velika_mapa_sajta_ne_pojede_sonde_za_lazni_404`.

### Nivo 2 visi zauvek na protetica.com (bag)

- **Zapažanje:** pun prolaz sa nivoom 2 nije se završio ni posle 10 minuta; 7 domena gotovo za ~30 s,
  protetica.com nikad. Javlja se povremeno, samo u punom prolazu.
- **Uzrok:** stek pokazuje da `_Recorder.drain()` čeka `response.body()` odgovora čije telo nikad ne stigne
  (strim, video). Nivo 2 nije imao tvrdi limit po domenu, pa je jedan takav odgovor blokirao ceo prolaz.
- **Odluka:** `drain` čeka najviše `browser.drain_timeout_s = 5`; šta ne stigne je nemereno, ne nula.
  Ceo nivo 2 po domenu ima tvrdi limit `browser.max_seconds_per_domain = 60`, posle kog je domen `failed`
  sa razlogom, a prolaz ide dalje. Testovi: `test_telo_koje_ne_stigne_je_nemereno_a_ne_zastoj`,
  `test_tvrdi_limit_po_domenu_prekida_nivo_2`.

### Posle obe popravke (automatski nivo)

`partial` 0 % (bilo 38 %), `unknown` 0 % (bilo 25 % za `infra.soft404`), najviše 15 od 16 zahteva.

Otvoreno za prolaz nad 100 domena:
- najsporiji domen je trošio 23,6 od 25 s budžeta — sporiji sajtovi će ga probijati;
- `perf.page.weight` pali na 7–8 od 8 domena. Ako tako ostane i na 100, prag od 1,5 MB ne razlikuje
  leadove i treba ga podići.

### protetica.com je `partial` — otvoreno

- **Zapažanje:** `perf.img.oversized` je `unknown` (17 od 33 slike nije izmereno), a kontrolni čist sajt
  ima 4 nalaza nivoa 2: `perf.page.weight`, `perf.load.time`, `perf.request.count`, `qa.console.errors`.
- **Odluka:** čeka ručnu proveru sajta u browser-u — da li su nalazi tačni, i zašto se pola slika ne učita
  posle skrolovanja.
