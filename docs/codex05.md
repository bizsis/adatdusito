# CODEX 05 – Rögzített magyar kategóriafa, automatikus paraméterforrások

## A jóváhagyott fa az elsődleges

A `backend/reference_data/curated_taxonomy.json` **változatlan** marad: 13 főcsoport,
584 pont, 571 él, legfeljebb 4 szint. Mindegyik pont az eredeti néven, azonosítóval,
sorrendben és szülővel jelenik meg, akkor is, ha nincs hozzá forrásparaméter.
A 171 strukturális pont (a főcsoportokkal együtt) nem igényel paraméterkapcsolatot.
A további 413 pont termékkategória; a korábban külön elfogadott szűrőeredetű
strukturális pontok továbbra is navigációs szerepűek.

Az eMAG-forrás `is_allowed` mezője **sem a megjelenést, sem az automatikus
paraméter-hozzárendelést nem korlátozza**. A forrás nem kategóriafa-alakító,
hanem paraméter-/értéktár. Forrásból származó `ref-emag-*` csomópontok nem bővítik
a felhasználói fát; az összes eredeti kategória és paraméterkapcsolat megmarad az
adatkönyvtárban. A korábbi aktív-only kísérlet nem került commitba vagy a VPS-re.

A megjelenítés közvetlenül a jóváhagyott JSON szerkezetét vetíti a meglévő
saját katalógusra. A korábban tárolt adminisztrátori szülőmódosítás sem írja ezt
felül; az eredeti döntés rekordját nem töröljük automatikusan. Új szülőmódosítást
az API is elutasít. A paraméterforrásra vonatkozó döntések viszont megmaradnak.

## Paraméterek és értékek

Az egyértelmű név-, alias- és útvonal-egyezések automatikusan hozzárendelik a
paraméterforrást, az `is_allowed` értékétől függetlenül. A gyűjtőpontok nem örökölnek
paramétereket a gyermekeiktől. A más forráskategóriához tartozó megengedett értékek
nem keverednek; a meglévő saját kategóriaparaméter- és értékkapcsolatok olvasódnak.

Konkrét javítás: a `Számítástechnika / Asztali PC és monitorok / Asztali számítógépek`
útvonalhoz a „Asztali számítógép” forráskategória (eMAG 6) egyértelmű nyelvtani
alias alapján kapcsolódik. A korábbi export szerint ez 70 paramétert tartalmaz,
bár a forrásjelzője `is_allowed=0`. A gyűjtőpont felirata „Navigációs gyűjtőpont”,
nem „Összerendelésre vár”. A TV továbbra is a saját 46 paraméterét használja.

Az adminisztrátor a kiválasztott termékkategóriánál **egyetlen paraméter-hozzárendelő
szerkesztőt** használhat: forráskeresés, választás, mentés, visszaállítás automatikusra.
Nincs szülőkeresés, kategória-áthelyezés, hash-bekérés vagy második kategóriaböngésző.
A forrásválasztóban az inaktív jelzőjű, megfelelő paraméterforrás is választható.

Kizárólag a több lehetséges forrású, ténylegesen bizonytalan kapcsolatok kerülnek
a felülvizsgálati nézetbe. A paraméter nélküli gyűjtőpont nem feladat. Az egyelőre
megfelelő forrás nélküli termékkategória látható marad, „Paraméterkészlet még nem
érhető el” jelzéssel; ez önmagában nem kézi ellenőrzési felszólítás.

A **„Paraméterforrás még nem érhető el” kártyára kattintva** megnyílik az érintett
kategóriák aktuális listája. A Nézet mezőben ugyanez „Paraméterforrás nélküli
kategóriák” néven választható. Minden sor a kategórianevet és a teljes szülői
útvonalat mutatja; kattintással megnyitható a meglévő paraméter-hozzárendelési
szerkesztő. A lista kereshető és lapozható; a keresés a kiválasztott szűrésen belül
marad. Gyűjtőpont és többértelmű hozzárendelés nem kerül ebbe a listába. A számláló
és a lista ugyanabból az aktuális katalógusból készül, nem az offline jelentésből.
A „Bizonytalan paraméter-hozzárendelés” kártya szintén megnyitható.


A stabil kategóriaazonosság a rögzített `navigation_id` / `category_key`.
A kiválasztási API `canonical_reference_key` mezője `fixed_category:<azonosító>`;
ez a paraméterforrás megváltoztatásakor sem változik. A kompatibilitási numerikus
mezők a meglévő saját katalógusazonosítókat őrzik; a külön
`parameter_source_category_id` a paraméterforrást jelöli. A következő termékimport
fázis a rögzített kategóriakulcshoz kapcsolódhat, nem a forrás aktív/inaktív állapotához.

## Offline lefedettség

A korábban átadott kategóriaexporton, helyi adminisztrátori döntések nélkül:

| Mérés | Darab |
|---|---:|
| Rögzített, látható pont | 584 / 584 |
| Főcsoport | 13 |
| Strukturális pont, főcsoportokkal | 171 |
| Hozzárendelt paraméterforrású termékkategória | 280 |
| Ebből tényleges paraméterkészlettel | 273 |
| Bizonytalan paraméter-hozzárendelés | 5 |
| Egyelőre forrás nélküli termékkategória | 128 |
| Megőrzött forráskategória | 2669 |
| Az exportban jelzett forrás-paraméterkapcsolat | 29398 |
| Forrás alapján hozzáadott felhasználói kategória | 0 |

A 171 + 280 + 5 + 128 = 584 felosztás az összes jóváhagyott pontot lefedi.
A 280 kapcsolat között 7 olyan forrás van, amelynek az export nulla paramétert jelez.
Az 5 bizonytalan pont: Kutyaeledel; Nyakörvek, pórázok, hámok; Étkészletek; Tálak;
Ablaktörlők. A részletes jelöltek és a 128 hiányzó kapcsolat útvonalai:
[codex05-parameter-bindings.json](reports/codex05-parameter-bindings.json).
A jelentés a 2669 kategóriás exportot használja; élő VPS-adatot nem kérdeztünk le.

Újramérés másik, még nem létező kimeneti fájllal, adatbázisírás nélkül:

```bash
python scripts/report_fixed_categories.py \
  --export backend/tests/fixtures/emag_categories_export.tsv \
  --output /tmp/codex05-parameter-bindings.json
```

## Telepítési határ

**Nem szükséges új import, új katalógusverzió, új aktiválás vagy migráció.**
A javított backend és frontend a már betöltött saját katalógusadatait használja.
A 2 847 054 értékrekordot nem másolja, nem módosítja, nem importálja újra.
Kizárólag az adminisztrátor által kezdeményezett paraméterforrás-módosítás ment
`CategoryOverride` és auditadatot; a kategória- és értékrekordok változatlanok.

**A VPS-en nem hajtottunk végre műveletet.** `.env`, Compose external hálózat,
MySQL, Nginx, HTTPS és a `pinfo.hu` környezet változatlan.

## Automatizált ellenőrzés

- Mind az 584 név, azonosító, sorrend és szülő változatlansága, a teljes forrásállomány
  `is_allowed` mezőjének 0/1/NULL értékre állítása mellett is, szintetikus másolatokon.
- Inaktív Desktop-forrás: 70 paraméter, kötelező/opcionális jelzők és meglévő
  megengedett értékek, örökölt és saját adatolvasásban.
- Paraméterforrás szerkesztése/visszaállítása: változatlan kategóriaútvonal és kulcs,
  változatlan forrás-/célértékek, paraméterkapcsolatok és tárolt kategóriapontok.
- Szülőmódosítás elutasítása; korábban rögzített szülődöntés nem változtatja meg a fát.
- Keresés kizárólag a fix fában; forrásból új csomópont nem jelenik meg.
- Csak ténylegesen többértelmű paraméterkapcsolatok a kézi felülvizsgálati listán.
- Asztali/mobil böngészőben a 13 gyökér, igény szerinti kibontás, Desktop 70 és TV 46
  paramétere, paraméterérték-keresés, az egyetlen szerkesztő és a szülőmezők hiánya.

A korábbi tesztek forrásból létrehozott csomópontokat és áthelyezési felületet
ellenőrző elvárásai a CODEX 05 szerint módosultak; a forrásparaméterek továbbra is
külön tesztelve, az eredeti azonosítóikon elérhetők az adatkönyvtárban.
A 2,85 milliós éles adathalmazt ezen fejlesztés során nem mértük vagy módosítottuk;
az adatmegőrzési tesztek eldobható tesztadatbázisokon futnak.

Végső ellenőrzés, 2026-11-13: `npm --prefix frontend run build` sikeres;
`PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests`:
**138 sikeres teszt**, 113,99 másodperc alatt. Egy meglévő Starlette/AnyIO elavulási
figyelmeztetés, teszthiba nélkül. A módosított Python-fájlok Ruff-ellenőrzése és a
`git diff --check` sikeres. A jóváhagyott kategória-JSON, migrációk és Compose nem
változtak.

A frontend végső TypeScript-típusjavítása után a build ismét sikeres lett, majd
mind a 6 asztali/mobil böngészőteszt az új frontend-artifacttal is sikeresen
lefutott (46,04 másodperc).
