# CATEGORY-02C – 457 besorolható kategória: aktuális állapot és eltérés-jelentés

Ez a jelentés a **jelenlegi** állapotot írja le (#20). A korábbi, 412 kategóriás CODEX 05 jelentés ([reviewed-parameter-profiles.md](reviewed-parameter-profiles.md), [JSON](reports/reviewed-parameter-profiles.json)) történeti dokumentumként változatlan marad; az ott szereplő 412/171 számok az akkori ellenőrzést írják le, nem a mostanit.

- Gépi, verziózott eredmény: [`docs/reports/category-457-status.json`](reports/category-457-status.json)
- Előállítás (offline, adatbázis nélkül, `pinfo_db`-t nem érinti):
  ```bash
  PYTHONPATH=backend python scripts/report_category_457.py          # újragenerálás
  PYTHONPATH=backend python scripts/report_category_457.py --check  # elavult-e (a tesztcsomag is futtatja)
  ```
- A JSON a bemenetek SHA-256 lenyomatát is rögzíti (régi jelentés, `reviewed_parameter_bindings.json`, `donor_review.json`, kategóriaexport `053a18a2…`).
- Regressziós tesztek: `backend/tests/test_category_457_audit.py`.

## Összefoglaló

| Ellenőrzés | Történeti (CODEX 05) | Jelenlegi |
|---|---:|---:|
| Magyar főcsoport | 13 | **13, azonos azonosítók és sorrend** |
| Rögzített menüpont | 583 | **583, azonos név és szülő mindegyiknél** |
| Besorolható termékkategória | 412 (`confirmed`) | **457** |
| Navigációs/strukturális pont | 171 | 126 |
| Újonnan besorolható | – | **45** (mind korábban `navigation`) |
| Megszűnt besorolhatóság | – | 0 |
| Többprofilos kategória | 18 | 23 |
| Profil-hozzárendelés | 503 | 555 |
| Ellenőrzésre váró (`pending_review`) donor | – | 3 |
| Törölt pont (`web-item-43-3550` TV antennák) | nem besorolható | nem besorolható, nincs a fában |
| Kalibrált automatikus módszer | – | **nincs** (`CALIBRATED_PRECISION = {}`) |

A 457 kategóriát a Tulajdonos jóváhagyta; a 45 eltérés **nem új menüpont**: a fa szerkezete, a nevek, az azonosítók és a sorrend változatlan, csak a 45 meglévő pont vált termékkategóriává.

Kilenc besorolható kategóriának van gyermeke is (pl. `web-item-29-3863` Okosórák); ezek a CODEX 05-ben is `confirmed` státuszúak voltak, nem a 45 közül valók. Felsorolás: JSON `classification.bindable_with_children`.

## A 45 újonnan besorolható elem

Mindegyik szabály `reviewed_input_state` értéke `structural_product_reclassified`, és **ugyanaz az általános indoklás** tartozik hozzájuk: „Termékkategória; az archivált menü szűrő/szekció szerepe nem zárja ki a termékbesorolást. A termékkör meglévő profiljai külön maradnak.” Elemenkénti, termékkör-specifikus bizonyíték a szabályfájlban nincs; a kockázati besorolást ezért ez a jelentés adja hozzá (lásd lent). Státusz: `navigation` → `bindable` (a CATEGORY-02A besorolási célként elfogadja).

Kockázat:
- **azonos/szűkebb** – a menüpont termékköre a donoréval azonos, vagy annak típus/kivitel/platform/évszak szerinti szűkítése (37 db);
- **több profil – kifejezett választás** – több külön donorprofil; automatikus döntés nem választ profilt, dúsítás csak kifejezett választás után (5 db);
- **pending_review** – a donor paraméterkészletének alkalmazhatósága nem igazolt; automatikusan nem rendelődik hozzá és dúsításra nem használható (3 db).

| # | ID | Teljes útvonal | Donor(ok) (eMAG ID – név, paraméterszám) | Régi → új státusz | Kockázat |
|---:|---|---|---|---|---|
| 1 | `web-item-114-3490` | Háztartási gépek és klíma > Mosógépek és szárítógépek > Elöltöltős mosógépek | 385 – Mosógépek (45) | navigation → bindable | azonos/szűkebb |
| 2 | `web-item-114-3491` | Háztartási gépek és klíma > Mosógépek és szárítógépek > Felültöltős mosógépek | 385 – Mosógépek (45) | navigation → bindable | azonos/szűkebb |
| 3 | `web-item-114-3492` | Háztartási gépek és klíma > Mosógépek és szárítógépek > Mosó-szárítógépek | 385 – Mosógépek (45) | navigation → bindable | **pending_review** |
| 4 | `web-item-114-4237` | Háztartási gépek és klíma > Mosogatógépek > Keskeny mosogatógépek | 411 – Mosogatógépek (36) | navigation → bindable | azonos/szűkebb |
| 5 | `web-item-114-3502` | Háztartási gépek és klíma > Páraelszívók | 525 – Páraelszívók (35) | navigation → bindable | azonos/szűkebb |
| 6 | `web-item-114-3508` | Háztartási gépek és klíma > Beépíthető készülékek > Beépíthető mosogatógépek | 411 – Mosogatógépek (36) | navigation → bindable | azonos/szűkebb |
| 7 | `web-item-114-3750` | Háztartási gépek és klíma > Beépíthető készülékek > Beépíthető mikrohullámú sütők | 363 – Mikrohullámú sütők (22) | navigation → bindable | azonos/szűkebb |
| 8 | `web-item-114-3751` | Háztartási gépek és klíma > Porszívók és vasalók > Porzsákos porszívók | 58 – Porszívók (27) | navigation → bindable | azonos/szűkebb |
| 9 | `web-item-114-3819` | Háztartási gépek és klíma > Porszívók és vasalók > Porzsák nélküli porszívók | 58 – Porszívók (27) | navigation → bindable | azonos/szűkebb |
| 10 | `web-item-114-3752` | Háztartási gépek és klíma > Porszívók és vasalók > Álló porszívók | 58 – Porszívók (27) | navigation → bindable | azonos/szűkebb |
| 11 | `web-item-114-3820` | Háztartási gépek és klíma > Porszívók és vasalók > Robotporszívók | 58 – Porszívók (27) | navigation → bindable | **pending_review** |
| 12 | `web-item-114-3753` | Háztartási gépek és klíma > Kávékészítés > Automata eszpresszó kávéfőzők | 32 – Eszpresszó kávéfőzők (29) | navigation → bindable | azonos/szűkebb |
| 13 | `web-item-114-3754` | Háztartási gépek és klíma > Kávékészítés > Kapszulás kávéfőzők | 32 – Eszpresszó kávéfőzők (29) | navigation → bindable | azonos/szűkebb |
| 14 | `web-item-43-3697` | TV és szórakozás > eBook olvasók és tartozékok | 103 – eBook olvasók (25); 313 – eBook olvasó tartozékok (8) | navigation → bindable | több profil – kifejezett választás |
| 15 | `web-item-43-4021` | TV és szórakozás > Konzolok és játékok > Hordozható játékkonzolok | 152 – Hardver konzolok (36) | navigation → bindable | azonos/szűkebb |
| 16 | `web-item-1-4244` | Telefon, Tablet, Laptop > Telefonok > Klasszikus mobiltelefonok | 15 – Mobiltelefonok (43) | navigation → bindable | azonos/szűkebb |
| 17 | `web-item-1-3180` | Telefon, Tablet, Laptop > Laptopok > Laptopok Windows-szal | 14 – Laptop / Notebook (68) | navigation → bindable | azonos/szűkebb |
| 18 | `web-item-7-3683` | Számítástechnika > Gaming > Gamer PC-k | 6 – Asztali számítógép (70) | navigation → bindable | azonos/szűkebb |
| 19 | `web-item-7-3827` | Számítástechnika > Gaming > Gamer laptopok | 14 – Laptop / Notebook (68) | navigation → bindable | azonos/szűkebb |
| 20 | `web-item-7-3684` | Számítástechnika > Gaming > Gamer monitorok | 5 – LCD & LED monitorok (39) | navigation → bindable | azonos/szűkebb |
| 21 | `web-item-7-3829` | Számítástechnika > Gaming > Gamer billentyűzetek | 10 – Billentyűzetek (17) | navigation → bindable | azonos/szűkebb |
| 22 | `web-item-7-3830` | Számítástechnika > Gaming > Gamer egérpad | 54 – Egérpad (6) | navigation → bindable | azonos/szűkebb |
| 23 | `web-item-7-3831` | Számítástechnika > Gaming > Gamer egér | 11 – Egér (16) | navigation → bindable | azonos/szűkebb |
| 24 | `web-item-29-4260` | Fotó-Videó, Okos eszközök > Okosórák > Android kompatibilis okosórák | 2920 – Okosórák (45) | navigation → bindable | azonos/szűkebb |
| 25 | `web-item-29-4261` | Fotó-Videó, Okos eszközök > Okosórák > iOS kompatibilis okosórák | 2920 – Okosórák (45) | navigation → bindable | azonos/szűkebb |
| 26 | `web-item-173-4297` | Otthon, barkács, kert > Világítás és elektronika > Okos izzók | 365 – Izzók (25) | navigation → bindable | azonos/szűkebb |
| 27 | `web-item-173-4008` | Otthon, barkács, kert > Dekorációk | 1567 – Dekorációs kiegészítők (20); 3903 – Fali dekorációk (13) | navigation → bindable | több profil – kifejezett választás |
| 28 | `web-item-173-4125` | Otthon, barkács, kert > Konyha és felszolgálás > Főzőedények | 146 – Serpenyő (21); 147 – Fazekak és lábasok (20); 1606 – Hőálló edények (21); 2664 – Multifunkciós főzőedények (21) | navigation → bindable | több profil – kifejezett választás |
| 29 | `web-item-173-3778` | Otthon, barkács, kert > Konyha és felszolgálás > Vízszűrő kancsók és tartozékok | 520 – Vízszűrő kancsók (17); 3674 – Vízszűrő kancsó tartozékok (14) | navigation → bindable | több profil – kifejezett választás |
| 30 | `web-item-199-2725` | Játékok, Baba, Mama > BABA-MAMA > Babakocsik és hordozók | 1359 – Babakocsik és tartozékok (23); 3257 – Babahordozó eszközök (11) | navigation → bindable | több profil – kifejezett választás |
| 31 | `web-item-199-3264` | Játékok, Baba, Mama > BABA-MAMA > Babajátékok > Interaktív babajátékok | 3290 – Interaktív babajátékok (14) | navigation → bindable | azonos/szűkebb |
| 32 | `web-item-199-3265` | Játékok, Baba, Mama > BABA-MAMA > Babajátékok > Tevékenységi központok és játszószőnyegek | 3278 – Baba tevékenységi játékközpont (14) | navigation → bindable | azonos/szűkebb |
| 33 | `web-item-199-4313` | Játékok, Baba, Mama > JÁTÉKOK > Társasjátékok > Gyerek társasjátékok | 1209 – Társasjátékok (15) | navigation → bindable | azonos/szűkebb |
| 34 | `web-item-199-4314` | Játékok, Baba, Mama > JÁTÉKOK > Társasjátékok > Családi társasjátékok | 1209 – Társasjátékok (15) | navigation → bindable | azonos/szűkebb |
| 35 | `web-item-199-4315` | Játékok, Baba, Mama > JÁTÉKOK > Társasjátékok > Felnőtt társasjátékok | 1209 – Társasjátékok (15) | navigation → bindable | azonos/szűkebb |
| 36 | `web-item-199-4128` | Játékok, Baba, Mama > JÁTÉKOK > LEGO felnőtteknek | 1187 – Építőkészletek (15) | navigation → bindable | azonos/szűkebb |
| 37 | `web-item-83-2994` | Szépségápolás > Parfümök | 1241 – Parfüm (14) | navigation → bindable | azonos/szűkebb |
| 38 | `web-item-83-4339` | Szépségápolás > Szépségápolási készülékek > IPL tartós szőrtelenítők | 63 – Epilátorok (26) | navigation → bindable | **pending_review** |
| 39 | `web-item-165-4041` | Sport és utazás > Kerékpározás > Felnőtt kerékpárok | 1809 – Kerékpárok (34) | navigation → bindable | azonos/szűkebb |
| 40 | `web-item-165-4042` | Sport és utazás > Kerékpározás > Gyerek kerékpárok | 1809 – Kerékpárok (34) | navigation → bindable | azonos/szűkebb |
| 41 | `web-item-79-4347` | Könyvek, Filmek és Irodaszerek > Filmek, zene > Bakelit lemezek | 604 – Hanglemezek és zenei CD-k (22) | navigation → bindable | azonos/szűkebb |
| 42 | `web-item-79-3439` | Könyvek, Filmek és Irodaszerek > Írás és rajzolás > Füzetek | 2606 – Füzetek (12) | navigation → bindable | azonos/szűkebb |
| 43 | `web-item-512-3833` | Autó- és motor felszerelések > Gumiabroncsok > Nyári gumik | 1412 – Gumiabroncsok (16) | navigation → bindable | azonos/szűkebb |
| 44 | `web-item-512-3834` | Autó- és motor felszerelések > Gumiabroncsok > Téli gumik | 1412 – Gumiabroncsok (16) | navigation → bindable | azonos/szűkebb |
| 45 | `web-item-512-3832` | Autó- és motor felszerelések > Gumiabroncsok > Négyévszakos | 1412 – Gumiabroncsok (16) | navigation → bindable | azonos/szűkebb |

## Kockázatos donorok egyenkénti átnézése

Forrás: a verziózott kategóriaexport (`backend/tests/fixtures/emag_categories_export.tsv`, id, név, szülő, `is_allowed`, paraméterszám). Az export **paraméterneveket nem tartalmaz**, ezért a hiányzó paraméterek tényleges listája csak a `pinfo_db` olvasásával állapítható meg (lent: csak olvasó SQL).

| Menüpont | Donor | Megállapítás | Javaslat |
|---|---|---|---|
| Mosó-szárítógépek (`web-item-114-3492`) | 385 Mosógépek (45 param.) | Nincs külön mosó-szárítógép kategória. A donor mosógép-termékkör; a szárítási funkció paraméterei nem igazoltak. Létezik külön 673 Szárítógépek (31 param.), de a szabályban nem szerepel. | **pending_review** |
| Robotporszívók (`web-item-114-3820`) | 58 Porszívók (27) | Nincs külön robotporszívó kategória. Robot-specifikus jellemzők (navigáció, üzemidő, dokkoló, felmosás) lefedettsége nem igazolt. | **pending_review** |
| IPL tartós szőrtelenítők (`web-item-83-4339`) | 63 Epilátorok (26) | Nincs külön IPL kategória. Eltérő technológia (fényimpulzus vs. mechanikus epilálás). | **pending_review** |
| eBook olvasók és tartozékok (`web-item-43-3697`) | 103 eBook olvasók (25), 313 tartozékok (8) | A két profil pontosan a menüpont két termékkörét fedi. | kifejezett profilválasztás (már kötelező) |
| Dekorációk (`web-item-173-4008`) | 1567 Dekorációs kiegészítők (20), 3903 Fali dekorációk (13) | Tág gyűjtőkategória; lehetnek termékek, amelyekre egyik profil sem illik. | kifejezett választás; nyitott kérdés |
| Főzőedények (`web-item-173-4125`) | 146, 147, 1606, 2664 | Az exportban további rokon kategóriák is vannak, amelyek **nincsenek** a szabályban: 1604 fedők (13), 1843 Kotyogós kávéfőzők (13), 3619 Főzőedények (0 param.). Fedőre a négy profil egyike sem illik. | kifejezett választás; nyitott kérdés |
| Vízszűrő kancsók és tartozékok (`web-item-173-3778`) | 520 kancsók (17), 3674 tartozékok (14) | A két profil a két termékkört fedi. Rokon: 3722 Vízszűrők, kancsók, szűrőrendszerek (6), nincs a szabályban. | kifejezett választás |
| Babakocsik és hordozók (`web-item-199-2725`) | 1359 Babakocsik és tartozékok (23), 3257 Babahordozó eszközök (11) | A két profil a két termékkört fedi. | kifejezett választás |

Megfigyelés (nem jelöltük `pending_review`-nak, mert a donor ugyanaz a termékcsalád): Kapszulás kávéfőzők → 32 Eszpresszó kávéfőzők (létezik 104 Kávéfőzők is), Okos izzók → 365 Izzók (okosfunkciók nélkül). Döntés: nyitott kérdés.

### A `pending_review` jelölés hatása (implementáció: PR #18)

- Adat: [`backend/reference_data/donor_review.json`](../backend/reference_data/donor_review.json) – csomópont + donor párra szól; ugyanaz a donor más, ellenőrzött csomóponton (pl. 385 az Elöltöltős mosógépeknél) `reviewed` marad.
- A kategória-besorolás (CATEGORY-02A: kategóriatérkép, kézi döntés, eredeti/saját kategória) **nem változik**.
- Automatikus döntés (kategóriatérkép, kalibrált szabály, import, backfill, háttérbeli újrabesorolás) ilyen donort **nem tárol**; az ok: `parameter_profile_pending_review`.
- Kézi, kifejezett választással a donor tárolható, de a `parameter_profile_state` ekkor is `pending_review` – a dúsítási kapu csak `ready` állapotban nyílik.
- A donor jóváhagyása = a bejegyzés törlése a JSON-ból (Vezér/Tulajdonos döntése, külön PR-ban).
- A `/reference/navigation/{node}/parameters` böngésző nézet (profil megjelenítése) nem dúsítás, változatlan.

### Hiányzó paraméterek ellenőrzése a `pinfo_db`-ben (csak olvasás)

A Tulajdonos futtathatja egy csak olvasó felhasználóval; írás, DDL vagy migráció nincs.

```sql
START TRANSACTION READ ONLY;
-- 1) A kétes donorok és a lehetséges alternatívák paraméterei
SELECT c.emag_category_id, c.name AS kategoria, p.name AS parameter, p.is_mandatory
FROM emag_category_parameters p
JOIN emag_categories c ON c.id = p.category_id
WHERE c.emag_category_id IN (385, 673, 58, 63, 32, 104, 365, 146, 147, 1604, 1606, 2664)
ORDER BY c.emag_category_id, p.display_order;

-- 2) Ami a Szárítógépek (673) profilban megvan, de a Mosógépek (385) profilból hiányzik
SELECT p.name FROM emag_category_parameters p
JOIN emag_categories c ON c.id = p.category_id
WHERE c.emag_category_id = 673
  AND p.name NOT IN (SELECT p2.name FROM emag_category_parameters p2
                     JOIN emag_categories c2 ON c2.id = p2.category_id
                     WHERE c2.emag_category_id = 385);
ROLLBACK;
```

### `is_allowed = 0` donorok (tájékoztatás)

A CODEX 05 döntése szerint az `is_allowed` nem befolyásolja a fát és a profilválasztást. A 457 kategória donorjai közül **51** hozzárendelésnél `is_allowed = 0` az exportban (pl. 15 Mobiltelefonok, 14 Laptop / Notebook, 2920 Okosórák). A paraméterkészlet ettől elérhető (paraméterszám > 0), de ha az `is_allowed` a fiók feltöltési jogosultságát jelenti, piactéri feltöltésnél korlátozó lehet. Ez nyitott kérdés, nem változtattunk rajta.

<details><summary>Az 51 hozzárendelés listája</summary>

| Menüpont | Donor | Név |
|---|---:|---|
| Háztartási gépek és klíma > Hűtő-fűtő berendezések és vízmelegítők > Klímák | 410 | Klíma |
| TV és szórakozás > Házimozi és audió rendszerek > Hangszórók | 310 | Hangszórók |
| TV és szórakozás > Lejátszók, hangfalak, fej- és fülhallgatók > Vezetékes fej- és fülhallgatók | 155 | Vezetékes fejhallgatók |
| TV és szórakozás > Lejátszók, hangfalak, fej- és fülhallgatók > Hordozható hangfalak | 2588 | Hordozható hangszórók |
| TV és szórakozás > Konzolok és játékok > Konzolok | 152 | Hardver konzolok |
| TV és szórakozás > Konzolok és játékok > Hordozható játékkonzolok | 152 | Hardver konzolok |
| TV és szórakozás > Konzolok és játékok > Konzol és PC játékok | 37 | Játékok PC-re és konzolra |
| TV és szórakozás > Konzolok és játékok > Gamepad, botkormányok és fejhallgatók | 582 | Kontrollerek, kormányok és gaming fejhallgatók |
| TV és szórakozás > Konzolok és játékok > VR Gaming szemüvegek | 3419 | VR Gaming szemüvegek |
| Telefon, Tablet, Laptop > Telefonok > Okostelefonok | 15 | Mobiltelefonok |
| Telefon, Tablet, Laptop > Telefonok > Klasszikus mobiltelefonok | 15 | Mobiltelefonok |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Telefontokok | 2779 | Mobiltelefon tokok |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Kijelzővédő fóliák | 2773 | Képernyővédő fóliák |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Töltőkábelek | 2782 | Adatkábelek/ USB kábelek |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Töltőkábelek | 2780 | Töltők |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Külső akkumulátorok | 2771 | Külső akkumulátorok |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Telefon akkumulátorok | 2772 | Akkumulátorok |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Adatkábelek | 2782 | Adatkábelek/ USB kábelek |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Vezetékes fej- és fülhallgatók | 155 | Vezetékes fejhallgatók |
| Telefon, Tablet, Laptop > Mobiltelefon tartozékok > Egyéb tartozékok | 2774 | Egyéb kiegészítők |
| Telefon, Tablet, Laptop > Laptopok > Laptop, notebook | 14 | Laptop / Notebook |
| Telefon, Tablet, Laptop > Laptopok > Laptopok Windows-szal | 14 | Laptop / Notebook |
| Telefon, Tablet, Laptop > Tabletek és tartozékok > Tabletek | 73 | Tabletek |
| Telefon, Tablet, Laptop > Okosórák és okos eszközök, aktivitásmérők > Okosórák | 2920 | Okosórák |
| Telefon, Tablet, Laptop > Okosórák és okos eszközök, aktivitásmérők > Okos eszközök | 2920 | Okosórák |
| Telefon, Tablet, Laptop > Okosórák és okos eszközök, aktivitásmérők > Okos eszközök | 2925 | Okos otthon |
| Számítástechnika > Asztali PC és monitorok > Asztali számítógépek | 6 | Asztali számítógép |
| Számítástechnika > Gaming > Gamer PC-k | 6 | Asztali számítógép |
| Számítástechnika > Gaming > Gamer laptopok | 14 | Laptop / Notebook |
| Fotó-Videó, Okos eszközök > Fényképezőgépek > Tükörreflexes fényképezőgépek | 43 | Tükörreflexes fényképezőgépek |
| Fotó-Videó, Okos eszközök > Okosórák | 2920 | Okosórák |
| Fotó-Videó, Okos eszközök > Okosórák > Android kompatibilis okosórák | 2920 | Okosórák |
| Fotó-Videó, Okos eszközök > Okosórák > iOS kompatibilis okosórák | 2920 | Okosórák |
| Fotó-Videó, Okos eszközök > Okos eszközök > Okos otthon | 2925 | Okos otthon |
| Fotó-Videó, Okos eszközök > Okos eszközök > VR szemüvegek | 3419 | VR Gaming szemüvegek |
| Szupermarket > Online élelmiszerbolt > Alapvető élelmiszerek | 3989 | Alapvető élelmiszerek |
| Szupermarket > Online élelmiszerbolt > Tészták | 3998 | Tészták |
| Szupermarket > Online élelmiszerbolt > Konzervek és gyorsételek | 3991 | Konzervek és gyorsételek |
| Szupermarket > Online élelmiszerbolt > Diétás és bio termékek | 3993 | Diétás és természetes termékek |
| Szupermarket > Online élelmiszerbolt > Gabonapelyhek | 3997 | Gabonapehely és müzli |
| Szupermarket > Online élelmiszerbolt > Snackek | 3994 | Chips és ropi |
| Szupermarket > Online élelmiszerbolt > Édességek | 3097 | Édességek |
| Szupermarket > Alkoholmentes italok > Szénsavas üdítők | 4016 | Szénsavas üdítők |
| Szupermarket > Alkoholmentes italok > Szénsavmentes üdítők | 4017 | Szénsavmentes üdítők |
| Szupermarket > Online drogéria > Baba tápszerek | 3167 | Tápszerek |
| Szupermarket > Ajándékötletek > Csomagok és ajándékkosarak | 3094 | Csomagok és ajándékkosarak |
| Divat, ékszerek és kiegészítők > NŐI DIVAT > Női ruházat > Dzsekik, mellények | 4404 | Női mellények |
| Divat, ékszerek és kiegészítők > NŐI DIVAT > Női kiegészítők > Karórák | 2709 | Női karórák |
| Divat, ékszerek és kiegészítők > FÉRFI DIVAT > Férfi ruházat > Dzsekik és mellények | 4403 | Férfi mellények |
| Divat, ékszerek és kiegészítők > FÉRFI DIVAT > Férfi kiegészítők > Karórák | 2742 | Férfi karórák |
| Szépségápolás > Parfümök | 1241 | Parfüm |

</details>

## 98% küszöb: nem mért garancia

- Az admin küszöb alapértéke 0,98, de **egyetlen módszer sincs kalibrálva** (`CALIBRATED_PRECISION = {}`), így pontossági állítás nincs mögötte.
- Kalibrálatlan módszer semmilyen küszöbnél (0,5–1,0) nem sorol automatikusan; a javaslat `needs_review` + `uncalibrated_suggestion` marad, `confidence: null`.
- Automatikusan besorolt csak jóváhagyott kategóriatérképből vagy kézi döntésből lesz. Ezt a `test_98_percent_is_not_a_measured_guarantee_and_uncalibrated_rules_never_auto` teszt rögzíti.

## A #18 kódkockázatainak átnézése

| Kockázat | Megállapítás | Teendő |
|---|---|---|
| Szinkron újrabesorolás kategóriatérkép mentésekor | **Valódi blokkoló.** A régi kód egy kérésben, egy tranzakcióban sorolta újra a saját kategória összes termékét. SQLite-on a régi kóddal 50 000 termék 30,4 s. MySQL 8-on már a gyorsított szinkron út is ≈2 ms/termék (1000 termék: 1,99 s), így 50 000 terméknél legalább ≈100 s lenne. A frontend Nginx `proxy_read_timeout` 30 s → 504, miközben a tranzakció tízezres sorzárat tart az importtal szemben. | **Javítva a #18-ban:** 2000 termékig a kérésen belül, fölötte folytatható háttérfeladat (`product_jobs`), kötegenkénti committal, újabb döntésnél `superseded`. MySQL: a kérés 0,04 s, a feladat 50 000 terméket 104 s alatt dolgozott fel. |
| `product_backfill` CLI | **Hiba:** a `main()` az engine-gyárat adta át a `Session()`-nek, a parancs nem futott volna. | **Javítva a #18-ban**, regressziós teszttel. |
| 0009 migráció MySQL-en | Additív: új táblák + 4 oszlop, FK és index a `supplier_products`-on. Az alkalmazás-engine `read_timeout` értéke 5 s, ezért egyetlen DDL sem futhat 5 s-nál tovább. Mérés 50 000 terméken: **0,97 s**. | Nincs módosítás. Nagyobb táblánál előtte mérés javasolt (lent). |
| Backfill | Folytatható, kötegenként commitol. 50 000 termék: **215 s** (soronként ImportRow-olvasás). Lassú, de egyszeri és megszakítható. | Nincs blokkoló; telepítéskor ütemezett futtatás. |
| JSON forrásoszlopok | `source_attributes` tömör (raw, column, run_id, line, present); címke/mértékegység számított. | Nincs teendő. |
| `search_text` (q) | Szövegrész-keresés (`LIKE %…%`), index nélküli bérlői szűrés. 50 000 terméken lista + darabszám 0,39 s, keresés 0,21 s. | Nincs blokkoló; sebességgarancia nincs. |
| Downgrade | Döntések (térkép, esemény, zárolt besorolás) esetén megtagad. MySQL-en ellenőrizve. | Nincs teendő. |

A számok egyetlen gép (helyi MySQL 8.0.46) mérései, **nem garanciák**.

### Reprodukálható MySQL-mérés

`scripts/mysql_category02a_check.py` – csak eldobható, helyi MySQL 8 szerveren fut. Megtagadja a futást, ha a host nem loopback vagy az adatbázis nem üres. **Tilos a VPS-en, a közös fejlesztői adatbázison vagy a `pinfo_db`-n futtatni.**

```bash
docker run --rm -d --name a02c -p 127.0.0.1:33306:3306 \
  -e MYSQL_ROOT_PASSWORD=scratch -e MYSQL_DATABASE=adatdusito_dev mysql:8.0
export APP_DATABASE_URL='mysql+pymysql://root:scratch@127.0.0.1:33306/adatdusito_dev'
cd backend && PYTHONPATH=. python ../scripts/mysql_category02a_check.py --products 50000
docker rm -f a02c
```

Lépései: `alembic upgrade 0008` → N termék és importsor feltöltése → `upgrade 0009` → backfill → kategóriatérkép-döntés egy N termékes saját kategórián (szinkron vagy háttérfeladat) → lista + keresés → downgrade-védelem. Az adatbázis neve az alkalmazás ellenőrzése miatt `adatdusito_dev`, ezért kell külön, eldobható szerver.

Mért eredmény (2026-11-15, MySQL 8.0.46, 50 000 termék): upgrade 0009 0,97 s; backfill 214,85 s; térképmentés kérése 0,04 s (`queued`), háttérfeladat 103,67 s (50 000 módosult, 0 zárolt); lista 0,39 s; keresés 0,21 s; downgrade megtagadva.

## Nyitott kérdések a Vezér/Tulajdonos felé

1. A 3 `pending_review` donor (385 → Mosó-szárítógépek, 58 → Robotporszívók, 63 → IPL) jóváhagyható-e, legyen-e más donor (pl. 673 Szárítógépek külön profilként), vagy maradjon donor nélkül? A döntés előtt az SQL-lekérdezés eredménye segít.
2. Főzőedények: kell-e a fedők (1604), a kotyogós kávéfőzők (1843) külön profilja, és mi legyen a 0 paraméteres 3619-cel?
3. Dekorációk: elfogadható-e, hogy a két profilon kívül eső dekorációs termék csak kézi döntéssel, dúsítás nélkül kezelhető?
4. Kapszulás kávéfőzők (32 vs. 104) és Okos izzók (365) donorja maradhat-e?
5. Az `is_allowed = 0` (51 hozzárendelés) számít-e a jövőbeli piactéri feltöltésnél?
6. A 45 elem szabályai elemenkénti indoklás nélkül, egységes szöveggel kerültek be. Kell-e elemenkénti indoklás a szabályfájlba?
7. A 2000 termékes szinkronhatár megfelelő-e? Állítható konstans (`product_jobs.SYNC_REAPPLY_LIMIT`).
