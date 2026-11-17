# RELEASE-CANDIDATE-02 – integrációs jegyzőkönyv és runbook

## Verzió és bemenetek

- Ág: `codex/release-candidate-02`.
- Tesztelt integrációs kód HEAD SHA: `ecb12b4a42e82ebf30c383a411be3a9367c39c51`. A jegyzőkönyvet hozzáadó dokumentációs commit után a **végső kiadási headet** a PR/átadási üzenet és a hozzá tartozó hosted CI rögzíti; checkoutból: `git rev-parse HEAD`.
- Kiadási alap / Draft PR base: [#40](https://github.com/bizsis/adatdusito/pull/40), `codex/release-candidate-01`, `09dc09b374bf6a9d52a60c329e47dcd14b85e1aa`.
- Első szülő: teljes [#46 HELP-02](https://github.com/bizsis/adatdusito/pull/46), `759278c9c0fb0e1480ab5d3d6c2b2e00f426b84b` (tartalmazza [#44 HELP-01](https://github.com/bizsis/adatdusito/pull/44), `a8fdea527053b637bd56a56cb12d9f469b3506b6`).
- Normál `merge --no-ff`: [#43 importjavítás](https://github.com/bizsis/adatdusito/pull/43), `735a4086549ab4f8b5d2fdb2ce73619db3a3caca`; merge commit: `0bc3d75`.
- Nincs squash/rebase, eredeti ág átírása, main merge vagy VPS-művelet.

## Eredmény és kiadási határ

A kompakt importelőzmények, biztonságos törlés, sor-/üresszámlálás, megfeleltetés és pénzügyi/EAN/készlet-figyelmeztetések a HELP-02 felületével együtt működnek. A `main.tsx` és az importkomponens meglévő jogosultsági bekötése megmaradt. A backend a #43 állapotával byte-szinten azonos; integrációs backendjavítás nem történt. A három vitatott donor változatlanul `pending_review`.

A törlés `imports.manage`-hez, teljes ügyfélerőforrás-hozzáféréshez és a szerver aktuális ellenőrzéséhez kötött. Csak a nem jóváhagyott/nem feldolgozott, nem futó és nem hivatkozott import törölhető. Feldolgozott import: 409, archiválás nincs. A beszállító, profilok, termékek, más importok és audit megmaradnak. A törlés nem rollback és nem azonos a forrásfájl retenciójával.

A `LASTINITIALCOST` utolsó beszerzési ár, a `LISTPRICE` listaár: mindkettő nettó HUF. Nincs automatikus eladásiár-következtetés, és a pénzügyi jóváhagyás továbbra is kötelező. A negatív készlet megmarad figyelmeztetéssel. Tudományos/kerekített BARCODE nem válik érvényes GTIN-né; a nyers forrás megmarad. Az aktív GUI figyelmeztetését pontosítottuk: **új, teljes számjegyes forrásadat kell; az utólagos Excel-formázás nem állítja helyre a már elveszett számjegyeket**.

## Mintafájl és adatvédelem

A pontosan `besz_minta(1).csv` nevű eredeti fájl nem érhető el. Egy korábbi `besz_minta.csv` feltöltés szerkezetét ellenőriztük: UTF-8 BOM, 27 oszlop, 4948 adatot jelölő sor, 3 kitöltött és 4945 üres. Ez nem bizonyítja a két fájl azonosságát, és **nem állítjuk, hogy a tesztek az eredeti ügyfélfájllal futottak**.

Minden új API/E2E/MySQL teszt a `scripts/tests/rc02_sample.py` szintetikus generátorát használja: kitalált termékazonosítók/nevek, helyőrző ismeretlen fejlécek, a hibajegyben megadott kritikus minták. Nincs valódi ügyfél-/beszállítói CSV vagy adatbázis-export commitolva.

## Ellenőrzések

| Ellenőrzés | Helyi eredmény |
|---|---|
| Teljes backend + eszközcsomag | 450 sikeres a merge után |
| Új fixture- és MySQL-célvédelmi tesztek | 5 sikeres, külön futtatva; távoli/pinfo/ack nélküli cél kapcsolódás előtt elutasított |
| Frontend lint, TypeScript, Vite | sikeres |
| Frontend tartalom-/konfigurációteszt | 14 sikeres |
| Integrált import + meglévő import UX + HELP-01/02 böngészős regresszió | 19 sikeres, 390/1440 px, valódi FastAPI + SQLite + produkciós bundle |
| MySQL 8.0.46 import API | 6 ellenőrzés, 0 hiba; valódi FK/DELETE, monotón új importazonosító, pénzügyi és jogosultsági szabályok, eredeti fájlbájtok/provenance, 0011-es séma |
| MySQL 8.0.46 migrációs regresszió | 3 kör, 56 ellenőrzés, 0 hiba; 0008–0011 fel/le, adatok/séma és döntési védelmek |

A 19-es böngészős csomag konkrét útja: beszállító → BOM/pontosvesszős 27 oszlopos feltöltés → 4948/3/4945 számláló → mapping, előnézet és figyelmeztetések → hiányzó pénzügyi jóváhagyásra 422 → törlési megerősítés → tényleges törlés → oldalfrissítés → új feltöltés → a törölt rekord nem tér vissza. Egy másik import megőrzését is ellenőrzi. A második futást jóváhagyva 3 termék jön létre, és feldolgozott importja nem törölhető. A hosszú fájlnév nem okoz oldalszintű vízszintes túlcsordulást, a JSON külön lenyitható részlet marad.

A MySQL importpróba `scripts/mysql_rc02_import_check.py`: kizárólag explicit `RC02_FIXTURE_ACK=isolated-release-candidate-02`, üres, loopback MySQL 8 `adatdusito_dev` fixture. Nem dob adatbázist; a séma elkészítése előtt ellenőrzi az ürességet. A referencia-URL-t zárt loopback portra cseréli, így nem örökölhet külső referencia-hozzáférést. **VPS-en/meglévő adatbázison soha nem futtatható.**

CI: hét kötelező job (backend, browser, menu-export, frontend, Docker, MySQL-migráció, ci-ok). Az új MySQL importpróba a backend job saját, eldobható MySQL service-ében is fut. A Claude-féle MySQL-migrációs job, függőségtelepítési lépések és `ci-ok` teljes `needs` listája változatlanok. A RC-02 push-trigger és saját elavult futásainak megszakítása beállítva. A korábbi külön #43/#46 eredmény **nem** a közös verzió bizonyítéka.

**Végső hosted bizonyíték:** a [RC-02 ág CI-futásai](https://github.com/bizsis/adatdusito/actions?query=branch%3Acodex%2Frelease-candidate-02) között az átadásban megadott végső SHA-ra 7/7 sikeres job kell. A teljes böngészős csomag 170 gyűjtött eset. A hosted eredményt az átadásban a konkrét run linkje azonosítja.

Helyi ismétlés (csak eldobható felhőteszt):

```bash
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
PYTHONPATH=backend .venv/bin/pytest -q backend/tests/test_import_ux_browser.py scripts/tests/test_release_candidate02_browser.py scripts/tests/test_help_browser.py scripts/tests/test_help_manual_browser.py
```

## Dokumentációs eltérések és nyitott pontok

- A korábbi HELP-02 még nem tartalmazta #43-at. Az aktuális feltöltés-, mapping-, jóváhagyás-, pénzügy-, történet/törlés- és hibakezelési cikkeket frissítettük; a gépi leltárban #41/#42 már elérhető.
- A `HELP-02-COVERAGE.md` történeti átadási jegyzőkönyv; fejlécében jelezzük ezt a verzióhatárt. A normál felhasználói útmutató az integrált viselkedést írja le.
- Új képek: `rc02-oszlopok.png`, `rc02-elozet.png`, `rc02-jovahagyas.png`, `rc02-importtortenet.png`, `rc02-importtorles.png`. Az aktuális importcikkek ezekre hivatkoznak; a régi képek a történeti leltárhoz megmaradnak. Újragyűjtés: `RC02_SCREENSHOTS=1` a RC-02 böngészőteszthez, kizárólag szintetikus fixture-ön.
- **A teljes HELP-02 emberi tartalmi jóváhagyása nincs kész.** Külső Google OIDC, valódi SMTP-kézbesítés és eszközfüggő passkey-folyamat külön környezeti próba. A későbbi UI-változáskor a vezérlőneveket, leírást és képeket ismét ellenőrizni kell.
- UNAS-termékfájl-generálás, AI-kutatás, kredit/fizetés, feldolgozott import archiválása nincs ebben a kiadásban.

## Migráció és későbbi, kézi telepítés

**Új migráció nincs; az adatbázis elvárt revíziója 0011.** A jelenlegi telepített a8fdea5 frontend/#40 backend/0011 állapotot ezen a feladaton nem módosítottuk. A Compose external hálózata `adatdusito-dev-net`, a `.env`, portok, Nginx, UFW, HTTPS és `pinfo_db` érintetlen.

Csak új tulajdonosi jóváhagyás után:

1. Rögzítsd az aktuális kód SHA-ját és képfájl-/containerverziókat; készüljön friss, ellenőrzött alkalmazás-DB-mentés. Új importot a váltás alatt ne indíts.
2. Ellenőrizd `/opt/adatdusito` munkakönyvtárának állapotát. Helyi változást (különösen Compose) ne írj felül; eltérésnél meg kell állni és felülvizsgálni.
3. A jóváhagyott, **7/7 CI-vel azonos immutable SHA-t** checkou­told. A `.env` és external hálózat változatlan maradjon.
4. Ellenőrizd a futó adatbázis 0011-es állapotát. Eltérésnél állj meg; ehhez a kiadáshoz nincs új `alembic upgrade` vagy adatmigrációs feladat.
5. Backend/frontend image build, majd a meglévő Redis/migráció megőrzésével célzott backend/frontend/worker újraindítás. Nincs teljes Compose down, MySQL-újratelepítés vagy automatikus tesztfixture-futtatás a VPS-en.
6. Liveness/readiness, bejelentkezés, megfelelő munkaterület, importelőzmények, segédlet és három `pending_review` donor ellenőrzése; új üzleti adat/import nélkül. A bevezetés utáni üzleti teszt külön jóváhagyás szerint.

## Rollback

Tulajdonosi döntés szerint a rögzített korábbi kód-/image-verzióra lehet visszaállni; séma-downgrade nem szükséges, mert marad 0011. Előtte állítsátok le/egyeztessétek az új importindításokat. **A kód rollback nem állítja vissza a már törölt importot vagy a már feldolgozott üzleti döntéseket.** Adat-visszaállítás külön jóváhagyott, mentésalapú művelet; automatikus DB-visszatöltés vagy referenciaadat-írás nincs. Az éles pinfo.hu környezet továbbra sem érintett.
