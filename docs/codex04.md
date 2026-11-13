# CODEX 04 – Saját, egységes referenciakatalógus

## Működés és adatmodell

Az alkalmazás egy közös kategóriafát használ. A 13 magyar főcsoport és sorrendjük megmarad. A kategóriák összevezetése a CODEX 03B név-/környezet-/kategóriakör-szabályait használja, az egyértelmű egyezések automatikusak. A nem elhelyezett, inaktív vagy bizonytalan kategóriák ugyanazon böngésző külön nézetében, saját paramétereikkel elérhetők. A forrásazonosítók számegyezése nem összerendelési feltétel.

Az első sikeres aktiválásig a meglévő olvasó működik tovább. Az aktivált katalógus kategória-, paraméter- és értéklekérdezései, keresése és readiness-ellenőrzése **kizárólag az alkalmazás-adatbázist használják**. Nem elérhető aktív katalógus esetén 503 érkezik; nincs észrevétlen visszaváltás a pinfo_db-re. A source URL ezután csak az operátori import/forrásellenőrzés számára szükséges. Nincs második kategóriaböngésző és nincs webes adatgyűjtés.

Új, kizárólag alkalmazás-adatbázisbeli migráció: **0005**, előzménye **0004**. Az 0001–0004 migráció változatlan.

| Logikai elem | Új táblák |
| --- | --- |
| Közös kategóriaazonosság | `catalog_categories` |
| Verziózott fa, megjelenítési helyek és aliasok | `catalog_category_nodes` |
| Közös paraméterdefiníció és adattípus | `catalog_parameters` |
| Stabil kategóriaparaméter-azonosító | `catalog_category_parameters` |
| Verziózott kategória–paraméter kapcsolat, kötelezőség, sorrend, szűrő- és újérték-jelző | `catalog_category_parameter_entries` |
| Közös megengedett értékszöveg | `catalog_parameter_values` |
| Eredeti kategória-/paraméter-/értékrekord és engedélyezettérték-tagság | `catalog_source_mappings` |
| Import, ellenőrzés, hiba és checkpoint | `catalog_versions` |

A közös azonosítók saját egész számok, 1 000 000 000-tól, a JavaScript pontos egészszám-tartományában. Az egyetlen, adatbáziszárral sorosított importer osztja ki őket. Újrafuttatáskor a meglévő kulcsok azonos azonosítókat kapnak. A kategóriaoldali `unified_category_id`, a paraméteroldali `parameter_id` és az értékoldali `id` a közös rendszer azonosítója. A `category_parameter_id` / paraméterlista `id` a kategóriában használt paraméterkapcsolat azonosítója; az értékvégpont ezt fogadja, mert a megengedett értékek kategóriánként eltérhetnek.

Az eredeti eMAG belső és külső azonosítók a névterezett forrásmegfeleltetésben maradnak. A korábbi numerikus kategória- és kategóriaparaméter-URL-ek forrásmegfeleltetésen keresztül olvashatók. A meglévő API-útvonalak és jogosultságok megmaradnak. A későbbi termékimportnak a **közös kategória-, paraméter- és értékazonosítókat**, valamint az adatverziót kell mentenie, nem eMAG-forrásazonosítót.

A paraméterdefiníciók azonos eMAG-paraméterazonosító, normalizált név és azonos típus esetén közösek. A kötelezőség, sorrend és a többi kategóriafüggő jelző külön kapcsolatrekordban marad. Az értékszövegeket azonos közös paraméter és **pontosan azonos szöveg** esetén egyszer tároljuk. Nem vonunk össze pusztán hasonló nevű, eltérő jelentésű/típusú definíciókat, illetve eltérő írású értékeket. A forrásmegfeleltetés több eredeti rekordot is ugyanazon közös definícióhoz/értékhez kapcsolhat; az összes eredeti sorazonosító, paraméter-FK és értéksorrend megmarad. A kategória-/paraméterrekordok eredeti `raw_json` tartalma külön, késleltetetten betöltött mezőben is megőrzött; a normál böngésző nem tölti be.

A bizonytalan kategóriákat az adminisztrátor meglévő, egyszerű választóval rendezheti, közös kategóriaazonosítóval. Nincs SHA-bekérés. Az aktív verzióban a módosítás auditált; a korábbi kategória sem válhat elérhetetlenné egy másik összekapcsolás miatt. Az „Importált besorolás visszaállítása” az adott verzió importált elhelyezését állítja vissza. Az ilyen választásokat az importer a következő új adatverzióban is figyelembe veszi. A következő adatverzió a kategóriadöntéseket az import kategóriafázisában pillanatképezi; az aktiválás előtti időközi kategóriaszerkesztéseket külön ellenőrizni kell.

A forrásnévtér és szöveges külső azonosító nem korlátozódik az eMAG-ra: későbbi adapter meglévő közös azonosítót használhat és új forrásmegfeleltetést adhat hozzá. Ebben a kiadásban kizárólag eMAG-import van; nincs Alza-adatgyűjtés, termékimport, AI-kutatómotor vagy UNAS-export.

## Import és ellenőrzés

Parancsmodul: `python -m app.catalog_import`.

1. Az importer forrásprofilból (darabszámok, legnagyobb sorazonosítók, kategória-/paramétermetaadatok ellenőrzőösszege) indul. A forráskapcsolat csak olvasható.
2. Külön, még nem aktív verzióba készíti a kategóriafát és forrásmegfeleltetéseit. A közös entitásokat újrahasználja; az aktív verzió tagsági rekordjait nem írja át.
3. A kategóriaparamétereket és az értékeket elsődleges kulcs szerinti kurzorral dolgozza fel (`id > checkpoint`, `ORDER BY id`, `LIMIT`), nem nagy OFFSET-ekkel.
4. Egy kötegben a közös entitás, a forrásmegfeleltetés, a tagság és a checkpoint **azonos céladatbázis-tranzakcióban** készül. Megszakításkor az utolsó befejezett kötegtől folytatódik. A kategóriafázis egy kisméretű, atomi tranzakció; megszakításkor ez a fázis kezdődik újra.
5. A végén a forráson végigmenő, konzisztens, csak olvasási ellenőrzés minden rekordot összevet az eltárolt adatokkal. Ellenőrzi az eredeti mezőket, JSON-t, FK-kat, típusokat, jelzőket, sorrendeket és a ténylegesen tárolt értékszöveget is. Teljes egyezés után lesz a verzió `ready`.
6. Az alkalmazás csak külön **activate** parancsra vált át. Ez egyetlen, auditált verziómutató módosítása; nincs élő táblacsere vagy teljes adattörlés.

Az első futás és az azonos verzió folytatása ugyanaz az `import` parancs. Megadható `--version N`. Egy már kész verzió újrafuttatása ellenőriz, nem duplikál. Frissített forráshoz vagy új importált pillanatképhez `--new-version` készít új verziót, a közös kategória-/paraméter-/értékentitások újrafelhasználásával. A verziónkénti tagság és forrásrekord-térkép tudatosan külön marad a biztonságos visszaváltáshoz. Régi verziókat nem törlünk automatikusan.

Forrásváltozás vagy ellenőrzési eltérés esetén nincs aktiválás. A korábban rögzített sorok csendes átírása helyett új verziót kell készíteni. A futási állapot és hibafázis az alkalmazás-adatbázisban megmarad. A napló verziót, fázist, kurzort és darabszámokat tartalmaz, jelszót vagy teljes adatrekordot nem.

### Teljesítmény és indexek

- Alapértelmezett értékköteg: 2000 sor, engedélyezett tartomány 1–5000; kötegenkénti szünet állítható. A teljes értékkészlet nem kerül Python-memóriába.
- Kategória-/paraméter-JSON-ból legfeljebb 100 rekord kerül egy lekérésbe, előzetes SQL-méretellenőrzéssel, kb. 16 MiB kötegcéllal. Egyetlen 64 MiB-nál nagyobb forrás-JSON esetén az import leáll, nem hagyja el a rekordot. Az ilyen rendhagyó rekord külön kezelését a tényleges forrásadat alapján kell megtervezni.
- A kis kategóriaindex és kategóriaparaméter-azonosítótérkép memóriában van; a több millió érték nincs. A nyers JSON a normál API-kban késleltetetten betöltött, nem része a fa listázásának.
- Egyedi indexek védenek az ismételt entitás- és forrásrekord-felvételtől. A forrásmegfeleltetés kulcsa verzió + típus + forrásnévtér + eredeti sor-ID.
- A `(version_id, kind, context_id, target_id)` index támogatja a kategóriaparaméterhez tartozó értékek kurzoros lekérését. A célazonosító és a forrás külső azonosítója külön indexet kapott. A kategóriaparaméter-lista verzió/kategória/sorrend szerint indexelt.
- Az API az értékeket az indexelt tagságból, legfeljebb `limit + 1` egyedi célazonosítóra szűkítve olvassa; nem a teljes értékszöveg-állományt csoportosítja memóriában. Kategóriakörnyezetenként külön megmarad a megengedett értékkészlet.
- MySQL név szerinti alkalmazászár akadályozza a párhuzamos importot/aktiválást. Normál olvasás és az ügyféladatok kezelése tovább működik; a kötegszünet mérsékli a közös VPS I/O-terhelését. A teljes forrás tényleges futásidejét és tárhelyét itt nem mértük.

## Pontos VPS-lépések – kizárólag kézi végrehajtás

Az alábbi lépéseket ebben a fejlesztésben **nem futtattuk a VPS-en**. Csak az `adatdusito_dev` módosul; a `pinfo_db` kizárólag olvasható, a `pinfo.hu` érintetlen. A `.env`, Compose external hálózat, MySQL-, Nginx-, UFW- és HTTPS-beállítások nem változnak.

### 1. Ellenőrzés és alkalmazásmentés

```bash
cd /opt/adatdusito
git status -sb
df -h /opt/adatdusito
docker compose ps
```

Tiszta Git-állapot és elegendő szabad tárhely szükséges az új katalógushoz és a megtartott verziókhoz. Készíts ellenőrzött alkalmazás-adatbázis-mentést a meglévő biztonságos MySQL-hozzáféréssel. Példa interaktív helyi root-hitelesítéssel (a jelszó nem kerül a parancsba):

```bash
umask 077
mkdir -p /root/adatdusito-backups
catalog_backup="/root/adatdusito-backups/adatdusito_dev-before-codex04-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
set -o pipefail
mysqldump -u root -p --single-transaction --no-tablespaces --routines --triggers adatdusito_dev | gzip > "$catalog_backup"
gzip -t "$catalog_backup"
```

Ha a VPS más meglévő hitelesítési módot használ (például Unix socket vagy login-path), azt használd; hitelesítési adatot ne másolj a repositoryba.

### 2. Kód, új séma és tovább működő alkalmazás

```bash
cd /opt/adatdusito
git pull --ff-only origin main
docker compose build backend frontend
docker compose run --rm --no-deps migrate alembic upgrade head
docker compose run --rm --no-deps migrate alembic check
docker compose up -d --no-build
bash scripts/smoke.sh https://dev.pinfo.hu
docker compose run --rm --no-deps migrate python -m app.catalog_import status
```

Ekkor a meglévő olvasó tovább működik, amíg nincs aktív saját katalógus. A 0005 csak új `catalog_*` táblákat/indexeket hoz létre; nincs működő tábla törlése vagy forrásmigráció.

### 3. Előkészített import

Hosszabb SSH-munkánál tartós terminálban célszerű futtatni. A forrásszinkron ne módosítsa közben az adatokat; a végső ellenőrzés eltérés esetén leáll.

```bash
set -o pipefail
docker compose run --rm --no-deps migrate python -m app.catalog_import import --batch-size 2000 --pause-ms 25 2>&1 | tee -a /root/adatdusito-backups/catalog-import.log
docker compose run --rm --no-deps migrate python -m app.catalog_import status
```

A kimenetből jegyezd fel a `version` számát. Megszakítás után ugyanez a parancs folytatja az aktuális verziót. Kifejezett folytatás: `import --version N`. `--max-batches N` használható szándékos, ellenőrzött részfutáshoz; az ilyen verzió nem aktiválható. Ha a forrás közben megváltozott, új verzióhoz `import --new-version` szükséges.

### 4. Teljes ellenőrzés és külön aktiválás

Az alábbi `1` helyére az import által kiírt tényleges verziószám kerüljön:

```bash
catalog_version=1
docker compose run --rm --no-deps migrate python -m app.catalog_import verify --version "$catalog_version" --batch-size 2000 --expected-categories 2669 --expected-parameters 29398 --expected-values 2847054 --expected-television-parameters 46
```

Csak sikeres, `complete: true` ellenőrzés és a `ready` állapot után:

```bash
docker compose run --rm --no-deps migrate python -m app.catalog_import activate --version "$catalog_version"
docker compose run --rm --no-deps migrate python -m app.catalog_import status
bash scripts/smoke.sh https://dev.pinfo.hu
```

Az aktiválás kimenete megadja az előző és az új mutatót; ezt őrizd meg a naplóval. A böngészőben Ctrl+F5, majd ellenőrizd a 13 főcsoportot és a **TV és szórakozás → Televíziók → 46 paraméter** útvonalat, az értékkeresést és az elkülönített kategóriákat.

A `processed.values` a megőrzött **eredeti értékrekordok** száma: 2 847 054. A `unified_value_count` az ismétlődő értékszövegek közösítése miatt kisebb lehet; ez önmagában nem adatvesztés. A teljes rekordellenőrzés és a forrásmegfeleltetések őrzik minden eredeti sorazonosító, szöveg, paraméterkapcsolat és sorrend egyezését. A `televisions` ellenőrzési rész a közös kategóriaazonosítót és a 46-os paraméterszámot is visszaadja.

## Visszaállítási terv

Az elsődleges visszaállítás **adatverzió-váltás**, nem adatbázis-visszatöltés. Így a közben létrejött felhasználói és ügyféladatok megmaradnak.

Korábbi saját adatverzió esetén (példa: az előző mutató 2 volt):

```bash
docker compose run --rm --no-deps migrate python -m app.catalog_import activate --version 2
docker compose run --rm --no-deps migrate python -m app.catalog_import status
bash scripts/smoke.sh https://dev.pinfo.hu
```

Az első saját import előtti működéshez ebben a fázisban:

```bash
docker compose run --rm --no-deps migrate python -m app.catalog_import activate --legacy
bash scripts/smoke.sh https://dev.pinfo.hu
```

Mindkettő auditált, atomi mutatóváltás. Böngészőfrissítés szükséges. A saját katalógus megmarad, később visszaaktiválható. Nem törlünk kategóriát, paramétert, értéket vagy ügyféladatot.

Ha kódvisszaállítás is szükséges, az utolsó CODEX 03B commit `917f5527894d553b57515a168c0f4847ee632ba1`. Tiszta munkakönyvtárban erre a commitra visszaállított checkoutból a backend/frontend újraépíthető; a bővített séma visszabontása nem szükséges. Az aktív saját verziót előbb a fenti operátori paranccsal állítsd `legacy` módra. A régi `.env` és Compose-beállítások maradnak.

A migráció `downgrade` ága csak az új katalógustáblákat törölné, ezért ez **nem a normál rollback**. Aktív saját katalógus mellett a downgrade le van tiltva. Éles környezeten nem futtatjuk automatikusan; teljes alkalmazásmentés visszatöltése külön adatvesztési/karbantartási döntés lenne. A MySQL DDL implicit commitja miatt félbeszakadt sémamigráció esetén előbb a tényleges `catalog_*` sémát kell megvizsgálni, nem vakon újrafuttatni törlő parancsokat.

## Tesztelés és korlátok

A teljes éles referenciaadatbázis ebben a környezetben nem volt elérhető. **Nem állítunk teljes 29 398 kapcsolatos / 2 847 054 értékes importtesztet vagy éles teljesítménymérést.** Ezt a fenti `verify` parancs ellenőrzi majd a VPS-en.

A valódi, feltöltött 2669 kategóriás TSV minden kategóriájának feldolgozása tesztelt, a hiányzó paraméter-/értékállomány nélkül. Külön 46 TV-paraméteres, kötelező/opcionális és értékes szintetikus adatkészleten ellenőrzött az import és a felület. Egy 25 001 forrásértékes ismétlődő mintán 101 közös értékszöveg és az összes eredeti tagsági rekord megmarad; a két kategória eltérő értékkészlete külön teszttel védett. Megszakítás, újrafuttatás, új verzió, közös ID-k megtartása, forrásváltozás, sérült adatok elutasítása, JSON-megőrzés/méretkorlát, és mutató-visszaállítás is tesztelt.

Az asztali/mobil UI-t a tényleges FastAPI tesztalkalmazással saját katalógusra aktiválva is teszteljük, letiltott forráseléréssel. Az API és readiness saját katalógus mellett a pinfo_db nélkül működik. MySQL 8-on külön, szintetikus felhőadatbázissal ellenőrizzük a migrációt, az importparancsokat és az aktiválást. A tesztek és ezek a felhőbeli műveletek nem érintik a VPS-t.
