# TEMPLATE-01 – Adatdúsítás előtti munkasablon

Az RC02-re épülő fejlesztés ugyanazt a tárolt forrásfájlt és streaming CSV/XLSX-olvasót használja, mint az import. A sablon nem termékimport és nem AI-feladat: nem hagy jóvá importot, nem változtat termékadatot, nem készít kutatási feladatot és nem fogyaszt kreditet.

## Folyamat és adatmodell

A `supplier.import` worker a sikeres elemzés/feldolgozás után külön `supplier.template` feladatot küld. Az `import_templates` verziózott pillanatképe az importhoz tartozik; az import korábbi állapotai változatlanok. A sablon saját állapota `queued → building → ready_for_enrichment`, hiba esetén `failed`. Újragenerálás új pillanatképet ad, az előző letöltési URL érvényes marad. A munkasablon csak a kész állapot tranzakciójában válik letölthetővé.

A CSV/XLSX-fájlok 60 000 bájtos `import_template_chunks` darabokban az alkalmazás-adatbázisban tárolódnak. A forrásfájl megőrzési idejének lejárta a már elkészült sablont nem törli. Az RC02 szabályai szerint törölhető, még jóvá nem hagyott import törlése az új táblákat FK-kaszkáddal együtt törli; feldolgozott import továbbra sem törölhető.

Az `0012_import_templates` kizárólag két új alkalmazástáblát és egy indexet hoz létre. Az `0001`–`0011`, a `pinfo_db`, a meglévő katalógusértékek és a Docker-hálózat változatlanok. Visszaállítás előtt a letöltött sablonokat mentsük: az `alembic downgrade 0011` csak az új sablontáblákat szünteti meg.

## Oszlopok és adatok

1. Minden eredeti oszlop, fejléc (ismétlődő és üres is), érték és adatsor az eredeti sorrendben marad. A fejléc előtti bevezető sorok a forrásfájlban maradnak, nem terméksorok. Az üres, fejléc utáni sorok a sablonban is megmaradnak, de nem számítanak terméknek. A fejlécnél szélesebb adatsorok többletoszlopai üres eredeti fejléccel megmaradnak.
2. A kért öt kötelező és tizennégy javasolt UNAS-munkamezőből csak a még nem megfeleltetettek kerülnek új oszlopba. Egyértelmű név/szűk alias alapján automatikus, oszlopindex alapján kézi megfeleltetés lehetséges. Két azonos UNAS-fejlécnél a felhasználónak kell választania. Beszerzési ár, listaár vagy adóalap nélküli általános ár nem válik automatikusan eladási nettó/bruttó árrá. Ismeretlen mező üres, ár/ÁFA/SEO/státusz nem lesz kitalálva.
3. A ténylegesen hozzárendelt, jóváhagyott donorprofilok paramétereinek uniója következik. A paraméterkulcs `(donor eMAG-kategóriaazonosító, eMAG-paraméterazonosító)`, ezért a különböző kategóriák paraméterei névegyezés miatt sem olvadnak össze. Megmarad a linkazonosító, kötelező jelleg, sorrend, szűrőjelölés, újérték-szabály és katalógusverzió. Pontos, egyértelmű forrásfejléc-egyezés esetén a hozzárendelt profil saját sorához az eredeti érték másolható; egyébként a paramétercella üres.

Az eMAG-paraméterek az alkalmazás meglévő aktív, ellenőrzött közös katalógusából jönnek. Ez a három eMAG-forrástáblából korábban importált adatokat használja; nincs új referenciaimport vagy több millió megengedett érték másolása. A megengedett értékek továbbra is az alkalmazás meglévő kereső/lapozó végpontjain érhetők el. A három `pending_review` donor védelme változatlan.

A feldolgozott termékek elfogadott besorolását automatikusan használjuk. Elemzés után, még importjóváhagyás előtt fájlszintű alapértelmezett és fizikai forrássorhoz kötött kategória választható. A sorbeállítás elsőbbséget élvez. Ez **csak a sablonhoz tartozik**, nem írja át a jóváhagyott termékbesorolást. Kategóriaválasztás nélkül az UNAS-alapmezők már letölthetők; a paraméterhiány látható figyelmeztetés.

## Formátumok és korlátok

Az XLSX cellái explicit szövegek. A meglévő parser megőrzi a szöveges azonosítókat és az Excel `000000` típusú vezetőnulla-formátumát; képletek szó szerinti szövegek, nem végrehajtható képletek. A forrásban korábban már elveszett számjegyek nem rekonstruálhatók. Az eredeti munkafüzet/fájl változatlanul letölthető az RC02-felületről.

A CSV UTF-8 BOM, pontosvesszős, minden mező idézőjelezett. Szövegként kell importálni Excelbe; az automatikus Excel-számfelismerést a CSV formátum nem képes kikapcsolni. Az XLSX az ajánlott azonosítómegőrző letöltés. A CSV szó szerint őrzi a képletjellegű forrásszöveget is; ezt a felület jelzi.

A generátor két streaming menetet és ideiglenes fájlokat használ, nem épít teljes adattáblát memóriába. Legfeljebb 10 előnézeti sor, XLSX szerint 1 048 575 adatsor/16 384 oszlop, fájlonként 200 MiB megengedett. A 32 767 karakternél hosszabb vagy XLSX-ben érvénytelen cellánál hiba keletkezik, nincs csonkítás. A DB-be írt darabok és kész állapot együtt commitolódnak. Egy worker egyszer foglalhatja le a pillanatképet. Megszakadt worker után 30 perc múlva új pillanatkép kérhető; a félkész fájlok soha nem szolgálhatók ki.

**Ez adatdúsítási munkatábla, nem végleges UNAS-importfájl.** A kért `Alternatív Kategória 1.` munkamezőt megőrizzük, de nem állítjuk, hogy ez támogatott natív UNAS-importfejléc. A korábban átadott UNAS-minta például `Kiegészítő Kategóriák` mezőt tartalmaz. A meglévő exportmotor-profilok nem változnak; a végleges UNAS-export külön, igazolt mezőnevekkel/formátumokkal készítendő.

Az RC02-ben nincs tényleges AI-kutatást indító végpont. Az előírt „Adatdúsítás indítása” gomb ezért magyarázattal letiltott; nem indít helyette más műveletet. A meglévő paraméter-előkészítés és jóváhagyás működését nem változtatjuk meg.

## API és jogosultság

- `GET /api/v1/imports/template-categories`: a meglévő közös fa választható kategóriái/profiljai.
- `GET /api/v1/imports/runs/{id}/template`: legfrissebb pillanatkép, oszlopséma, megfeleltetések, kategória/profileredet, előnézet és figyelmeztetések.
- `POST /api/v1/imports/runs/{id}/templates`: új pillanatkép, opcionális `mapping: {UNAS-mező: eredeti_oszlopindex}`, `category: {node_id, donor?}`, `rows: {fizikai_sorszám: {node_id, donor?}}`.
- `GET /api/v1/imports/runs/{id}/templates/{template_id}/{csv|xlsx}`: ismételhető letöltés.

Olvasás/letöltés: `imports.read`, létrehozás: `imports.create`, kategóriaválasztás ezen felül `products.classify`. Minden import tenant- és teljes erőforrás-hozzáféréshez kötött; Origin/CSRF/no-store védelem változatlan. Másik tenant vagy másik import pillanatképe 404. Futó import mellett új generálás nem kérhető. Hiba nem módosítja az import állapotát és nem teszi elérhetetlenné a korábbi pillanatképeket.

## Ellenőrzés

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
npm --prefix frontend run build
npm --prefix frontend run lint
npm --prefix frontend test
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_import_templates.py backend/tests/test_template_preparation_api_browser.py
```

Az új migrációt SQLite round-trip teszt, a tényleges MySQL FK-kaszkádot és generálást az elkülönített RC02 MySQL CI-próba ellenőrzi. Ez a próba kizárólag üres, helyi teszt-MySQL-en futtatható; nem VPS-telepítési parancs. A meglévő MySQL migrációs CI-job változatlan. Az új downgrade a régebbi revíziók döntésvédelmeit több lépéses visszaállításnál még az első DDL előtt ellenőrzi; MySQL-en a táblával együtt távolítja el az idegen kulcshoz szükséges indexet.

Telepítéskor az `0012` upgrade és a backend/worker/frontend újraépítése szükséges, a szokásos mentési/PR-jóváhagyási folyamatban. Ebben a fejlesztésben nem történt VPS-művelet vagy `.env`-módosítás.
