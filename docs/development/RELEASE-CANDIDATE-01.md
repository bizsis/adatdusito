# RELEASE-CANDIDATE-01 – közös kiadási jelölt

Feladat: [#32, Vezér döntése](https://github.com/bizsis/adatdusito/issues/32#issuecomment-6927301428).
Ág: `codex/release-candidate-01`. Külön draft PR, main base kizárólag összehasonlításhoz.
A #37 eredeti ága és az összes forráság változatlan marad. **Nincs main-merge,
VPS-telepítés, pinfo_db-írás vagy új termékfunkció.**

## Bemenetek és reprodukció

| Input | Rögzített head | RC merge commit |
|---|---|---|
| #37 CATEGORY-03D | `ab7cf44100253f6d632c8aa686a5bf40c1cd060b` | Az új ág kiindulópontja |
| #34 RELEASE-01 | `329146ad68e05d6639fab9b04610f838ed0a1dbb` | `5b7b2c19923f27956fba314e9b8f0de518ea99b2` |
| #39 RELEASE-03 | `a8bac7eb3423beecda8001c454f8e826a1c8ef81` | `a1f97c7b32da784c6ce4fccb383c876cc96340fc` |

A #37 már tartalmazza a #18/#25/#26/#29/#22/#27/#31 inputokat és a #36
RELEASE-02-t (`3df4b20afbd8be6c4ab019ac245d3bf2e1071eed`). A részletes korábbi
SHA-k, integrációs eltérések és 03A/03C garanciák:
[CATEGORY-03D-INTEGRATION.md](CATEGORY-03D-INTEGRATION.md).

Mindkét lépés normál `git merge --no-ff`, közös ancestry-vel; nem squash,
rebase vagy fájlmásolás. **Nem volt merge-konfliktus.** A CI és az AGENTS
automatikus merge-eredményét külön ellenőriztük:

- Az AGENTS megtartja a #34 AUTH/SECURITY `test_auth09.py` fájlgazdáját és a
  #39 Claude-féle MySQL job/szkriptek tulajdonosi sorát is.
- A `mysql-migrations` teljes jobja és a `ci-ok` MySQL-függősége a #39-ből jön.
  Ezekben nincs Codex által szerkesztett változás.
- A #37 CI-trigger megmarad; az RC saját ágára is kerül push-trigger, hogy a
  hosted ellenőrzés PR-létrehozó API nélkül is elindulhasson. Nincs gate-gyengítés.
- A RELEASE-01/02/03 dokumentumok eredeti tartalma megmarad. A RELEASE-01 a
  javítás előtti történeti audit; B1 aktuális állapotát a RELEASE-02 és az RC
  eredménye határozza meg. A RELEASE-01 8. fejezetének korai javítási javaslata
  helyett a #36 tényleges, tesztelt implementációja az érvényes.
- A teljes `backend/`, `frontend/`, `compose.yaml` és `deploy/` változatlan a
  #37-hez képest. Nincs új migráció, séma-, paraméter- vagy donoradat-módosítás.

Ellenőrzések a teljes klónban:

```bash
git rev-parse HEAD
for input in ab7cf44 329146a a8bac7e 3df4b20; do
  git merge-base --is-ancestor "$input" HEAD || exit 1
done
git diff ab7cf44..HEAD -- backend frontend compose.yaml deploy
```

Az utolsó diff üres. A publikált RC pontos HEAD-jét, saját commitjait és a
hozzátartozó hosted futás URL-jét a végső átadás és a kész draft PR-leírás
rögzíti; nem a korábbi #37 vagy a külön #39 CI-zöldjét nevezzük RC-bizonyítéknak.

## Kötelező ellenőrzési mátrix

A végső **RC-HEAD-en** hét jobnak kell sikeresnek lennie:

| Job | Mit ellenőriz? |
|---|---|
| `backend` | Teljes backend/eszközteszt; dependency-lock és resolver; worker-only regisztráció; donor-, RBAC-, tenant-, CSRF- és migrációs regressziók |
| `browser` | A tényleges frontend bundle és FastAPI/SQLite együtt; 03A/03C, mobil/asztali, lock, forrásadat, token, limit, jóváhagyás/revízió, hibás DTO |
| `menu-export` | Önálló menüexport-eszköz tesztjei |
| `frontend` | Lint, lintkonfiguráció-tesztek, TypeScript és produkciós build |
| `docker` | Backend/frontend image build, runtime-függőségek és import |
| `mysql-migrations` | RELEASE-02, negatív kontroll **és RELEASE-01** az alábbi sorrendben |
| `ci-ok` | Mind a hat fenti job blokkoló összesítése |

A MySQL job az RC-n megtalálja a #34 `scripts/mysql_release01_check.py` fájlját.
Ezért a RELEASE-01 lépés **nem notice/skip**: resetelt üres adatbázison fut,
`pipefail` mellett a szkript hibája a job és a végső gate hibája.

1. `mysql_release02_downgrade_check.py --rounds 3`: 56 ellenőrzés; teljes séma,
   indexek, FK-k/szabályaik, 2000 előzetes termék/importsor, felhasználók,
   tagságok, szerepkörök, jogkatalógus lenyomata; ismételt down/up és döntésvédelmek.
2. Negatív kontroll: csak ideiglenes migrációmásolatba kerül vissza a 0010 két
   eredeti hibás `drop_index` sora. Az elvárt eredmény **exit 1 és MySQL 1553**.
   Ha a kontroll nem észleli a hibát, a job bukik. A repó migrációi változatlanok.
3. Újabb üresadatbázis-reset után `mysql_release01_check.py`: hat kötelező
   elvárás, upgrade és ismételt upgrade adatmegőrzése, jogok, védett/szabad downgrade.
   A félbeszakadt upgrade kísérlet külön B2 állapotot mutat ki; nem javítja azt.

A MySQL csak eldobható loopback service, szintetikus adatokkal. A konténer pontos
MySQL-verziója a napló része. A hosted `mysql:8.0` és a helyi `mysql:8.0.46`
eredményét külön kell feltüntetni. Ez **nem 250 000-es MySQL terhelési mérés**.
A 03D 250 000-es határteszt SQLite-bizonyíték marad.

Helyi backendparancs (Python 3.12, a projekt runtime+test lockjai):

```bash
PYTHONPATH=backend .venv/bin/pytest -q -ra backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
```

A MySQL-lépések reprodukciója: a `ci.yml` `mysql-migrations` jobjának `run`
blokkjai, a telepítési lépés után, külön üres eldobható MySQL-szolgáltatáson.
A reset/negatív kontroll/RELEASE-01 szkriptek **nem üzemeltetési parancsok**;
meglévő adatbázison, a VPS-en vagy `pinfo_db`-n tilos futtatni őket.

## Saját helyi MySQL-eredmény a közös fán

A CI job tényleges `run` blokkjait futtattuk, azonos sorrendben, saját eldobható
MySQL **8.0.46** konténeren, loopback porttal és üres app-adatbázissal:

- RELEASE-02: **56 ellenőrzés, 0 hiba, 3 kör, exit 0**, 27,8 s.
- Sémalenyomatok: `0008 2d7cf379f428add9`, `0009 f4aebc5d320cff5b`,
  `0010 89374986112d40b8`, `0011 7bb84020684f2cc0`.
- Negatív kontroll: **exit 1, 1553 és a hiányzó index felismerve**;
  a kontrollt ellenőrző joblépés exit 0.
- RELEASE-01: **6/6 elvárás igaz, exit 0**. A korábbi adatok megmaradnak,
  az öt jog megvan, a szerepkörök kiosztása a szerződést követi; jóváhagyással
  a downgrade megtagadott, jóváhagyás nélkül sikeres.
- A B2 szimuláció 0010-en hagyja a részleges sémát; a vak újrafuttatás
  `1060 Duplicate column name 'created_by'`. Ez a dokumentált helyreállítási korlát,
  nem a RELEASE-02 hibája és nem engedély újrapróbálásra valódi adaton.
- A segéd, regresszió, negatív kontroll, RELEASE-01 és summary együtt 52,77 s;
  minden joblépés exit 0. Csak szintetikus adatok és a saját tesztkonténer érintett.

Ezek **helyi** eredmények. A közös RC hosted CI-jét a publikált HEAD-en külön
kell ellenőrizni, a végső átadás konkrét futáslinkjével és mind a hét job állapotával.

## Blokkolók és fennmaradó korlátok

| Tétel | RC értékelése / teendő |
|---|---|
| B1, MySQL 1553 downgrade | A #36 javítása megmaradt; csak a sikeres RC MySQL-regresszió és hibát felismerő negatív kontroll után lezárt technikai blocker. |
| Bármely piros vagy hiányzó RC CI-job | Blokkoló. A korábbi #37/#39 zöld nem helyettesíti a közös futást. |
| B2, félbeszakadt MySQL upgrade | Ismert, runbookkal kezelt korlát; nincs automatikus újrafuttatás/downgrade. A staging előtt validált mentés és visszatöltési terv szükséges. |
| Staging jóváhagyás, mentés-visszatöltési próba, verzióegyezés | Telepítési előfeltételek; ebben a feladatban nem hajtjuk végre őket. |
| 3 vitatott donor | Változatlan `pending_review`, továbbra is blokkolt, nem release közben jóváhagyandó. |
| 250 000-es MySQL teljesítmény | Nem mért; nem ígérünk ilyen kapacitást. Külön jóváhagyott terhelési feladat. |
| Lejárt kiválasztási tételek takarítása | Korábbi, külön feladatra hagyott nem blokkoló tétel. |
| Tenant-helyi admin-sablonmásolatok és egyedi szerepkörök | Az új jogok delegálásáról a Tulajdonos dönt; nincs csendes jogosultságbővítés. |
| Élő Redis/worker újrakézbesítés és VPS-proxy | CI-val nem igazolt; staging smoke szükséges. |

A vitatott donorok: `web-item-114-3492` → 385,
`web-item-114-3820` → 58, `web-item-83-4339` → 63.
A jóváhagyott 13 gyökér és 457 besorolható kategória változatlan.

## Backend, worker, frontend és staging runbook

Ez **előkészítési terv, nem végrehajtás vagy telepítési engedély**.
Az operátori részletek: [RELEASE-01 §5](RELEASE-01-READINESS.md#5-staging-és-élesítési-runbook-csak-utasítás)
és a [RELEASE-02 runbook-pontosítása](RELEASE-02-DOWNGRADE.md#a-runbook-pontosítása-kiegészíti-a-release-01-56-pontját).

1. A Tulajdonos külön jóváhagyja a pontos RC/kiadási SHA-t, a dev.pinfo.hu
   karbantartási ablakát és a visszaállítás adatvesztési határát. A régi image-ek,
   kód, migrációs revízió, titkosítási kulcs és app-adatmentés legyenek rögzítve.
2. **Írások és futó feladatok rendezése**, frontend/backend/worker megállítása
   a jóváhagyott ablakban. Ne legyen régi worker az új backend mellett.
   A Redis jelenleg nem perzisztens (`--save '' --appendonly no`), ezért nem a
   broker a műveletek megbízható naplója: az app-adatbázis jobállapotát is fel kell mérni.
3. App-adatbázis-mentés **a migráció és minden `compose up` előtt**; külön üres
   környezetben visszatöltési próba, revízió és rekorddarabszámok ellenőrzése.
   A `pinfo_db` nem migrációs vagy visszatöltési cél. `.env`/kulcs nem kerül Gitbe.
4. Azonos jóváhagyott forrásból készült backend- és frontend-image.
   A worker és a migrátor ugyanazt a backend-image-et használja, eltérő commanddal.
   Egyetlen lánc: **0009 → 0010 → 0011**, egy head: 0011.
   A backend és a worker csak sikeres migráció után indulhat együtt; frontend utána.
   Az external `adatdusito-dev-net`, portok, Nginx/UFW/HTTPS változatlanok.
5. Backend/worker regisztráció: `supplier.import`, `products.reapply_category_map`,
   `products.parameter_run`, `products.operation` (és `infra.ping`). Valódi Redis
   elérés, brokerhiba, lease, pending/stalled, explicit resume és megszakítás
   ellenőrzése tesztbérlőben. A 03C futáslimit 50 000, snapshotlimit 250 000;
   ez nem azonos a kategóriatérkép 2000-es háttérváltási küszöbével.
6. Health live/ready, bejelentkezés, tenant/jogok, forrásadat és lock megőrzése,
   03A manuális módosítás utáni jóváhagyás-érvénytelenség; a három vitatott donor
   blokkolása. A tokenes megerősítések csak a megfelelő friss előnézetből induljanak.
7. Hiba esetén az aktuális állapotot meg kell őrizni, az írásokat és workereket
   leállítani. Részleges MySQL DDL-t nem javítunk vak újrafuttatással, downgrade-del
   vagy kézi DDL-lel: a validált app-mentés és a hozzá tartozó kód/image-ek együtt
   állnak vissza. A mentés óta keletkezett adatok elvesztéséről a Tulajdonos dönt.
   Új döntések/jóváhagyások után az üzleti downgrade továbbra is tiltott.

## A bizonyíték határa és a PR átadása

A hosted CI zöldje a közös forrás ellenőrzése; a MySQL job technikai migrációs
mérés szintetikus adatokkal. **A VPS, a valódi Redis/broker, a staging forgalom,
a helyi adminok tényleges jogai és az ottani backup-visszatöltés még nem tesztelt.**
Nincs kiadási engedély vagy main-merge a CI eredményéből.

Az új ág külön draft PR-t kap, a #37 draft marad, a korábbi PR-eket nem zárjuk le.
GitHub API 403 esetén a feltöltött branch, pontos SHA, kész PR-leírás és a
GitHub PR-létrehozó URL használható:
https://github.com/bizsis/adatdusito/pull/new/codex/release-candidate-01 .
A kész leírás a tényleges RC-HEAD és CI-futáslink alapján készül.
