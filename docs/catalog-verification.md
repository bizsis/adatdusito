# Folytatható katalógusellenőrzés – CODEX 04B

## Hatókör

Ez a javítás a **már betöltött** katalógusverziót ellenőrzi. Nem hoz létre új
katalógusverziót, nem importál újra, nem töröl adatot és nem aktivál. A VPS-en nem
futtattunk műveletet. A meglévő `building / verify` 1-es verzió megtartható.
Nincs új migráció, index vagy tábla; az ellenőrzőpont a meglévő
`catalog_versions.counters.verification_progress` JSON-mezőben tárolódik.

## Lekérdezések és memória

Az értékek korábbi, több ezres `source_id IN (...)` ORM-lekérdezése és a külön
értéklekérdezés helyett kötegenként **egy tartományos Core-lekérdezés** fut:

```sql
SELECT m.source_id, m.target_id, m.context_id, m.ordinal,
       m.payload_sha256, m.data,
       v.id, v.parameter_id, v.`key`, v.value_text
FROM catalog_source_mappings m FORCE INDEX (PRIMARY)
LEFT JOIN catalog_parameter_values v ON v.id = m.target_id
WHERE m.version_id = :data_version
  AND m.kind = 'value'
  AND m.source_key = 'emag_marketplace'
  AND m.source_id > :after AND m.source_id <= :through
ORDER BY m.source_id
LIMIT :batch_size_plus_one;
```

Az elsődleges index teljes egyenlőségi prefixe `(version_id, kind, source_key)`,
azt követi a `source_id` tartománya. A célérték elsődleges kulcs szerinti JOIN-nal
érkezik. Nincs érték-ORM-példányosítás vagy felesleges `source_json` betöltés.
Legfeljebb 5000 forrásrekord és egy kötegnyi céladat van egyszerre memóriában.
A kategória-/paraméter-metaadatok és a kötegenkénti rövid lenyomatnapló külön,
korlátozott méretű munkakészletet alkotnak; nincs több milliós értéklista.

A kategóriák és paraméterek SHA-256 metaadatlenyomata az érdemi összehasonlítás
közben készül, ezért az ellenőrzés elején nem kell ugyanazokat a forrás-JSON-okat
még egyszer beolvasni. A saját kategóriaidentitások egyszeri tömeges lekérdezése
megszünteti a kategóriánkénti külön SQL-t. A metaadat-megfeleltetések lekérdezése
MySQL alatt szintén kifejezetten az elsődleges indexet használja.

Az értékrekordok teljes céloldali `COUNT(*)` vizsgálatát a tartományokban ténylegesen
beolvasott rekordok ellenőrzése helyettesíti: minden forrásazonosító megvan-e,
nincs-e extra célrekord a tartományban, nem pozitív azonosító vagy a végső kurzoron
túli rekord. A végső darabszámnak egyeznie kell a rögzített forrásdarabszámmal.
A külön egyediérték-számlálás megtartja a `25e086d` fedőindexét és 60 másodperces,
kizárólag erre az összesítésre érvényes olvasási időkeretét.

## Tényleges egyezés és folytatás

Minden új értékrekordnál ellenőrizzük a forrássor lenyomatát, a célérték meglétét,
a kategóriaparaméter-kapcsolatot, a közös paraméterazonosítót, a pontos szöveget,
a sorrendet, az eredeti forrásparaméter-kapcsolatot és a közös értékkulcsot.
A kategóriák/paraméterek nyers metaadatai, típusai és jelzői is ellenőrzöttek.

Csak teljesen sikeres köteg után történik ellenőrzőpont-mentés. Ez tartalmazza a
kurzort, a feldolgozott darabszámot, a futásidőt, a ellenőrző-/adatverzió kötését és
kötegenként a tényleges forrás- és céladatok lenyomatát. Ctrl+C vagy SQL-hiba nem
veszíti el a már mentett kötegeket. A hibás vagy félbemaradt köteg újraellenőrződik.

**A folytatás nem bízik vakon a régi kurzorban.** A korábban ellenőrzött értéktartományok
mindkét oldalát újraolvassa, és összeveti a mentett lenyomatokkal. Ez továbbra is
I/O-munka, de nincs ismételt mezőnkénti validálás a változatlan kötegeken. Így az
azonos darabszámot/maximális azonosítót megtartó, megszakítás közbeni módosítás sem
marad észrevétlen. Eltéréskor részletes rekordellenőrzés ad pontos hibajelzést;
a kétoldali, következetes átírás is lenyomateltérésként megállítja a folytatást.
A kategória-/paraméter-metaadatokat minden folytatás újraellenőrzi.

Egy korábban sikeresen ellenőrzött, kész verzió ismételt ellenőrzése friss teljes
vizsgálat. A korábbi sikerjelentés nem íródik felül félkész riporttal; a folyamat
állapota külön tárolódik. Függőben lévő vagy hibával megszakadt ellenőrzéssel a
verzió **nem aktiválható**, még korábbi sikerjelentés birtokában sem. Ugyanez
vonatkozik a faverzió által hivatkozott közös paraméter-/érték-adatverzióra.
Siker esetén a meglévő verzió `ready / complete` lesz. Az aktiválás továbbra is
külön, explicit művelet; az ellenőrzés nem módosítja az aktív verzió mutatóját.
Az import/ellenőrzés/aktiválás közös zárolása megakadályozza az ütköző CLI-műveleteket.

## Napló és hiba

A JSON-napló jelzi a verziót, fázist, feldolgozott/összes rekordot, százalékot,
rekord/másodperc sebességet, aktuális és összesített futásidőt. A korábbi kötegek
újraolvasása `values_checkpoint_replay`, az új ellenőrzés `values` fázisban látszik.
Az összesítések kezdetét és a sikeres befejezést is külön esemény jelzi.

Eltéréskor naplózódik a forrássor és a célrekord azonosítója, az eltérő mező,
valamint az elvárt/tényleges érték rövidített változata. SQL-hibánál a valódi
DBAPI/MySQL-hibakód és üzenet jelenik meg és kerül a verzió `error` mezőjébe;
a több ezres SQL-paraméterlista nem. Ha a hibaállapot mentése is elromlik, az
másodlagos naplóbejegyzés; az eredeti hiba nem vész el.

## Későbbi üzemeltetői használat

Az alábbi parancsok a javított backend-image elérhetővé tétele **után** használhatók.
Ezeket a fejlesztés során nem futtattuk a VPS-en. A backend új image-ből futó,
egyszeri konténere nem igényli a webes szolgáltatás leállítását.

```bash
cd /opt/adatdusito
# A meglévő 1-es verzió ellenőrzése / automatikus folytatása, import nélkül:
docker compose run --rm --no-deps backend python -m app.catalog_import verify \
  --version 1 --batch-size 5000 \
  --expected-categories 2669 --expected-parameters 29398 \
  --expected-values 2847054 --expected-television-parameters 46

# Állapot és az utolsó mentett ellenőrzőpont összefoglalója:
docker compose run --rm --no-deps backend python -m app.catalog_import status
```

A futás Ctrl+C-vel megszakítható; a terminálparancs újbóli kiadása folytatja.
Ha tudatosan nulláról kell újraellenőrizni, ugyanahhoz a `verify` parancshoz adható
`--restart-verification`. Ez csak az ellenőrzőpontot kezdi újra, nem importál adatot,
és nem cseréli le az 1-es verziót. A sikeres ellenőrzés után sem történik aktiválás.

## Tesztelés

Az automatizált tesztek eldobható SQLite adatbázisokban vizsgálják a megszakítást,
folytatást eltérő kötegmérettel, a korábbi tartomány forrás-/céloldali változását,
a pontos paraméterjelző-hibát, extra rekordokat, valódi SQL-hiba megőrzését,
a sikertelen újraellenőrzés utáni aktiválási tiltást és a friss újrakezdést.
A MySQL SQL-fordítás tesztje ellenőrzi az indexhintet és a teljes prefixet.
A 25 001 soros szintetikus mérés kötegenként egy tartományos céllekérdezést,
korlátos kötegméretet és 101 egyedi érték helyes megtartását ellenőrzi.

A teljes 2 847 054 soron elérhető valós VPS-futásidőt nem állítjuk: élő VPS-mérés
nem történt. Az indexhasználatot, az SQL-alakot és a lekérdezésszámot teszteltük;
a konkrét MySQL végrehajtási tervet a későbbi üzemeltetői futás igazolhatja.

2026-11-13: a végső teljes futás (`PYTHONPATH=backend .venv/bin/pytest -q
backend/tests scripts/tests`) **135 sikeres teszttel**, 108,51 másodperc alatt
zárult. Az egyetlen figyelmeztetés a meglévő Starlette/AnyIO elavulási jelzése.
A módosított Python-fájlok Ruff-ellenőrzése és a `git diff --check` is sikeres.
