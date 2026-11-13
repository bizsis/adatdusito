# CODEX 03A – egyetlen közös eMAG-referencia

## Mi a kanonikus rendszer?

A kategória identitása `emag_marketplace:<emag_category_id>`. A meglévő `pinfo_db.emag_categories` az egyetlen kanonikus kategóriatár ebben a kiadásban. A belső `id` változatlanul a paraméterkapcsolatok kulcsa; nem cseréljük le külső azonosítóra. Az alkalmazásadatbázisban **nincs kategóriamásolat és nincs második böngészhető fa**.

- Szülő: `parent.emag_category_id = child.parent_id`.
- Kategóriaparaméter: `emag_category_parameters.category_id = emag_categories.id`.
- Megengedett érték: `emag_parameter_values.parameter_id = emag_category_parameters.id`.
- A `0001` és `0002` migráció változatlan. A `0003` csak globális forrásregisztert és forrásmegfigyeléseket ad az `adatdusito_dev` adatbázishoz.

A `reference_sources` a források definícióját tartalmazza. A `reference_observations` ellenőrzési eseményeket tárol: forráshivatkozás, megfigyelés időpontja, tartalomhash, hozzáférési eredmény, eredeti forrásazonosító, megfeleltetési állapot és indoklás. Ezek nem kategóriák, nincs külön szülőfájuk, nem hoznak létre új választható kategóriákat.

Forrásazonosságot névegyezésből nem állapítunk meg. A strukturált breadcrumb-feldolgozó még numerikus URL-azonosító esetén is `pending` megfigyelést ad, nem Marketplace-megfeleltetést. Igazolt kapcsolatot csak Superadmin rögzíthet meglévő kanonikus eMAG-ID-ra, forrásazonosítóval, nyilvános bizonyítékkal, tartalomhash-sel és explicit ID-/dokumentált crosswalk-bizonyítéktípussal. A szerver ezt operátori bizonyítékrögzítésként kezeli, nem állítja, hogy a hash hitelességét távolról maga ellenőrizte. Az esemény auditált.

Ha később új, bizonyított kategória kerül elő, annak kontrollált, verziózott központi bővítésére lesz szükség. A terv: az eredeti eMAG-ID maradjon a közös azonosító; az eredeti belső ID-k és paraméter-FK-k maradjanak meg; a csak új rekordokat tartalmazó globális bővítőréteg ugyanabba a logikai gráfba olvadjon, bizonyított szülőkapcsolattal. Bizonyítatlan webshop-ID továbbra is megfigyelés, nem új fa. E kiadás nem talál ki ilyen rekordot, és nem tartalmaz rendszeres szinkronizálót.

## Navigálható és besorolható

A kategória megnyitása adatmegtekintés, nem termékbesorolás.

- **Besorolható:** `is_allowed = 1`, és nincs a névben `Deleted` jelölés.
- **Strukturális:** nem besorolható, de szükséges valamely besorolható kategória teljes ismert szülőláncához.
- **További ág:** nem törölt, nem besorolható és nem szükséges a fenti szülőláncokhoz. Ugyanennek a fának a „Minden nem törölt referenciaág” szűrésével megtekinthető.
- **Töröltnek jelölt:** a név kis-/nagybetűtől függetlenül `Deleted` jelölést tartalmaz. A séma nem ad külön törlési flag-et, ezért ez jelölésalapú, konzervatív kizárás, nem új távoli státuszellenőrzés. Ilyen rekord nem jelenik meg és nem besorolható, akkor sem, ha az engedélyezési flag ellentmondásos.
- **Hiányzó szülő:** a külső szülőazonosító nem oldható fel. Az ismert ág önálló megjelenítési gyökérként elérhető; az eredeti parent-ID látható marad. Nem használunk azonos számú belső ID-t pótlásként.
- **Ciklus:** felismerjük az összes ciklikus komponenst. Megjelenítési célból egy determinisztikus csomóponton megszakítjuk a bejárást; `cycle_break` és `hierarchy_error=cycle` jelzi ezt. Ez nem átírt forráskapcsolat, az eredeti ID megmarad.

A `1496 → 79` televízió-példában a 1496 strukturális szülőként navigálható, a 79 besorolható. A termékbesorolás előkészítéséhez külön `GET /api/v1/reference/categories/{belső_id}/selection` szerződés tartozik: strukturális kategóriára 409, törölt/ismeretlen kategóriára 404. Siker esetén megadja a kanonikus kategóriát és a közvetlen paraméterforrást; terméket nem hoz létre.

## Paraméterek és következő fázis

A saját kategóriához rendelt paraméterek az elsődlegesek. A szülők paramétereit **nem örökítjük automatikusan**. Ezt nem úgy állítjuk, hogy az eMAG biztosan tilt minden öröklést: a szolgáltatói szabályt a mostani hálózati hozzáféréssel nem lehetett hiteles dokumentációból megerősíteni. Az adatbázis explicit kategória–paraméter kapcsolatai bizonyítottak, ezért ezeket használjuk.

A közvetlen paraméterek száma, kötelező/opcionális/ismeretlen kötelezőségű darabszáma és a gyermekek száma minden kategória DTO-jában szerepel. A típus numerikus `type_id`, nem kitalált típusszótár. Az értéklisták továbbra is kurzorral lapozottak, legfeljebb 100 sorral; nincs többmilliós lista letöltése.

A következő importfázisnak a kanonikus kategóriaazonosítót, a közvetlen paraméterazonosítót, a megengedett érték ID-ját és a paraméterforrás verzióját kell megőriznie. Új paraméterérték később ügyfelenkénti munkafolyamatban `pending_approval` javaslat lesz; a referenciaadatbázisba nem kerül automatikusan. E kiadás csak ezt a szabályt adja át (`new_value_policy=proposal_requires_approval`), importot, AI-t, terméktáblát és javaslatbeküldést nem épít.

## Publikus forrásvizsgálat – tényleges eredmény

2026-11-13-án a felhőkörnyezetből végzett vizsgálat:

| Vizsgált forrás | Eredmény |
| --- | --- |
| `https://www.emag.hu/robots.txt` | A környezeti proxy CONNECT 403-mal tiltja; nem az eMAG tartalmi válasza |
| `https://www.emag.hu/sitemap.xml` | Az első közvetlen próba szintén proxytiltás; a megismételhető kutatóeszköz robots-ellenőrzés nélkül már nem tölti le |
| `https://www.emag.hu/` navigáció / breadcrumb | A kutatóeszköz ellenőrizetlen robots miatt nem tölti le |
| `https://marketplace.emag.hu/infocenter/emag-api/` dokumentációs belépési cím | Proxy CONNECT 403; a dokumentum tényleges elérhetősége/tartalma nem igazolt |
| Meglévő helyi Marketplace-adatbázis | A sémát és a valós statisztikákat az üzemeltető adta át; futás közben a rendszer ebből olvas |

**Új publikus webshop-kategóriát nem töltöttünk le és nem olvasztottunk be. A teljes magyar webshopfa lefedettségét nem állítjuk.** Az URL-ek kísérleti forrásbelépési címek, nem igazolt teljes exportforrások. A hálózati javaslat a környezeti piszkozatban a `www.emag.hu`, `emag.hu`, `marketplace.emag.hu`, `marketplace-api.emag.hu` hostokat tartalmazza; mentése nem jelent alkalmazott hozzáférést vagy közzétételt, és nem módosította a VPS-t.

A kézi vizsgálat megismételhető:

```bash
python scripts/research_reference_sources.py --output /tmp/emag-source-report.json
```

Ez korlátos robots-/manifest-/dokumentációs próba, nem termékkatalógus-letöltő vagy automatikus szinkronizáló. Hozzáférési tiltást nem kerül meg. A JSON-LD feldolgozás szintetikus, ellenőrzött breadcrumb-mintákon tesztelt; nem állítunk sikeres élő scrapinget.

## Valós és mért lefedettség

Az üzemeltető által átadott valós adatok: 2 669 kategória; 1 749 engedélyezett, 920 nem engedélyezett; 1 807 kategóriához tartozik paraméterkészlet, 862-höz nem; 29 398 paraméterdefiníció és 2 847 054 érték. A paraméterkészletek számát az üzemeltető a `COUNT(DISTINCT category_id)` lekérdezéssel külön ellenőrizte. Eredeti gyökerekből elérhető 2 565 rekord, mélységük 1–4, rétegenként 89 / 512 / 1 710 / 254. A 104 fennmaradó rekordot nem könyveljük automatikusan javítottnak. 94 közvetlen hiányzó szülőkapcsolat ismert: 2661 → 91, 619/727/781 → 1–1. A 3904, 3306 és 3810 aktív kategóriákat nem rendeljük kitalált pótszülőhöz.

Ezek átadott statisztikák, nem az itt rendelkezésre álló szintetikus adatbázis újramérései. A fenti valós paraméterkészlet-darabszámot az üzemeltető külön SQL-ellenőrzése igazolja. A tényleges aktuális számokat és a forrásellenőrzés időpontját telepítés után az alábbi, kizárólag olvasó jelentés adja meg:

```bash
cd /opt/adatdusito
docker compose exec -T backend python -m app.reference_report
```

A hitelesített `/api/v1/reference/coverage` ugyanilyen élő statisztikát ad: tárolt, besorolható, navigációs, strukturális, törlésjelölt darabszám; eredeti gyökerekből elérhető/elérhetetlen rekordok; eredeti igazolt maximális mélység és szinteloszlás; hiányzó szülő-ID-k; ciklusok; közvetlen paraméterkészlettel rendelkező kategóriák és definíciók száma. A megjelenítés ciklustöréseit és árvaágait nem számolja bizonyított eredeti gyökereknek.

## Teljesítmény és hozzáférés

A szerver egy kérésben a kategóriák kis metaadathalmazát és csoportosított paraméterszámokat olvassa. A gráf felépítése iteratív O(V+E), nincs 50 szintes levágás vagy szülőnként külön SQL. A 10 000 szintű mesterséges gráf és az 1 000 szintű API-szülőút tesztelt. A listák legfeljebb 100 kategóriát adnak vissza, a React-fa gyermekeket csak kibontáskor kér. A több millió paraméterérték nem kerül memóriába a fa építéséhez.

A forrásadatok közösek minden ügyfélnek, a meglévő `reference.read` jogosultság védi őket. A forrásmegfigyelés rögzítéséhez Superadmin szükséges, az esemény auditált. A referencia-engine továbbra is SELECT-only; az új app-táblákhoz nincs pinfo_db író jogosultság. Nincs .env-, Compose-, hálózati, MySQL-, Nginx-, UFW- vagy HTTPS-módosítás.
