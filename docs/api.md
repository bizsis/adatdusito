# API és hozzáférési modell

Alapútvonal: `/api/v1`. OpenAPI JSON: `/api/v1/openapi.json`, Swagger UI: `/api/v1/docs` – mindkettő bejelentkezéshez kötött. A régi `/api/health/live` és `/api/health/ready` útvonal változatlan.

## CODEX 04: saját referenciaazonosítók

A `0005` séma és az ellenőrzött katalógus külön aktiválása után a referencia-végpontok a saját adatbázisból dolgoznak. A 13 főcsoportos `/reference/navigation` marad az egyetlen közös böngésző API-ja. Aktiválásig a korábbi olvasó szolgálja ki ugyanazt a felületet. [Import, teljes ellenőrzés és visszaállítás](codex04.md).

- Navigációs adatlap: `unified_category_id` = saját közös kategória-ID, `catalog_version_id` = adatverzió. A meglévő szöveges navigációs `id` útvonal-/aliasazonosító marad.
- Kategóriaválasztás: a `/reference/navigation/{id}/selection` válasz `category_id` mezője aktivált katalógusnál a saját kategória-ID. A későbbi termékek ezt használják.
- Paraméterlista: `parameter_id` = közös paraméterdefiníció; `id` és `category_parameter_id` = az adott kategória paraméterkapcsolata. Az `/reference/parameters/{id}/values` végpontnak a **kapcsolat** azonosítóját add át, hogy a kategóriaspecifikus értékkészletet kapd.
- Értéklista: az `id` a közös érték-ID, a `next_cursor` változatlanul a következő oldalhoz használható. Eredeti forrásrekordok egyező paraméter + pontosan egyező értékszöveg esetén közös értékre hivatkozhatnak; minden eredeti tagság és sorrend megmarad.
- Adminisztrátori választás: `POST /reference/navigation/{id}/assignment`, `{ "category_id": <közös ID> }`, vagy `{ "parent_id": "<navigációs szülő>" }`. Saját katalógus mellett a visszaállítás az importált állapotot állítja vissza. Nincs hash-bekérés.
- A korábbi numerikus forrás-kategória- és kategóriaparaméter-azonosítók kompatibilitási feloldása megmarad. A saját ID-k legalább 1 000 000 000 értékűek; az eredeti eMAG külső azonosító külön metaadat, nem közös ID.
- Az aktív katalógus hibája 503, nem automatikus forrás-visszaesés. Az aktiválás/rollback operátori CLI, nem tenantművelet. A `pinfo_db`-hez továbbra sincs író API.

Az alábbi eredeti referencia-ID-leírások az aktiválás előtti, illetve forrás-kompatibilitási üzemmódot dokumentálják. A jogosultsági, CSRF- és ügyfélelkülönítési szerződés mindkét üzemmódban változatlan.

## Hitelesítés

A `POST /auth/login` JSON email/password mezőkkel lép be; a válasz `csrf_token` értéket és HttpOnly, Secure, SameSite=Strict, hosthoz kötött cookie-t ad. A véletlen munkamenettokennek csak SHA-256 kivonata kerül az alkalmazás-adatbázisba. Abszolút élettartama 8 óra; új belépés tokenforgatást végez. Jelszavakhoz scrypt N=131072, r=8, p=1, egyedi 16 bájtos só, állandó idejű összehasonlítás használatos.

Minden bejelentkezett módosító kéréshez `X-CSRF-Token` kell; ez a login vagy a `GET /auth/me` válaszából olvasható. A token a titkos session-cookie-hoz kötött, kliensoldali tartós tárolás nincs. Más Originről érkező módosítás tiltott; CORS nincs engedélyezve. A bejelentkezés JSON-t fogad, idegen Originről elutasított. Éles/HTTPS-szerű fejlesztői domainen `COOKIE_SECURE` maradjon true.

A belépési kísérleteket Redisben, atomikusan korlátozzuk: 10/account/15 perc és 300 socket-peer/15 perc. A továbbított IP-fejlécek nem megbízhatóak, ezért a közös frontendproxy peer-limitje szándékosan tágabb. Redis-hibánál a bejelentkezés 503-mal leáll. Több API-folyamat közös korlátot használ.

Kijelentkezéskor, jelszócserénél és globális adminisztrátori jogosultságmódosításnál a munkamenetek visszavonhatók. Az aktív user-, tenant- és tagságállapot minden kérésnél újra ellenőrzött, nem kliensoldali szerepkörből származik. Visszavont tagság után másik ügyfél kiválasztható, vagy ki lehet lépni.

## Jogosultságok

| Funkció | Superadmin | Ügyféladminisztrátor | Adatfeldolgozó / Ellenőrző |
| --- | --- | --- | --- |
| Saját munkamenet, jelszó, tenantválasztás | Igen | Igen | Igen |
| Ügyféllista | Összes | Saját tagságai | Saját tagságai |
| Ügyfél létrehozása, állapotkezelése | Igen | Nem | Nem |
| Ügyfél nevének szerkesztése | Igen | Aktív saját ügyfél | Nem |
| Globális felhasználók, Superadmin-jog, hozzárendelés | Igen | Nem | Nem |
| Új ügyfélfelhasználó, saját tagságok szerepe/állapota | Igen | Aktív saját ügyfél | Nem |
| Felhasználó neve, jelszó-visszaállítás | Igen | Csak kizárólag saját ügyfélhez tartozó, nem Superadmin-fiók | Nem |
| Referenciaadatok olvasása | Igen | Igen | Igen |
| Műveleti napló | Összes | Csak aktív saját ügyfél | Nem |
| Rendszerkonfiguráció | Igen | Nem | Nem |

A tagság ügyfelenkénti szerepkörrel rendelkezik, globális Superadmin-jog kizárólag a felhasználóhoz tartozik. Az utolsó aktív Superadmin és az utolsó aktív ügyféladmin eltávolítása tiltott; adminváltásokat tranzakciós zárolás védi. Egy megosztott felhasználó globális jelszavát és nevét tenantadmin nem módosíthatja. Saját jelszóhoz a régi jelszó megadása szükséges. Nem várt tenant-hozzáférés 404-et vagy 403-at ad, idegen ügyfél adatait nem listázza.

## Végpontok

| Módszer | Útvonal | Rendeltetés |
| --- | --- | --- |
| POST | /auth/login, /auth/logout | Belépés / kilépés |
| GET | /auth/me | Saját fiók, tagságok, jogosultságok, CSRF-token |
| POST | /auth/tenant | Aktív tenant választása (`tenant_id`); rendszerszint csak Superadminnak |
| POST | /auth/password | Saját jelszócsere (`current_password`, `password`) |
| GET, POST | /tenants | Lapozott ügyféllista / létrehozás |
| PATCH | /tenants/{tenant_id} | Ügyfél szerkesztése |
| GET, POST | /users | Globális lapozott felhasználók / létrehozás |
| PATCH | /users/{user_id} | Név, aktivitás, Superadmin-jog, jelszó |
| GET, POST | /tenants/{tenant_id}/members | Tagságok / meglévő user hozzárendelése |
| PATCH | /tenants/{tenant_id}/members/{user_id} | Szerepkör, tagság aktív állapota |
| POST | /tenants/{tenant_id}/users | Új fiók és tagság egy tranzakcióban |
| PATCH | /tenants/{tenant_id}/users/{user_id} | Kizárólagos ügyfélfiók neve / jelszava |
| GET | /audit | Lapozott, jogosultság szerint szűrt napló |
| GET | /settings | Rendszerbeállítások |
| PUT | /settings/{key} | Csak display_name és admin_notice, titkok nélkül |
| GET | /system/status | Hitelesített részletes szolgáltatásállapot |
| GET | /reference/categories | Gyökerek, alkategóriák, név-/eMAG-ID-keresés |
| GET | /reference/categories/{id} | Belső ID szerinti adatlap és feloldott szülőlánc |
| GET | /reference/parameters | category_id (belső), q, mandatory szerinti paraméterkeresés |
| GET | /reference/parameters/{id}/values | Belső paraméter-ID szerinti értéklista |

Általános lapozás: `offset=0&limit=25`, maximum 100 elem. Referenciák offsetje legfeljebb 10000. Értékekhez keyset-lapozás: `after=0&limit=50`, majd a `next_cursor` értékét add az `after` paraméterbe, amíg `has_more=false`. Nincs több millió soros COUNT az értéklistákhoz. A név és szöveg keresése escaped részszövegkeresés; egy nagy paraméterhalmaz keresése költségesebb lehet. A meglévő referenciaindexeket nem módosítjuk.

A kategóriáknál `parent_id` a feloldott **belső** szülőazonosító; `parent_emag_id` az eredeti referenciaérték. Az API `parent_id` szűrője belső kategória-ID-t vár, és a lekérdezés alakítja át eMAG-ID-ra. A `missing_parent` és `hierarchy_error` nem hallgatja el a hiányos/körkörös referenciákat. A numerikus `type_id` értékeknek nem találunk ki szöveges típust: az adatbázisban tárolt érték és a beállítási flag-ek jelennek meg.

Hibaformátum: `{"error":{"code":"403","message":"…"}}`. Validációs hibánál mezőhely és hibatípus szerepel, a beküldött jelszó és request body nem. 401: nincs érvényes munkamenet; 403: jog/CSRF/Origin; 404: nincs hozzáférhető erőforrás; 409: ütközés/védett utolsó admin; 422: bemenet; 429: belépési limit; 503: infrastruktúrahiba. Az API-válaszok no-store fejléccel készülnek.

## Adatbiztonság és határok

Az alkalmazás-metaadat csak az adatdusito_dev tábláit tartalmazza. A referencia-Core metadata különálló; nincs migrációs, INSERT/UPDATE/DELETE referenciaútvonal. A referencia-engine nem SELECT jellegű utasítást megtagad, a tranzakció read-only, és a legfontosabb védelem a külön SELECT-only MySQL-felhasználó. Adminmódosítás és audit ugyanabban az alkalmazás-tranzakcióban történik; jelszó és sessiontoken nem kerül auditadatba.

Ez a fázis nem tartalmaz regisztrációs/jelszó-visszaállító emailt, MFA-t, importot, AI-t, kreditet vagy szinkronizálót. A JSON API csak azonos originről támogatott; a termék HTTPS reverse proxy mögött működik. A display_name/admin_notice jelenleg adminisztrációs konfigurációs rekord, nem globális felületfelülírás.


## CODEX 03A: strukturális navigáció és besorolhatóság

Ez a kiadás felváltja a korábbi, kizárólag aktív rekordokat mutató szabályt. `view=navigation` az alapérték: a besorolható kategóriák teljes ismert, nem törölt szülőlánca navigálható. A `view=all` ugyanennek a fának minden nem törölt referenciaágát is megmutatja. Ez nem két kategóriarendszer. A szűrő a kategóriákon, a paramétereken és az értékeken is használható.

A kategória DTO `selectable`, `classification`, `reference_key`, `in_navigation`, `path`, `ancestors`, `children_count`, `parameter_count`, `mandatory_parameter_count`, `optional_parameter_count`, `unknown_parameter_count`, `cycle_break`, `hierarchy_error` adatokat ad. A névben Deleted jelölésű rekord mindig rejtett; nem tételezünk fel új, sémában nem létező törlési flag-et. Az ismeretlen szülő eredeti eMAG-ID-ja megmarad. A strukturális szülőt a valódi eMAG-ID alapján oldjuk fel, nem dobjuk el azért, mert is_allowed=0.

Új végpontok:

- `GET /reference/categories/{belső_id}/selection`: kizárólag besorolható kategóriához ad előkészítő szerződést (strukturálisra 409). Nincs terméklétrehozás. Közvetlen paraméterforrás, automatikus öröklés nélkül; új érték csak későbbi jóváhagyási javaslat lehet.
- `GET /reference/coverage`: élő, csak olvasó lefedettségi és integritási jelentés. A webshop teljessége mindaddig unverified, amíg nincs igazolt forrás.
- `GET /reference/sources`: közös forrásregiszter.
- `GET /reference/sources/observations`: lapozott, közös forrásmegfigyelések.
- `POST /reference/sources/observations`: Superadmin által rögzített, auditált forrásbizonyíték. A pending forrás-ID nem lesz automatikusan kanonikus kategória; névegyezés nem elegendő megerősítéshez.

Részletes szerződés és forrásvizsgálat: [codex03a.md](codex03a.md).
