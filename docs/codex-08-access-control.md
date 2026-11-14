# CODEX 08 – Jogosultságok, munkaterületek és meghívások

## Kiindulás és határok

A fejlesztés a működő CODEX 07 alkalmazást bővíti. A cookie, a scrypt jelszavak, a CSRF, a Redis belépési korlát és a globális felhasználóazonosító megmarad. Nincs külön auth-szolgáltatás. A `compose.yaml`, az external `adatdusito-dev-net`, a `.env`, a `0001`–`0006` migrációk és a referencia-kategóriaadatok változatlanok. Nincs újraimportálás, katalógusaktiválás vagy VPS-művelet.

Az előzetes felmérés kiterjedt a modellekre, a security/API/main modulokra, valamennyi migrációra, a React főfelületre és importmunkaterületre, az import/export/katalógus/audit végpontokra, a tesztekre, Compose-ra és README-re. Külön cég- és webáruház-entitás nem volt; most minimális nyilvántartás készült. A termékek korábban kizárólag ügyfélhez tartoztak.

## Adatmodell és migráció

A `0007_access_control` az `adatdusito_dev` adatbázisban nyolc új táblát hoz létre:

| Tábla | Tartalom |
| --- | --- |
| `access_roles` | Tulajdonos (`system`, `template`, `tenant:ID`), név, kód, permissionlista, kompatibilitási/protected jelzők. |
| `access_bindings` | Felhasználó + kontextus + szerepkör; több szerepkör egy munkaterületen. |
| `system_user_access` | Rendszerfiók ügyfélköre: `none`, `all`, `selected`. |
| `user_permission_exceptions` | Kontextusonkénti explicit engedély vagy tiltás. |
| `workspace_resource_access` | Teljes vagy kijelölt cég-/webáruházkör; új szerepkörkiosztás elsődlegessége. |
| `workspace_companies` | Ügyfélen belüli cég, név, aktív állapot. |
| `workspace_webshops` | Ügyfélhez és céghez kapcsolt webáruház, név, aktív állapot. |
| `user_invitations` | E-mail, kiosztás, tokenhash, lejárat, állapot, kézbesítés, meghívó és elfogadó. |

A meglévő `tenants` táblához az `ix_tenant_workspace_names(active,name,id)` index kerül. A `permissions` és `roles` új kódokkal bővül; a meglévő kódok és `role_permissions` nem törlődnek. A tagságok régi szerepkörei átkerülnek az új kapcsolótáblába. A régi `memberships.role` megmarad kompatibilitási mezőként, az új felületen több szerepkör kezelhető. A migráció minden korábbi tagságnak teljes ügyfélen belüli erőforráskört ad, ezért nem talál ki cég-/bolti hozzárendeléseket.

A felhasználók, jelszóhash-ek, munkamenetek, ügyfelek és tagságok megmaradnak, a kézzel létrehozott superadmin-tagságok is. A superadmin hozzáférése nem függ ezektől. Az Alembic revision táblája miatt az ismételt `upgrade head` nem szúrja be újra a jogosultságokat. Meglévő, egyedileg kialakított régi szerepköröket is megőrzi.

## Jogosultságok kiszámítása

Központi szolgáltatás: `app/access_control.py`; API-adapter: `access_api.py`. Minden kérés újra ellenőrzi a felhasználót és az aktuális kiosztást, nincs sessionbe fagyasztott permissionlista.

1. Aktív fiók és aktív, engedélyezett munkaterület ellenőrzése.
2. Releváns szerepkörök engedélyeinek uniója.
3. Egyedi engedélyek hozzáadása.
4. Egyedi tiltások levonása; a tiltás nyer.
5. Ügyfél-, cég- és webáruházkör ellenőrzése.
6. Műveletspecifikus és delegálási korlátok ellenőrzése.

A rendszerfelhasználó ügyfélmunkaterületen is saját rendszerszerepköreit használja. Nem örököl ügyféladmin-jogot, és nem jelenik meg automatikusan munkatársként. A superadmin védett hozzáférését a `users.superadmin` megőrzött jelző biztosítja; normál szerepkörből vagy ügyfélkivétellel nem alakítható át és nem vonható vissza. Az utolsó aktív superadmin letiltását és lefokozását zárolt tranzakció akadályozza meg.

Az ügyféladmin csak saját ügyfelén belül, a delegálható katalógusból és a saját effektív engedélyei erejéig oszthat. Más ügyfél szerepköre, erőforrása, rendszerjogosultság vagy védett szerepkör nem adható át. A tenant-szerepkörsablon szerkesztése helyi másolatot hoz létre, és csak az adott ügyfél kiosztásait/még függő meghívóit vezeti át; más ügyfelet nem érint.

### Kompatibilitás

A régi `system.manage`, `users.manage`, `tenants.manage`, `tenant.manage`, `exports.manage` kódokat dokumentált aliasréteg vezeti át a részletes engedélyekre. A régi `imports.manage` széles jelentése csak régi szerepkörből történő örökléskor bővül; új szerepkörben külön osztható a létrehozás, kezelés, jóváhagyás és megszakítás. Visszafelé alias csak valamennyi összetevő engedélyével képződik, tehát nem állít vissza tiltott műveletet.

A katalógus kizárólag megvalósított funkciókat sorol fel. A `products.create/edit/delete/approve` és `exports.create` nem dekorációként szerepelnek: önálló ilyen üzleti műveletek még nincsenek. A jelenlegi import-, termékmegtekintő és exportprofil/mező funkciók tényleges jogosultságokra vannak kötve. A referencia megtekintéséhez `reference.read`, központi szerkesztéséhez `reference.manage` kell.

### Erőforráskör fontos korlátja

A teljes kör a később létrehozott cégekre és webáruházakra is kiterjed. A kijelölt kör konkrét cég- és webáruház-azonosítókhoz kötött, új erőforrás nem kerül bele automatikusan, még kijelölt cég új boltja sem.

**A meglévő beszállítói termékek/importok/exportprofilok még nem tárolnak cég-/webáruház-kapcsolatot.** Kijelölt körű felhasználó ezért nem kap hozzáférést ezekhez a teljes ügyfélhez tartozó adatokhoz, illetve a munkatársak és teljes ügyfélaudit kezeléséhez. A rendszer nem találgatja az adatgazdát, és nem ad teljes hozzáférést részleges kör mellett. A névjegyzék erőforrásai ténylegesen szűrtek. Az effektív jogosultságok forrásánál `requires_full_workspace` jelzi a korlátozás okát. A későbbi feladat az üzleti rekordok explicit cég-/boltkapcsolatának migrációja és az ezekre épülő szűrés; ez most nem kész webáruház-integráció.

## API

Minden útvonal `/api/v1` alatt van; az író, hitelesített kérésekhez a meglévő CSRF szükséges. A `tenant_id` query paraméter a saját aktív ügyfélmunkaterületet jelöli; elhagyva a rendszerkontextust. A puszta ID ismerete nem jogosít hozzáférésre.

| Művelet | Végpont |
| --- | --- |
| Effektív állapot, források, elérhető munkaterületek | `GET /auth/me` |
| Ellenőrzött, naplózott váltás | `POST /auth/tenant` |
| Keresett/lapozott munkaterületek | `GET /access/workspaces?q=&offset=` |
| Magyar jogosultsági katalógus | `GET /access/catalog` |
| Szerepkörök | `GET/POST /access/roles`, `PUT/DELETE /access/roles/{id}` |
| Felhasználó szerepkörei, kivételei és köre | `GET/PUT /access/users/{user_id}` |
| Erőforráskör önálló kezelése | `GET/PUT /access/users/{user_id}/resources?tenant_id=` |
| Rendszerfiókok név/e-mail keresése | `GET /access/system-users?q=&offset=` |
| Felhasználó jogosultsági előzményei | `GET /access/history/{user_id}` |
| Cégek | `GET/POST /access/companies`, `GET/PATCH /access/companies/{id}` |
| Webáruházak | `GET/POST /access/webshops`, `GET/PATCH /access/webshops/{id}` |
| Meghívók | `GET/POST /invitations`, `POST /invitations/{id}/resend`, `POST /invitations/{id}/revoke` |
| Token ellenőrzése / tulajdonosi elfogadás | `POST /invitations/inspect`, `POST /invitations/accept` |

Megmaradnak a `/users`, `/tenants`, `/tenants/{id}/members`, `/audit`, `/settings`, import/export és referencia végpontok, új központi védelemmel. A globális fiókadatokat az ügyféladmin továbbra sem írhatja át. A korábbi ügyféloldali közvetlen fióklétrehozás helyett meghívás kell: a régi létrehozó végpont **új és meglévő e-mailre azonos 409 választ ad**, így nem lesz fiókfelderítő eszköz. A megbízható rendszeradminisztráció kompatibilitási végpontjai megmaradnak. A régi egyszerepkörös tagságmódosítás több új szerepkört nem lapíthat vissza észrevétlenül.

## Felület és munkaterület-váltás

Rendszerszinten „Rendszerhozzáférések”, ügyfélszinten „Munkatársak és hozzáférések” nézet: munkatársak, meghívók, szerepkörök, cégek/webáruházak; név/e-mail keresés, több szerepkör, csoportosított engedélyek, örökölt/engedélyezett/tiltott kivételek, effektív eredmény és források, előzmények. A superadmin rendszerfiók aktív/védett állapotot is kezelhet, az utolsó admin védelmével. Rendszerfiók ügyfélbeli erőforrásköre a rendszeradminisztrációból is megadható.

A munkaterület-választó külön, kereshető és lapozott API-t használ, nem csak a tagságokat. Superadmin valamennyi aktív ügyfelet név szerint látja tagság nélkül, köztük Molnarvegyi és Nomadsport munkaterületét is, ha léteznek és aktívak. Más rendszerfiók a kiosztott kört, ügyfélfiók az aktív tagságait látja.

Váltáskor a felület eldobja az előző munkaterületi komponenseket/állapotot, az elkésett válaszokat figyelmen kívül hagyja, újra lekéri a jogosultságokat. A jogosultságfrissítés 30 másodpercenként történik a nyitott felületen; a backend már a következő kérésnél érvényesíti a visszavonást. Nincs kliensoldali jogosultságra alapozott API-hozzáférés.

## Meghívás és SMTP

A meghívó véletlen, 32 bájtból képzett token; csak SHA-256 hash tárolódik. A link fragmentben hordozza (`/#invite=...`), az ellenőrzés/elfogadás POST-törzsben történik. A token nem kerül API-listába, auditba vagy alkalmazáslogba. Lejárt, visszavont és felhasznált token nem használható; újraküldéskor új token készül. Új meghívó ugyanahhoz a fiókhoz/kontextushoz, illetve új hozzáférési döntés visszavonja a korábbi függő linkeket: ezekkel nem állítható vissza később elvett jog.

Új felhasználó maga ad nevet és legalább 12 karakteres jelszót. Meglévő fiók tulajdonosának saját fiókjával be kell jelentkeznie és jóváhagynia a tagságot; jelszava és más ügyfélnél kapott jogosultsága nem változik. Az ügyféladmin saját munkatársait keresheti, más ügyfelek globális fiókjait nem böngészheti; e-mailes meghíváskor nem kap választ arra, hogy a cím másik ügyfélnél már ismert-e.

Az üzemeltető biztonságos csatornán állítja be a környezeti változókat. A fejlesztés nem írja át a VPS `.env` fájlját:

| Beállítás | Jelentés |
| --- | --- |
| `SMTP_HOST`, `SMTP_FROM` | Kötelező szerver és feladó. |
| `SMTP_PORT` | Alapértelmezés STARTTLS-nél 587, TLS-nél 465. |
| `SMTP_SECURITY` | `starttls` (alap), `tls`; `none` csak elkülönített helyi teszthez. |
| `SMTP_USER`, `SMTP_PASSWORD` | Ha a szolgáltató hitelesítést kér. Titkok, ne commitold. |
| `INVITE_TTL_HOURS` | Alap 48, megengedett tényleges tartomány 1–168 óra. |
| `APP_ORIGIN` | A meglévő `https://dev.pinfo.hu`, innen képződik a meghívólink. |

TLS-tanúsítvány-ellenőrzés bekapcsolva. SMTP hiányában/hibájánál a kérés 503, a meghívó kézbesítése `failed`; nincs színlelt siker, a felületen újraküldhető. A tényleges külső szolgáltatón történő kézbesítés üzemeltetői próba, itt eldobható helyi SMTP-kiszolgálóval teszteltük.

## Audit

A meglévő be-/kijelentkezés és munkaterület-váltás naplózása megmarad. Új `access.*` események: szerepkör-létrehozás/módosítás/törlés, kiosztás/kivételek/hatókör módosítása előző és új állapottal, cég-/boltműveletek, meghívás/újraküldés/visszavonás/elfogadás. Szerepel az eljáró, az érintett, ügyfél és időpont; nincs jelszó, sessiontitok vagy meghívótoken. A tagságmódosítás és globális aktív/superadmin állapot szintén naplózott.

## Tesztelés

Automatizált regresszió: `PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests`, előtte `cd frontend && npm ci && npm run build`. A Chromiumot `python -m playwright install --with-deps chromium` készíti elő; ha van rendszer-Chromium, a böngészőteszt azt használja.

Lefedés: több szerepkör és ügyfél, tiltás elsőbbsége, delegálási korlát, aktív sessionben visszavonás, rendszerfiók saját jogai, all/selected/none ügyfélkör, cég/bolt izoláció és új erőforrás, utolsó superadmin, meghívó lejárat/egyszeriség/elfogadás/újraküldés/visszavonás, e-mail magánszféra, tényleges helyi SMTP-kézbesítés, audit, alias kompatibilitás, import/export és referencia regresszió. Valódi FastAPI-t használó Playwright asztali (1440 px) és mobil (390 px) ellenőrzés: váltó, ügyfél- és rendszerszerepkör létrehozása/kiosztása, effektív tiltás, saját jelszavas meghívó.

Külön eldobható MySQL 8 példányon lefutott a `0006 → 0007`, ismételt `upgrade head`, kezdeti downgrade és vissza-upgrade: megmaradt a két fiók, három tagság, munkamenet, jelszóhash és CODEX 07 termék. A superadmin két név szerinti tesztügyfélbe tagság nélkül is átválthatott, az importadatok ügyfélhatára nem sérült. Ezek szintetikus tesztek, nem a VPS-en futottak.

A teljes helyi regresszió eredménye: **201 sikeres teszt**, 280,17 másodperc; frontend TypeScript/Vite build és mindkét Docker-image build sikeres. Egy meglévő Starlette/AnyIO elavulási figyelmeztetés maradt. A GitHub CI-futást a commit átadási üzenete rögzíti. A CI a teljes backend/böngészőtesztet, frontend-buildet, mindkét Docker-buildet és a menüexport tesztjeit futtatja.

## Kézi VPS-telepítés

**Ezeket az üzemeltető futtatja, a fejlesztés nem telepít a VPS-re.** Az importfeladatok befejezését várd meg. A karbantartás alatt a frontend/backend/worker röviden leáll; a MySQL, Redis, Nginx, hálózat, referenciaadatbázis és éles `pinfo.hu` nem áll le. A képernyőn ellenőrizd a konfigurációt, de `docker compose config` kimenetét ne publikáld, mert titkokat tartalmazhat.

Első blokk: tiszta Git-állapot, előző verzió és konfiguráció megőrzése, image-build. Ha helyi követett módosítás van, előbb egyeztesd; a parancs nem írja felül.

```bash
cd /opt/adatdusito
set -euo pipefail
umask 077
test -z "$(git status --porcelain --untracked-files=no)"
access_stamp=$(date -u +%Y%m%d-%H%M%S)
access_dir="/root/adatdusito-backups/codex08-$access_stamp"
mkdir -p "$access_dir"
git rev-parse HEAD > "$access_dir/previous-commit.txt"
cp -p .env compose.yaml "$access_dir/"
docker compose config --quiet
docker image tag adatdusito-dev-backend "adatdusito-dev-backend:before-codex08-$access_stamp"
access_frontend_image=$(docker compose images -q frontend | head -n 1)
test -n "$access_frontend_image"
docker image tag "$access_frontend_image" "adatdusito-dev-frontend:before-codex08-$access_stamp"
git fetch origin main
git merge --ff-only origin/main
docker compose config --quiet
docker compose build backend frontend
```

Második blokk: csak a saját alkalmazás áll le. Ezután konzisztens teljes alkalmazásmentés készül a migráció előtt. A `mysqldump` interaktívan kéri a MySQL-admin jelszavát; jelszót ne írj parancsargumentumba. Tartsd meg ezt a shellt és az `access_dir` változót; új shellnél állítsd be a valódi mentési útvonalra.

```bash
cd /opt/adatdusito
docker compose stop frontend backend worker
mysqldump -u root -p --single-transaction --no-tablespaces --routines --triggers adatdusito_dev | gzip > "$access_dir/adatdusito_dev.sql.gz"
gzip -t "$access_dir/adatdusito_dev.sql.gz"
sha256sum "$access_dir/adatdusito_dev.sql.gz" > "$access_dir/adatdusito_dev.sql.gz.sha256"
docker compose run --rm --no-deps migrate
docker compose up -d --no-deps backend worker frontend
docker compose exec -T backend alembic current
docker compose ps
docker compose logs --tail=80 backend worker
curl --fail --silent --show-error https://dev.pinfo.hu/api/health/live
```

A revision `0007` legyen. Ne futtass bootstrapot meglévő superadmin helyett, cloud fixture-t, katalógusimportot vagy aktiválást. A `migrate` csak a saját adatbázison fut. SMTP-t a szolgáltató adataival az üzemeltető konfigurálja a meglévő titokkezelésben; enélkül a meghívás kézbesítése tudatosan hibát jelez. Környezeti változtatás után backend/worker újralétrehozás szükséges.

### Kézi ellenőrzési jegyzék

1. Meglévő superadmin bejelentkezés; a név szerinti aktív Molnarvegyi és Nomadsport tagság létrehozása nélkül választható, kereshető. Válts oda-vissza: a terméklista és adatok követik az ügyfelet.
2. Rendszerhozzáférésekben hozz létre tesztszerepkört, adj csak olvasási jogot és kijelölt ügyfélkört egy tesztfióknak. Csak azt az ügyfelet lássa; írás és másik ügyfél API-ja 403.
3. Saját ügyfélnél szerepkör + több szerepkör kiosztása, explicit tiltás; az effektív lista mutassa a forrást. Másik böngészőben már bejelentkezett tesztfiókkal a tiltás következő API-kéréskor érvényes.
4. SMTP teszt: saját ellenőrzött e-mail-címre meghívó, új fiók saját jelszóval; meglévő fiók saját bejelentkezéssel fogadja el. Újraküldés után a régi, elfogadás után az új link sem használható újra. Más ügyfél tagsága változatlan.
5. Kijelölt cég/bolt kör: csak kijelölt szervezeti rekordok; ügyfélhez kötött, erőforrás nélküli termék/import ne legyen hozzáférhető. Teljes körű meglévő feldolgozóval CSV/XLSX, előnézet, jóváhagyás, worker és terméklista próba szintetikus fájllal.
6. Rögzített kategóriafa és paraméterérték-keresés változatlan; exportmezők megfelelő jogosultsággal működnek. Auditban látszik a váltás/kiosztás/meghívás, titkos token nem.
7. Tagság megszüntetése nem törli a fiókot vagy más ügyfele tagságát. Utolsó superadmin letiltása/lefokozása visszautasított. Mobilon is ellenőrizd a váltót és szerkesztőt.

## Visszaállítási terv

A mentés biztonságát külön, üres ellenőrző adatbázisba történő próba-visszaállítással ellenőrizd **még a karbantartási ablak előtt**. Az alábbi parancs csak új, külön sémát hoz létre és tölt fel, nem írja felül az alkalmazást; a mentés útvonalát helyettesítsd:

```bash
set -euo pipefail
access_restore_schema="adatdusito_restorecheck_$(date -u +%Y%m%d%H%M%S)"
mysql -u root -p -e "CREATE DATABASE \`$access_restore_schema\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
gzip -dc /root/adatdusito-backups/IDE-A-VALOS-MENTES/adatdusito_dev.sql.gz | mysql -u root -p "$access_restore_schema"
mysql -u root -p "$access_restore_schema" -e 'SELECT version_num FROM alembic_version; SELECT COUNT(*) AS users FROM users; SELECT COUNT(*) AS memberships FROM memberships; SELECT COUNT(*) AS sessions FROM login_sessions;'
```

Ez csak mentésellenőrzés, az alkalmazás adatbázis-URL-jét nem állítja át. A nagy katalógus miatt időt és szabad tárhelyet igényel. Az ellenőrző sémát csak kézi felülvizsgálat után takarítsd el.

**Korai rollback**, ha még senki nem használt CODEX 08 hozzáféréskezelést és nincs `access.*` auditesemény: az alkalmazás álljon, az új image migrációja visszaléphet `0006`-ra. A downgrade maga is ellenőrzi ezt, és változtatás esetén megtagadja az új jogosultságtáblák törlését.

```bash
cd /opt/adatdusito
set -euo pipefail
# access_dir és access_stamp az eredeti telepítési blokk valódi értékei.
docker compose stop frontend backend worker
docker compose run --rm --no-deps migrate alembic downgrade 0006
access_previous_commit=$(cat "$access_dir/previous-commit.txt")
git switch --detach "$access_previous_commit"
docker image tag "adatdusito-dev-backend:before-codex08-$access_stamp" adatdusito-dev-backend
docker image tag "adatdusito-dev-frontend:before-codex08-$access_stamp" adatdusito-dev-frontend
docker compose up -d --no-deps backend worker frontend
```

**Új jogosultsági döntések után** a régi alkalmazást nem szabad ráengedni az új adatbázisra: nem értené az új tiltásokat és több szerepkört. Ilyenkor elsődleges a javító frissítés. Ha teljes visszaállítás szükséges, DBA-val karbantartási ablakban: alkalmazás leállítása → aktuális állapot külön mentése → migráció előtti teljes mentés ellenőrzött próba-visszaállítása → későbbi üzleti változások egyeztetése → az alkalmazásséma ellenőrzött teljes helyreállítása → megfelelő korábbi image indítása → jogosultsági és üzleti ellenőrzés. A meglévő sémára történő egyszerű dump-ráimport nem elég (új FK-táblák és jogosultságadatok maradhatnának). Nincs automatikus éles DROP/újrainicializálás; az adatvesztési és visszavont jogosultságok visszatérésének kockázatát az üzemeltetővel előbb rendezni kell. A `pinfo_db` egyik eljárásban sem szerepel.

## Következő ütem

Az üzleti rekordok explicit cég-/webáruház-kapcsolata külön migrációt igényel. A globális `users.id` alkalmas későbbi több hitelesítési mód idegen kulcsára; TOTP, passkey/WebAuthn, Google OIDC, kötelező 2FA, számlázás és AI-kreditek ebben az ütemben nem készültek.
