# CODEX 04B – Rögzített közös kategóriahierarchia

## Adatforrás és hatókör

A `backend/reference_data/curated_taxonomy.json` a felhasználó 13 menüképből
leírt struktúrájának verziózott, géppel feldolgozható reprezentációja (`04B.1`).
Az eredeti export és a `web_navigation.json` változatlan. Új webes gyűjtés nincs.
A leírás SHA-256 lenyomata belső eredetnapló; a felületen nem kell hash-t megadni.

A 13 főcsoport és sorrendjük változatlan. A váz **584 navigációs pontot és 571
szülő–gyermek élt** tartalmaz, legfeljebb 4 szinttel. Mind az 584 meglévő menüazonosító
megmarad. A korábban kétértelmű női tornacipő/férfi nadrág menüpont identitását az
archivált, nemi ághoz tartozó forráshivatkozás rögzíti, nem új eMAG-azonosító.

A felhasználó külön megerősítése alapján 65 strukturális pont szerepel a vázban:
a gyűjtőcímek, valamint a név szerint előírt, eredetileg szűrőhivatkozások
(pl. elöltöltős mosógép, Windows laptop, Android/iOS óra). Ezekhez nincs automatikus
pontos forrásmegfeleltetés és nem választhatók termékbesorolásra.

A TV-technológiák/felbontások továbbra sem kategóriák. A televízió adatlapján
külön kapcsolódó szűrőként szerepelnek. Kapcsolat csak az adott TV-kategóriához
ténylegesen tartozó, megfelelő nevű paraméter és egyértelmű megengedett érték
alapján jön létre. Hiány vagy többértelműség esetén nincs kitalált paraméterazonosító.
Márka-, kampány-, termékkereső és egyéb kihagyott menühivatkozás nem kerül a fába.

## Reprodukálható lefedettség

Forrás: a korábban átadott, 2669 soros kategória-TSV; adminisztrátori helyi döntések
nélkül. Részletes lista: [codex04b-coverage.json](reports/codex04b-coverage.json).

| Mérés | Darab |
|---|---:|
| Megőrzött eredeti forráskategória | 2669 / 2669 |
| Elhelyezett egyedi forráskategória | 2006 |
| Ebből aktív, besorolható forráskategória | 1688 / 1749 |
| Többértelmű egyezés miatt felülvizsgálandó forráskategória | 5 |
| További, el nem helyezett forráskategória | 658 |
| Összesen nem elhelyezett forráskategória | 663 |
| Többértelmű menüpont | 5 |
| Paraméterkészlettel rendelkező forráskategória | 1807 |
| Ebből elhelyezett | 1677 |
| Exportban jelzett kategóriaparaméter-kapcsolat | 29398 |
| Automatikusan megfeleltetett egyedi forráskategória | 296 |
| Név- vagy kontextusalias alapján megfeleltetett menüpont | 37 |
| Több helyen megjelenő, közös identitású forráskategória | 10 |
| Rögzített vázból el nem helyezett navigációs pont | 0 |
| Rögzített menüidentitás ütközése | 0 |

A teljes összevezetett fa legnagyobb mélysége 5; a megadott menüvázé 4.
A 663 el nem helyezett forráskategóriából 61 aktív. A többi inaktív vagy archivált;
ezek állapota megmarad, nem kerülnek gyökérszintre. A keresésben és az elkülönített
felülvizsgálati/archív nézetben továbbra is hozzáférhetők.

A többértelmű menüpontok: Kutyaeledel; Nyakörvek, pórázok, hámok; Étkészletek;
Tálak; Ablaktörlők. A jelöltek és az eredeti szülők a JSON-jegyzőkönyvben szerepelnek.
A „Nagyítók” előírt szülője biztos, de a „Nagyítók és optikai eszközök” (318)
forráskategória tágabb fogalom, ezért nincs automatikus pontos paraméterkapcsolat.

A paraméterkészlet nélküli strukturális pont nem örökli gyermekei paramétereit.
A laptopmemória és asztali memória, a hálózati/elektromos kapcsoló, valamint a
női/férfi/gyermek ágak a teljes útvonal szerinti egyeztetést használják.
Az azonos kategória több megjelenési helye ugyanazt a saját kategóriaazonosítót
és paraméterkészletet használja. Korábbi strukturális helyazonosítók aliasai
megmaradnak, ha egy későbbi verzióban pontos forráskapcsolatot kapnak.

A TSV nem tartalmazza a paraméterdefiníciók teljes rekordjait vagy a megengedett
értékeket. A **2 847 054 érték** megléte korábbi felhasználói mérés; ebben a feladatban
nem történt éles import vagy teljes értékellenőrzés. A 46 TV-paramétert, a 15/31
kötelező/opcionális bontást és az értékkeresést szintetikus adatbázison teszteljük;
a valós kategóriaexport a TV-hez szintén 46 paramétert jelez.

Offline újramérés (adatbázisírás nélkül, új kimeneti fájllal):

```bash
python scripts/report_unified_categories.py \
  --export backend/tests/fixtures/emag_categories_export.tsv \
  --curated --output /tmp/codex04b-coverage.json
```

## Verziózás a meglévő CODEX 04 adatmodellben

Nincs új tábla, modell vagy Alembic-migráció. A `0001`–`0005` migrációk változatlanok.
A teljes import új tervlenyomat esetén új verziót készít, a korábbit nem írja felül.
Megváltozott tervvel félbeszakadt paraméter/érték-import nem folytatható vegyes fával.

A már befejezett CODEX 04 saját katalógushoz a `rebuild` művelet **csak új faverziót**
készít. A forráskategóriák saját adatbázisban tárolt metaadataiból dolgozik,
`pinfo_db`-kapcsolatot sem nyit. A `catalog_versions.counters.data_version_id`
a már ellenőrzött, változatlan paraméter- és értékkapcsolat-verzióra mutat.
Nem másolja vagy módosítja a több millió értéket, a jelzőket, a forráskapcsolatokat
vagy az eredeti saját azonosítókat. A lánc hiánya/ciklusa hiba, nincs forrásadatbázisra
visszaesés. Újrafuttatás nem duplikálja a közös entitásokat.

Az előkészítés és az aktiválás külön művelet. Az aktív verzió nem változik az
előkészítéstől. A korábbi adminisztrátori megfeleltetések és szülődöntések megmaradnak.
Ha egy korábbi explicit szülődöntés ellentmond a most előírt élnek, az előkészítés
hibával, visszagörgetve megáll: a döntést és az aktív verziót nem írja felül csendben.

**Ebben a munkában nem történt VPS-telepítés, adatimport, faújraépítés vagy aktiválás.
A tesztek kizárólag saját, eldobható tesztadatbázisokat hoznak létre.**
A Git-frissítés önmagában ezért nem változtatja meg az aktív adatverzió fáját.

Későbbi, külön engedélyezett üzemeltetői lépéshez:

```bash
# Csak a verziók állapotának kiolvasása:
docker compose exec backend python -m app.catalog_import status
# A további lépések még NINCSENEK végrehajtva.
# Előkészítés egy kész, ellenőrzött CODEX 04 saját adatverzióból:
docker compose exec backend python -m app.catalog_import rebuild --version KORABBI_VERZIO
# A kiírt új verzió ellenőrzése után külön aktiválható:
docker compose exec backend python -m app.catalog_import activate --version UJ_VERZIO
# Visszaállás ugyanezzel a paranccsal a korábbi verzióra lehetséges.
```

`.env`, Compose, external hálózat, VPS/MySQL/Nginx/UFW/HTTPS és ügyféladatok változatlanok.

## Ellenőrzési jegyzőkönyv

2026-11-13, izolált felhőbeli tesztkörnyezet:

- `npm --prefix frontend run build`: TypeScript-ellenőrzés és Vite build sikeres.
- `PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests`:
  **119 sikeres teszt**, 105,24 másodperc. Egy meglévő Starlette/AnyIO elavulási
  figyelmeztetés, teszthiba nélkül.
- A módosított Python-fájlok Ruff-ellenőrzése és `git diff --check` sikeres.
- Kötelező kategóriaútvonalak, mind az 571 rögzített él, 2669 megőrzött kategória,
  ismétlődő nevek/nemi ágak és kizárt TV-szűrők ellenőrizve.
- Korábbi menüverzióból új struktúra előkészítése; változatlan aktív verzió,
  megőrzött közös azonosítók; ismételt előkészítéskor nincs entitásduplikáció,
  paraméter-/értékkapcsolat-másolat vagy referencia-adatbázis-hozzáférés.
- Adminisztrátori döntések megőrzése és ellentmondó szülődöntés atomikus elutasítása.
- TV 46 paramétere, kötelező/opcionális jelölések, kategóriánként elkülönített,
  kereshető és lapozott értékek, új terv miatti új verzió létrehozása.
- Chromium asztali (1440×1000) és mobil (390×844) teszt, örökölt és saját katalógus:
  13 induló főcsoport, igény szerinti kibontás; saját verzióban a mosógépútvonal,
  strukturális állapot, TV-paraméterek, értékkeresés, adminisztrátori besorolás;
  JavaScript-hiba és vízszintes túlnyúlás nélkül.

## MySQL 8 végső ellenőrzésének indexjavítása

Az első VPS-import végső egyediérték-összesítésénél a MySQL a PRIMARY indexet
választotta, a kliens pedig 2013-as időtúllépéssel megszakadt. Az üzemeltető által
mért `FORCE INDEX (ix_catalog_mapping_targets)` lekérdezés 613410 különböző értéket
adott 11,219 másodperc alatt.

A `verify_version()` egyediérték-számlálása MySQL alatt most kifejezetten ezt a
meglévő, `(version_id, kind, target_id)` fedőindexet kéri. A szűrés és a
`COUNT(DISTINCT target_id)` jelentése változatlan. Mivel a mért idő az általános
5 másodperces klienskorlátot is meghaladja, kizárólag ez az egy összesítés kap
külön, legfeljebb 60 másodperces olvasási időkeretű kapcsolatot az
alkalmazás-adatbázishoz. A kapcsolat siker és hiba esetén is lezárul. A többi
ellenőrzés, az API-kapcsolatok időkorlátja és a referencia-adatbázis kezelése nem
változik. SQLite tesztkörnyezetben ugyanaz a meglévő session marad használatban,
MySQL-specifikus SQL nélkül.

Nincs új index/migráció, új import, törlés vagy aktiválás. A meglévő `building /
verify` verzió a javított kóddal a `verify --version 1` művelettel ellenőrizhető
újra; siker esetén az eredeti működés szerint `ready / complete` lesz, de ettől
még nem válik aktívvá. Ezt az üzemeltetői műveletet a fejlesztés során nem futtattuk.

Célzott ellenőrzés: **19 sikeres teszt** (`test_catalog_verification_index.py`,
`test_owned_catalog.py`, `test_curated_taxonomy.py`), valamint sikeres Ruff és
`git diff --check`. A MySQL SQL-fordítás, az indexhint, a külön időkeret és a
kapcsolat lezárása tesztelt; élő VPS-lekérdezést nem futtattunk.

A teljes ellenőrzési folyamat további optimalizálását, a mentett kötegeket,
automatikus folytatást és az 1-es verzió ellenőrzőparancsait a
[folytatható katalógusellenőrzés útmutatója](catalog-verification.md) írja le.
