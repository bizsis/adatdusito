# A magyar eMAG vásárlói főmenü begyűjtése saját gépről

Az emag.hu 13 vásárlói főcsoportja nem azonos a Marketplace-adatbázis gyökereivel. Például a „TV és szórakozás” menücsoportot nem szabad név alapján kitalált Marketplace-szülőként beírni. Először a nyilvános menüt és az almenük tényleges kapcsolatait gyűjtjük be, utána lehet azokat az egyetlen közös referenciafába ellenőrzötten illeszteni.

A gyűjtő nem módosítja az Adatdúsító felületét vagy adatbázisát. Nem olvas `.env` fájlt, nem használ API-kulcsot és nem ment sütit, böngészőprofilt vagy localStorage-ot. A szokásos eMAG-böngészéshez nem kell bejelentkezned. A program csak a kezdőlap menüjét nyitogatja; nem járja be a termékkatalógust, és nem követi a kategória-/terméklinkeket.

## 1. Ajánlott: Windows PowerShell + saját Chrome

Ne a VPS-en kezdd: a saját gépeden a böngésző látható, kezelni tudod a sütikérdést, és a hozzáférésed is ellenőrizhető. Python 3.10+ és Git szükséges. Meglévő Chrome esetén külön Chromium-letöltés nem kell.

Új könyvtárban:

```powershell
git clone https://github.com/bizsis/adatdusito.git adatdusito-menu
cd adatdusito-menu
py -m venv .menu-venv
.\.menu-venv\Scripts\python.exe -m pip install -r scripts/browser-requirements.txt
.\.menu-venv\Scripts\python.exe scripts/export_emag_menu.py --channel chrome --output "$env:USERPROFILE\Desktop"
```

Ha a friss repository már a gépeden van, annak könyvtárából az utolsó három parancs elég. Git nélkül a GitHub **Code → Download ZIP** funkciójával is letöltheted és kicsomagolhatod a projektet. Ha a `py` parancs nem található, telepített Python esetén próbáld helyette a `python` parancsot.

1. Megnyílik egy új, ideiglenes böngészőablak.
2. Kezeld az eMAG sütikérdését. Ne jelentkezz be, maradj a főoldalon.
3. A PowerShell-ablakban nyomj Entert.
4. A program megnyitja a Kategóriák menüt és a DOM-ban valóban megtalált főcsoportok fölé viszi az egeret, legalább egy másodperces szünetekkel.
5. A konzol kiírja a mentett főcsoportokat és a ZIP pontos elérési útját.

A kimenet egy új, időbélyeges `emag-menu-...` mappa az Asztalon; korábbi eredményt nem ír felül. A mappában lesz az **`emag-menu-export.zip`**. Ezt add át a fejlesztéshez.

Chrome helyett Edge:

```powershell
.\.menu-venv\Scripts\python.exe scripts/export_emag_menu.py --channel msedge --output "$env:USERPROFILE\Desktop"
```

Ha egyik sincs telepítve, a Playwright saját Chromiumja is használható:

```powershell
.\.menu-venv\Scripts\python.exe -m playwright install chromium
.\.menu-venv\Scripts\python.exe scripts/export_emag_menu.py --output "$env:USERPROFILE\Desktop"
```

## 2. Ha az automatikus hover nem működik: kézi mód

```powershell
.\.menu-venv\Scripts\python.exe scripts/export_emag_menu.py --channel chrome --manual --output "$env:USERPROFILE\Desktop"
```

Az első Enter után nyisd ki a Kategóriák menüt. Sorban vidd az egeret mind a 13 főcsoport nevére, várd meg az almenüt, és még a név fölött állva nyomj **Alt+Shift+M**-et (alternatíva: F8). A böngésző konzolja jelzi a mentést. Ha mindegyik kész, a PowerShellben nyomj Entert; elkészül a ZIP.

A menü aktuális szerkezete eltérhet a szintetikus tesztektől. Ha a gyűjtő nem találja a panelt, a `--panel-selector` opcióval a valódi, aktív almenü CSS-szelektora adható meg. Ezt a DevTools Elements paneljén kell ellenőrizni; a `body` és `html` használatát a program tiltja. A hiba/hiány is megmarad a jelentésben. Nem talál ki hiányzó menüket.

## 3. Telepítés nélküli, saját böngészős DOM-export

Ez a kézi változat csak a már megnyitott menü DOM-ját olvassa; nem indít külön HTTP-letöltést vagy robots-lekérdezést. Akkor használható, ha a nyilvános eMAG-oldalt a szokásos módon meg tudod nyitni. Hozzáférési tiltás vagy CAPTCHA megkerülésére nem szolgál.

1. Nyisd meg az emag.hu főoldalát, lehetőleg bejelentkezés nélkül.
2. A projektben nyisd meg a `scripts/emag_menu/menu_capture.js` fájlt, ellenőrizd, majd másold be a saját böngésződ **F12 → Console** felületére, és futtasd.
3. Kattints vissza az oldalra, nyisd ki a Kategóriák menüt.
4. Főcsoport fölé egér → megjelenő almenü → **Alt+Shift+M**. Ismételd mind a 13 főcsoporttal. F8 is támogatott, de a DevTools ezt lefoglalhatja.
5. **Alt+Shift+E** (vagy F9) letölti az `emag-menu-export-....json` fájlt. Ezt add át. A JSON a tisztított menü-HTML-t is tartalmazza.

Haladó diagnosztika a konzolban:

```javascript
AdatdusitoMenuCapture.discover()  // a DOM-ban ténylegesen látható főcsoportok
AdatdusitoMenuCapture.report()    // mentések, hiányok, duplikált panelek
AdatdusitoMenuCapture.diagnostics() // technikai DOM-szelektorok, oldal-/fióktartalom nélkül
// Csak a valódi, előzőleg ellenőrzött panel szelektorát add meg:
// AdatdusitoMenuCapture.setPanelSelector('...')
```

## Mit tartalmaz az export?

- A ténylegesen megfigyelt főcsoportneveket és DOM-sorrendet. A 13 megadott név ellenőrzőlista, nem automatikusan legyártott adat.
- Főcsoportonként a látható menühivatkozásokat és a DOM-ból bizonyítható szekciócsoportosítást.
- Nyilvános URL-útvonalakat és explicit forrásattribútumokat. A queryértékek és fragmentek nincsenek mentve.
- Tisztított menü-HTML-t; automatikus módban, sikeres rögzítésnél a menüpanel képernyőképét is.
- Időpontokat, HTML-hash-eket, hiányzó csoportokat, azonos tartalmú panelek jelzését és feldolgozási hibákat.

A menüben **Brand shopok, kampányok és Termékkeresők is lehetnek**. Ezeket nem nyilvánítjuk automatikusan termékkategóriának. Egy numerikus `/c/79` URL vagy `data-category-id=79` attribútum sem kap ellenőrzés nélkül Marketplace-megfeleltetést: a `canonical_emag_id=null`, a `mapping_status=pending` marad. A vizuális elrendezés önmagában nem bizonyít teljes kategória-szülőkapcsolatot.

Az `all_expected_panels_captured=true` csak azt jelzi, hogy mind a 13 megadott csoporthoz készült felvétel. A `full_category_tree_verified` mindig false ebben a gyűjtőben. Az ismeretlen panelkapcsolatok és az azonos paneltartalmak ellenőrzést igényelnek. A program 2-es kóddal tér vissza, ha hiány, duplikált panel vagy hiba maradt; a részleges csomagot ilyenkor is megőrzi.

Az automata a robots.txt-t is ellenőrzi. Ha nem elérhető, HTML-ellenőrzőoldalt kap helyette vagy a szabály nem engedi a kezdőlapot, leáll. Nem használ stealth plugint, nem kapcsolja ki a TLS-ellenőrzést és nem old meg CAPTCHA-t automatikusan. A menüexport célja a már hozzáférhető vásárlói navigáció megfigyelése.

## Linux / VPS, csak szükség esetén

Meglévő grafikus asztalon a Windows parancsok megfelelői:

```bash
python3 -m venv /tmp/adatdusito-menu-venv
/tmp/adatdusito-menu-venv/bin/python -m pip install -r scripts/browser-requirements.txt
/tmp/adatdusito-menu-venv/bin/python -m playwright install chromium
/tmp/adatdusito-menu-venv/bin/python scripts/export_emag_menu.py --output /tmp/emag-menu-exports
```

PuTTY-s, grafikus felület nélküli szerveren használható a `--headless`, de sütidialógus vagy védelmi oldal miatt sikertelen lehet; ezért a saját gépes látható böngésző az ajánlott. Nem telepítünk automatikusan rendszerkönyvtárakat, és nem módosítunk MySQL-, Docker-, Nginx-, UFW- vagy HTTPS-beállítást.

## Ellenőrzési korlát

Az élő emag.hu oldalhoz innen továbbra sincs engedélyezett hálózati hozzáférés. A gyűjtő Chromiumon, szintetikus DOM-on tesztelt: 13 főcsoport, különböző almenük, tényleges sorrend, hiányok, duplikációk, szanitizálás, kézi gyorsbillentyűs JSON-letöltés és ZIP. Ez nem sikeres élő eMAG-letöltés állítása. Az első valós exportot a fájlok alapján ellenőrizni kell, szükség esetén a konkrét DOM-hoz igazított szelektorral.
