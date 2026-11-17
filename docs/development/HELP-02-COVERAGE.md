# HELP-02 – képernyő-, művelet- és tartalomleltár

**Vizsgált alap:** `codex/help-01` / `a8fdea527053b637bd56a56cb12d9f469b3506b6`. **Munkaág:** `codex/help-02-complete-manual`. A leltár első változata a cikkek bővítése előtt, külön commitban készült. A dokumentum nem a VPS aktuális verzióját igazolja.

## Állapot és bizonyíték

36 cikk, 8 témakör, 52 PNG (9 korábbi + 43 új), 40 képernyő-/műveletcsoport. A 12 eredeti cikk URL-je megmaradt. A strukturális teszt a tényleges `main.tsx` menütömbjéből is ellenőrzi a lefedettséget.

**Emberi tartalmi jóváhagyás még szükséges.** A „dokumentált” azt jelenti, hogy a vizsgált forráshoz tartozó használati leírás, előfeltétel, mezőmagyarázat, demó, várt eredmény és hibakezelés elkészült. Nem jelenti az összes adminisztratív írási művelet E2E-tesztjét vagy minden szolgáltató/eszköz kipróbálását. A képernyőképek szintetikus SQLite-adatokkal, a valódi frontend bundle és FastAPI-végpontok használatával készültek.

- `test_help_browser.py`: navigáció, bejelentkezési határ, üzleti jog nélküli olvasás, 390/1440 px, URL/vissza/kép, mobil hash-versenyhelyzet és eredeti munkafolyamatok.
- `test_help_manual_browser.py`: hosszú cikk tartalomjegyzék/táblázat/fókusz, képernyő-megnyitás és képfelvétel; referenciafa/értéklista; írott demó végigjárása; olvasó alkalmazási jog nélkül; valódi 409 és vak ismétlés tiltása.
- A további üzleti viselkedés regresszióját a meglévő teljes backend- és böngészőcsomag ellenőrzi. A forrásfájlok az alábbi táblában és a géppel ellenőrzött `coverage.json` fájlban szerepelnek.

## Leltár

| Menü / képernyő és műveletek | Jogosultság / környezet | Cikk | Forrás / API-implementáció | Képek | Állapot |
|---|---|---|---|---|---|
| Fejléc / Munkaterület: Keresés; munkaterületváltás; további találatok; Rendszerszint | bejelentkezett; engedélyezett ügyfél | [belepes-munkaterulet](../../frontend/src/support/articles/belepes-munkaterulet.json) | `frontend/src/main.tsx`; `backend/app/api.py` | [ugyfelek](../../frontend/public/help/images/ugyfelek.png); [munkaterulet](../../frontend/public/help/images/munkaterulet.png) | dokumentált; emberi ellenőrzésre vár |
| Áttekintés; Ügyfelek: Állapot; ügyfél létrehozás/szerkesztés/felfüggesztés; lapozás; munkaterület megnyitása; technikai Swagger | tenants.read/create/edit/suspend | [attekintes-ugyfelek](../../frontend/src/support/articles/attekintes-ugyfelek.json) | `frontend/src/main.tsx`; `backend/app/api.py` | [attekintes](../../frontend/public/help/images/attekintes.png); [ugyfel-letrehozas](../../frontend/public/help/images/ugyfel-letrehozas.png) | dokumentált; emberi ellenőrzésre vár |
| Fejléc / Biztonság; Jelszó: Újraazonosítás; felhasználónév; jelszócsere; munkamenet visszavonás; kijelentkezés | saját bejelentkezett fiók | [sajat-fiok-biztonsag](../../frontend/src/support/articles/sajat-fiok-biztonsag.json) | `frontend/src/AuthViews.tsx`; `backend/app/auth_api.py` | [sajat-fiok](../../frontend/public/help/images/sajat-fiok.png); [jelszocsere](../../frontend/public/help/images/jelszocsere.png); [munkamenetek](../../frontend/public/help/images/munkamenetek.png) | dokumentált; emberi ellenőrzésre vár |
| Biztonság / TOTP és helyreállítási kódok: Aktiválás; csere; kódforgatás; visszavonás; kétlépcsős admin-helyreállítás | saját fiók + friss újraazonosítás; admin-helyreállítás: superadmin | [totp-helyreallitas](../../frontend/src/support/articles/totp-helyreallitas.json) | `frontend/src/AuthViews.tsx`; `backend/app/auth_api.py` | [totp-allapot](../../frontend/public/help/images/totp-allapot.png); [admin-helyreallitas](../../frontend/public/help/images/admin-helyreallitas.png) | dokumentált; emberi ellenőrzésre vár |
| Bejelentkezés; Biztonság / Passkey; Google: Passkey hozzáadás/törlés/bejelentkezés; Google kapcsolás; e-mail regisztráció/megerősítés | engedélyezett mód; eszköz/HTTPS; saját fiók | [passkey-google-regisztracio](../../frontend/src/support/articles/passkey-google-regisztracio.json) | `frontend/src/AuthViews.tsx`; `backend/app/oidc_api.py` | [passkey-allapot](../../frontend/public/help/images/passkey-allapot.png); [google-allapot](../../frontend/public/help/images/google-allapot.png) | dokumentált; emberi ellenőrzésre vár |
| Beszállítói import / Beszállító: Létrehozás; kiválasztás; beszállítónkénti profilok | ügyfél; imports.read/manage | [beszallito-letrehozasa](../../frontend/src/support/articles/beszallito-letrehozasa.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_api.py` | [fajlbeallitasok](../../frontend/public/help/images/fajlbeallitasok.png); [beszallito](../../frontend/public/help/images/beszallito.png) | dokumentált; emberi ellenőrzésre vár |
| Beszállítói import / CSV/XLSX fájl: Feltöltés; elemzés; munkalap; fejléc; elválasztó; kódolás | ügyfél; imports.read/create | [csv-xlsx-feltoltes](../../frontend/src/support/articles/csv-xlsx-feltoltes.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_api.py` | [fajlbeallitasok](../../frontend/public/help/images/fajlbeallitasok.png); [feltoltes](../../frontend/public/help/images/feltoltes.png) | dokumentált; emberi ellenőrzésre vár |
| Beszállítói import / Oszlopok: Forrás/belső/cél oszlop; bizalom; minta; ismeretlen adatok; importprofil vs exportprofil | imports.read; mentés: imports.approve | [oszlopok-megfeleltetese](../../frontend/src/support/articles/oszlopok-megfeleltetese.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_engine.py` | [fajlbeallitasok](../../frontend/public/help/images/fajlbeallitasok.png); [oszlopok](../../frontend/public/help/images/oszlopok.png) | dokumentált; emberi ellenőrzésre vár |
| Beszállítói import / Jóváhagyás: Importprofil; pénzügyi megerősítés; feldolgozás; jóváhagyás és olvasás különbsége | imports.approve | [import-jovahagyasa](../../frontend/src/support/articles/import-jovahagyasa.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_api.py` | [import-jovahagyas](../../frontend/public/help/images/import-jovahagyas.png) | dokumentált; emberi ellenőrzésre vár |
| Beszállítói import / Feed és összekapcsolás: Identitás; csatlakozási kulcs; teljes/részleges/ár/készlet/műszaki feed; beszerzési és eladási ár | imports.approve | [import-kulcsok-penzugy](../../frontend/src/support/articles/import-kulcsok-penzugy.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_engine.py` | [import-jovahagyas](../../frontend/public/help/images/import-jovahagyas.png) | dokumentált; emberi ellenőrzésre vár |
| Beszállítói import / Futástörténet: Állapot; szünet/folytatás; hibák CSV; eredeti fájl; forrásretenció; jelenlegi UX-korlátok | imports.read/cancel/manage/create műveletfüggő | [import-elozmenyek-hibak](../../frontend/src/support/articles/import-elozmenyek-hibak.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_api.py` | [fajlbeallitasok](../../frontend/public/help/images/fajlbeallitasok.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Termékek / Megnyitás: Keresés; állapotszűrés; saját/belső kategória; kézi besorolás; előnézet; védelem; revízió | products.read; módosítás: products.classify | [termekek-kategorizalasa](../../frontend/src/support/articles/termekek-kategorizalasa.json) | `frontend/src/classification/ClassificationWorkspace.tsx`; `backend/app/workspace_views.py` | [kategorizalas](../../frontend/public/help/images/kategorizalas.png) ; [termeklista](../../frontend/public/help/images/termeklista.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Kategóriatérkép: Saját kategória megfeleltetés; örökítés; jóváhagyás/elutasítás/törlés; 2000 felett háttér | products.read/classify | [kategoriameterkep](../../frontend/src/support/articles/kategoriameterkep.json) | `frontend/src/classification/ClassificationEditor.tsx`; `backend/app/workspace_views.py` | [kategoriameterkep](../../frontend/public/help/images/kategoriameterkep.png) | dokumentált; emberi ellenőrzésre vár |
| Kategóriák: 13 gyökér; fix hierarchia; keresés; profilok; admin hozzárendelés; hiányzó forrás; forráslefedettség | reference.read; szerkesztő: system.manage | [kozos-kategoriafa](../../frontend/src/support/articles/kozos-kategoriafa.json) | `frontend/src/main.tsx`; `backend/app/web_navigation.py` | [kozos-kategoriafa](../../frontend/public/help/images/kozos-kategoriafa.png); [kategoria-parameterek](../../frontend/public/help/images/kategoria-parameterek.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Termék / Paraméterprofil: Egy/több profil; explicit választás; pending_review; navigáció vs paraméterforrás | products.read/classify | [emag-donorprofilok](../../frontend/src/support/articles/emag-donorprofilok.json) | `frontend/src/parameters/LiveParameters.tsx`; `backend/app/product_parameters.py` | [kategoria-parameterek](../../frontend/public/help/images/kategoria-parameterek.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Automatikus besorolás; Rendszerbeállítások / Kategóriabesorolás: 98% küszöb; kalibráció; mérés hiánya; kézi védett döntés | products.read/classify; system.settings.read/manage | [besorolasi-kuszob](../../frontend/src/support/articles/besorolasi-kuszob.json) | `frontend/src/classification/ClassificationThreshold.tsx`; `backend/app/product_catalog.py` | [beallitas-kuszob](../../frontend/public/help/images/beallitas-kuszob.png) | dokumentált; emberi ellenőrzésre vár |
| Paraméterkereső; Kategóriák / Paraméterek / Értékek: Paraméternév/ID; kötelező/opcionális; keresés; értékoldalazás; nincs globális értékszerkesztő | reference.read | [parameterkereses](../../frontend/src/support/articles/parameterkereses.json) | `frontend/src/main.tsx`; `backend/app/reference.py` | [parameterkereso](../../frontend/public/help/images/parameterkereso.png); [megengedett-ertekek](../../frontend/public/help/images/megengedett-ertekek.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Paraméterek; Termék / Paraméter-előkészítés: Nyers/normalizált; konverzió; hét állapot; előnézet/alkalmazás; eredeti forrás | products.read; alkalmazás: products.parameters | [parameterallapotok](../../frontend/src/support/articles/parameterallapotok.json) | `frontend/src/parameters/ParameterWorkspace.tsx`; `backend/app/product_parameters.py` | [parameterallapotok](../../frontend/public/help/images/parameterallapotok.png); [hianyzo-parameterek](../../frontend/public/help/images/hianyzo-parameterek.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Termék / Kézi paraméterdöntés: Érték; forrásjelölt; zárolás/feloldás/reset; indok; revízió; audit; kötött értéklista | products.parameters | [kezi-parameterek](../../frontend/src/support/articles/kezi-parameterek.json) | `frontend/src/parameters/LiveSlotEditor.tsx`; `backend/app/parameter_views.py` | [kezi-parameter](../../frontend/public/help/images/kezi-parameter.png); [revizio-utkozes](../../frontend/public/help/images/revizio-utkozes.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Termék / Aliasszabályok: Keresés; hatókör; státusz; új alias; jóváhagyás; visszavonás | products.parameters; globális: parameters.global_aliases.manage | [aliasok](../../frontend/src/support/articles/aliasok.json) | `frontend/src/parameters/LiveAliases.tsx`; `backend/app/parameter_views.py` | [aliasok](../../frontend/public/help/images/aliasok.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Termék / Paraméterhelyek háttérfutása: Hatókör; preview/apply; futásazonosító; 50000-es limit; elakadás; nincs vak újraindítás | products.read/parameters | [parameter-hatterfutas](../../frontend/src/support/articles/parameter-hatterfutas.json) | `frontend/src/parameters/LiveRuns.tsx`; `backend/app/product_jobs.py` | [parameter-futas](../../frontend/public/help/images/parameter-futas.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Paraméterek / Rögzített termékkör: Aktuális oldal vs teljes szűrt állomány; 250000; 2 óra; token; szűrőváltás | products.read | [tomeges-kijeloles](../../frontend/src/support/articles/tomeges-kijeloles.json) | `frontend/src/parameters/LiveBulkPreparation.tsx`; `backend/app/bulk_operations.py` | [tomeges-kijeloles](../../frontend/public/help/images/tomeges-kijeloles.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Paraméterek / Tömeges paraméter-előnézet: Előnézet; eligible/kihagyott/hibás; alkalmazás; idempotencia; 50000/futás; megszakítás/folytatás | products.parameters + products.bulk | [tomeges-jovahagyas](../../frontend/src/support/articles/tomeges-jovahagyas.json) | `frontend/src/parameters/LiveBulkPreparation.tsx`; `backend/app/bulk_views.py` | [tomeges-olvasasi-jog](../../frontend/public/help/images/tomeges-olvasasi-jog.png); [tomeges](../../frontend/public/help/images/tomeges.png) | dokumentált; emberi ellenőrzésre vár |
| Termékadatok / Paraméterek / Előkészítési ellenőrzés; Jóváhagyások: Check/approve; invalid; újramérés; visszavonás; elavult termékek; nincs kutatásindítás | products.read; döntés: products.prepare.approve | [elokeszitesi-jovahagyas](../../frontend/src/support/articles/elokeszitesi-jovahagyas.json) | `frontend/src/parameters/ApprovalReview.tsx`; `backend/app/bulk_operations.py` | [elokeszitesi-ellenorzes](../../frontend/public/help/images/elokeszitesi-ellenorzes.png); [elokeszitesi-megerosites](../../frontend/public/help/images/elokeszitesi-megerosites.png); [elokeszitesi-jovahagyas](../../frontend/public/help/images/elokeszitesi-jovahagyas.png) | dokumentált; emberi ellenőrzésre vár |
| Export / Webáruházmotorok → Exportmezők: Motor; mező; típus; kötelező; alapérték; validáció; referenciaminta; saját profil; nincs exportgenerálás | exports.read/profile; központi: exports.fields.manage | [exportprofilok](../../frontend/src/support/articles/exportprofilok.json) | `frontend/src/ImportWorkspace.tsx`; `backend/app/import_api.py` | [exportprofil](../../frontend/public/help/images/exportprofil.png) | dokumentált; emberi ellenőrzésre vár |
| Munkatársak és hozzáférések; Rendszerhozzáférések: Tényleges jogok; szerepek; egyedi engedély/tiltás; tiltás elsőbbsége; erőforráshatókör | members.read vagy system.users.read/system.roles.read | [jogosultsagok](../../frontend/src/support/articles/jogosultsagok.json) | `frontend/src/AccessWorkspace.tsx`; `backend/app/access_api.py` | [munkatarsak](../../frontend/public/help/images/munkatarsak.png); [jogkatalogus](../../frontend/public/help/images/jogkatalogus.png) | dokumentált; emberi ellenőrzésre vár |
| Rendszerhozzáférések / Rendszerfelhasználók; Munkatársak: Új rendszerfelhasználó; keresés; hozzáférés; fióktiltás vs tagság; superadmin; ideiglenes jelszó | system.users.manage vagy members.manage; szerepkör: members.roles.manage | [felhasznalok-tagsagok](../../frontend/src/support/articles/felhasznalok-tagsagok.json) | `frontend/src/AccessWorkspace.tsx`; `backend/app/access_api.py` | [rendszerfelhasznalok](../../frontend/public/help/images/rendszerfelhasznalok.png) | dokumentált; emberi ellenőrzésre vár |
| Hozzáférések / Szerepkörök; Jogosultsági katalógus: Saját szerepkör; kód; jogosultsági mátrix; sablonmásolat; védett szerep; törlés | system.roles.read/manage vagy members.read/roles.manage | [szerepkorok](../../frontend/src/support/articles/szerepkorok.json) | `frontend/src/AccessWorkspace.tsx`; `backend/app/access_api.py` | [szerepkorok](../../frontend/public/help/images/szerepkorok.png); [szerepkor-szerkeszto](../../frontend/public/help/images/szerepkor-szerkeszto.png) | dokumentált; emberi ellenőrzésre vár |
| Hozzáférések / Meghívások; Meghívó elfogadása: E-mail; szerepek/hatókör; küldés; kézbesítés; lejárat; újraküldés; visszavonás; elfogadás | members.invite vagy system.users.manage; elfogadás: címzett | [meghivok](../../frontend/src/support/articles/meghivok.json) | `frontend/src/AccessWorkspace.tsx`; `backend/app/invitations.py` | [meghivo-urlap](../../frontend/public/help/images/meghivo-urlap.png) | dokumentált; emberi ellenőrzésre vár |
| Munkatársak és hozzáférések / Cégek és webáruházak: Cég; szülő cég/webshop; szervezeti nyilvántartás; selected/all erőforrásmód | companies.read/manage; webshops.read/manage | [cegek-webaruhazak](../../frontend/src/support/articles/cegek-webaruhazak.json) | `frontend/src/AccessWorkspace.tsx`; `backend/app/access_api.py` | [cegek-webaruhazak](../../frontend/public/help/images/cegek-webaruhazak.png) | dokumentált; emberi ellenőrzésre vár |
| Rendszerbeállítások / Általános: Megjelenített név; rendszernév; nyelv; időzóna; környezetjelző; mentés | system.settings.read/manage | [beallitasok-altalanos](../../frontend/src/support/articles/beallitasok-altalanos.json) | `frontend/src/SystemSettings.tsx`; `backend/app/settings_api.py` | [beallitas-altalanos](../../frontend/public/help/images/beallitas-altalanos.png) | dokumentált; emberi ellenőrzésre vár |
| Rendszerbeállítások / SMTP / Levelezés: Host; port; TLS; felhasználó; titok megtartása; feladó; tesztkapcsolat/tesztlevél | system.settings.read/manage | [beallitasok-smtp](../../frontend/src/support/articles/beallitasok-smtp.json) | `frontend/src/SystemSettings.tsx`; `backend/app/system_config.py` | [beallitas-smtp](../../frontend/public/help/images/beallitas-smtp.png) | dokumentált; emberi ellenőrzésre vár |
| Rendszerbeállítások / Hitelesítés és bejelentkezés; Kétfaktoros hitelesítés; Biztonsági szabályok: Módok; OIDC; regisztráció; kötelező MFA; passkey faktor; munkamenet/jelszó/meghívó korlátok | olvasás: system.settings.read; írás: system.settings.manage + superadmin | [beallitasok-hitelesites](../../frontend/src/support/articles/beallitasok-hitelesites.json) | `frontend/src/SystemSettings.tsx`; `backend/app/settings_api.py` | [beallitas-auth](../../frontend/public/help/images/beallitas-auth.png); [beallitas-mfa](../../frontend/public/help/images/beallitas-mfa.png); [beallitas-biztonsag](../../frontend/public/help/images/beallitas-biztonsag.png) | dokumentált; emberi ellenőrzésre vár |
| Napló / Audit: Időpont; végrehajtó; cél; technikai esemény és részletek; lapozás | ügyfél: audit.read; rendszer: system.audit.read | [muveleti-naplo](../../frontend/src/support/articles/muveleti-naplo.json) | `frontend/src/main.tsx`; `backend/app/api.py` | [audit](../../frontend/public/help/images/audit.png) | dokumentált; emberi ellenőrzésre vár |
| Támogatás / Segédlet: Keresés; témakör; URL; vissza; kapcsolódó cikk; képnagyítás; Swagger külön | minden bejelentkezett felhasználó, üzleti jogosultság nélkül is | [segedlet-hasznalata](../../frontend/src/support/articles/segedlet-hasznalata.json) | `frontend/src/support/HelpPage.tsx`; — helyi statikus tartalom | [manual-asztali](../../frontend/public/help/images/manual-asztali.png); [manual-mobil](../../frontend/public/help/images/manual-mobil.png) | dokumentált; emberi ellenőrzésre vár |
| Minden képernyő / Hibajelzés: 401/403/404/409/422/429/503; megőrzött részmunka; biztonságos hibajelentés | műveletfüggő | [gyakori-hibak](../../frontend/src/support/articles/gyakori-hibak.json) | `frontend/src/ui.tsx`; `backend/app/api.py` | [tomeges-olvasasi-jog](../../frontend/public/help/images/tomeges-olvasasi-jog.png); [revizio-utkozes](../../frontend/public/help/images/revizio-utkozes.png) | dokumentált; emberi ellenőrzésre vár |
| #41 Import UX-javítás: Tartós futástörténet-törlés; kompakt történet; awaiting_approval megszakítás | nem elérhető a vizsgált alapverzióban | [import-elozmenyek-hibak](../../frontend/src/support/articles/import-elozmenyek-hibak.json) | `frontend/src/ImportWorkspace.tsx`; — | nem elérhető működés | nem elérhető ebben az alapverzióban |
| #42 Import előnézet-javítás: 5/10/25/50 soros kompakt forráselőnézet; pénzügyi és GTIN szélhelyzetek | nem elérhető a vizsgált alapverzióban | [csv-xlsx-feltoltes](../../frontend/src/support/articles/csv-xlsx-feltoltes.json) | `frontend/src/ImportWorkspace.tsx`; — | nem elérhető működés | nem elérhető ebben az alapverzióban |
| UNAS fájlgenerálás: Exportfájl előállítás/letöltés; nem elérhető | nem elérhető a vizsgált alapverzióban | [exportprofilok](../../frontend/src/support/articles/exportprofilok.json) | `frontend/src/ImportWorkspace.tsx`; — | nem elérhető működés | nem elérhető ebben az alapverzióban |
| AI-kutatás/kredit/fizetés: Jóváhagyás nem indít AI-kutatást; nincs kész kutatómotor | nem elérhető a vizsgált alapverzióban | [elokeszitesi-jovahagyas](../../frontend/src/support/articles/elokeszitesi-jovahagyas.json) | `frontend/src/parameters/LiveBulkPreparation.tsx`; — | nem elérhető működés | nem elérhető ebben az alapverzióban |

## Cikkjegyzék

- [Bejelentkezés és munkaterület kiválasztása](../../frontend/src/support/articles/belepes-munkaterulet.json) — `#/segedlet/belepes-munkaterulet`
- [Áttekintés és ügyfelek kezelése](../../frontend/src/support/articles/attekintes-ugyfelek.json) — `#/segedlet/attekintes-ugyfelek`
- [Saját fiók, jelszó és munkamenetek](../../frontend/src/support/articles/sajat-fiok-biztonsag.json) — `#/segedlet/sajat-fiok-biztonsag`
- [TOTP, helyreállítási kódok és elveszett eszköz](../../frontend/src/support/articles/totp-helyreallitas.json) — `#/segedlet/totp-helyreallitas`
- [Passkey, Google és e-mailes regisztráció](../../frontend/src/support/articles/passkey-google-regisztracio.json) — `#/segedlet/passkey-google-regisztracio`
- [Beszállító létrehozása](../../frontend/src/support/articles/beszallito-letrehozasa.json) — `#/segedlet/beszallito-letrehozasa`
- [CSV/XLSX feltöltése](../../frontend/src/support/articles/csv-xlsx-feltoltes.json) — `#/segedlet/csv-xlsx-feltoltes`
- [Oszlopok megfeleltetése](../../frontend/src/support/articles/oszlopok-megfeleltetese.json) — `#/segedlet/oszlopok-megfeleltetese`
- [Import ellenőrzése és jóváhagyása](../../frontend/src/support/articles/import-jovahagyasa.json) — `#/segedlet/import-jovahagyasa`
- [Összekapcsolási kulcsok, feedek és pénzügyi adatok](../../frontend/src/support/articles/import-kulcsok-penzugy.json) — `#/segedlet/import-kulcsok-penzugy`
- [Importelőzmények, megállítás és hibás sorok](../../frontend/src/support/articles/import-elozmenyek-hibak.json) — `#/segedlet/import-elozmenyek-hibak`
- [Termékek kategorizálása](../../frontend/src/support/articles/termekek-kategorizalasa.json) — `#/segedlet/termekek-kategorizalasa`
- [Saját kategóriatérkép és örökítés](../../frontend/src/support/articles/kategoriameterkep.json) — `#/segedlet/kategoriameterkep`
- [A közös magyar kategóriafa és forrásai](../../frontend/src/support/articles/kozos-kategoriafa.json) — `#/segedlet/kozos-kategoriafa`
- [eMAG-paraméterek és donorprofilok](../../frontend/src/support/articles/emag-donorprofilok.json) — `#/segedlet/emag-donorprofilok`
- [Automatikus besorolás és a 98%-os küszöb](../../frontend/src/support/articles/besorolasi-kuszob.json) — `#/segedlet/besorolasi-kuszob`
- [Paraméterkereső és megengedett értékek](../../frontend/src/support/articles/parameterkereses.json) — `#/segedlet/parameterkereses`
- [Paraméterállapotok, nyers adat és normalizálás](../../frontend/src/support/articles/parameterallapotok.json) — `#/segedlet/parameterallapotok`
- [Paraméterek kézi javítása és zárolása](../../frontend/src/support/articles/kezi-parameterek.json) — `#/segedlet/kezi-parameterek`
- [Ügyfél- és globális aliasszabályok](../../frontend/src/support/articles/aliasok.json) — `#/segedlet/aliasok`
- [Paraméterhelyek háttérfutása és hibakezelése](../../frontend/src/support/articles/parameter-hatterfutas.json) — `#/segedlet/parameter-hatterfutas`
- [Oldalkijelölés és teljes szűrt termékkör](../../frontend/src/support/articles/tomeges-kijeloles.json) — `#/segedlet/tomeges-kijeloles`
- [Tömeges feldolgozás és előkészítési jóváhagyás](../../frontend/src/support/articles/tomeges-jovahagyas.json) — `#/segedlet/tomeges-jovahagyas`
- [Előkészítési ellenőrzés és jóváhagyások](../../frontend/src/support/articles/elokeszitesi-jovahagyas.json) — `#/segedlet/elokeszitesi-jovahagyas`
- [Exportprofilok beállítása](../../frontend/src/support/articles/exportprofilok.json) — `#/segedlet/exportprofilok`
- [Felhasználók és jogosultságok](../../frontend/src/support/articles/jogosultsagok.json) — `#/segedlet/jogosultsagok`
- [Rendszerfelhasználók és ügyféltagságok](../../frontend/src/support/articles/felhasznalok-tagsagok.json) — `#/segedlet/felhasznalok-tagsagok`
- [Szerepkörök és jogosultsági katalógus](../../frontend/src/support/articles/szerepkorok.json) — `#/segedlet/szerepkorok`
- [Meghívás, kézbesítés és elfogadás](../../frontend/src/support/articles/meghivok.json) — `#/segedlet/meghivok`
- [Cégek, webáruházak és erőforráshatókör](../../frontend/src/support/articles/cegek-webaruhazak.json) — `#/segedlet/cegek-webaruhazak`
- [Általános rendszerbeállítások](../../frontend/src/support/articles/beallitasok-altalanos.json) — `#/segedlet/beallitasok-altalanos`
- [SMTP, tesztkapcsolat és tesztlevél](../../frontend/src/support/articles/beallitasok-smtp.json) — `#/segedlet/beallitasok-smtp`
- [Központi hitelesítési, MFA- és biztonsági szabályok](../../frontend/src/support/articles/beallitasok-hitelesites.json) — `#/segedlet/beallitasok-hitelesites`
- [Napló és auditbejegyzések olvasása](../../frontend/src/support/articles/muveleti-naplo.json) — `#/segedlet/muveleti-naplo`
- [Keresés és navigáció a segédletben](../../frontend/src/support/articles/segedlet-hasznalata.json) — `#/segedlet/segedlet-hasznalata`
- [Gyakori kérdések és hibák](../../frontend/src/support/articles/gyakori-hibak.json) — `#/segedlet/gyakori-hibak`

## Képjegyzék és korlátok

A képek natív DOM-/oldalkivágások, utólagos képtartalom-szerkesztés nélkül. Az új kivágások legfeljebb 1400 px magasak; a hosszú űrlapokat részletként feliratozzuk. A képek nagyíthatók. Csak a `manual-mobil` 390 px-es nézet; a többi 1440 px-es asztali nézetben készült. A korábbi 9 képet nem importáltuk újra.

Nincs felvétel TOTP-QR-ről, titokról, helyreállítási kódról, meghívó/approval tokenről, jelszóról vagy valódi ügyféladatról. A külső Google- és natív passkey-ablak nincs kitalált képpel helyettesítve. Valós szolgáltatói kézbesítés, Google OIDC és eszközön végzett passkey-regisztráció emberi/környezeti ellenőrzésre vár. A képek nem bizonyítanak telepítést vagy valós katalógusrekordszámot.

- [admin-helyreallitas.png](../../frontend/public/help/images/admin-helyreallitas.png)
- [aliasok.png](../../frontend/public/help/images/aliasok.png)
- [attekintes.png](../../frontend/public/help/images/attekintes.png)
- [audit.png](../../frontend/public/help/images/audit.png)
- [beallitas-altalanos.png](../../frontend/public/help/images/beallitas-altalanos.png)
- [beallitas-auth.png](../../frontend/public/help/images/beallitas-auth.png)
- [beallitas-biztonsag.png](../../frontend/public/help/images/beallitas-biztonsag.png)
- [beallitas-kuszob.png](../../frontend/public/help/images/beallitas-kuszob.png)
- [beallitas-mfa.png](../../frontend/public/help/images/beallitas-mfa.png)
- [beallitas-smtp.png](../../frontend/public/help/images/beallitas-smtp.png)
- [beszallito.png](../../frontend/public/help/images/beszallito.png)
- [cegek-webaruhazak.png](../../frontend/public/help/images/cegek-webaruhazak.png)
- [elokeszitesi-ellenorzes.png](../../frontend/public/help/images/elokeszitesi-ellenorzes.png)
- [elokeszitesi-jovahagyas.png](../../frontend/public/help/images/elokeszitesi-jovahagyas.png)
- [elokeszitesi-megerosites.png](../../frontend/public/help/images/elokeszitesi-megerosites.png)
- [exportprofil.png](../../frontend/public/help/images/exportprofil.png)
- [fajlbeallitasok.png](../../frontend/public/help/images/fajlbeallitasok.png)
- [feltoltes.png](../../frontend/public/help/images/feltoltes.png)
- [google-allapot.png](../../frontend/public/help/images/google-allapot.png)
- [hianyzo-parameterek.png](../../frontend/public/help/images/hianyzo-parameterek.png)
- [import-jovahagyas.png](../../frontend/public/help/images/import-jovahagyas.png)
- [jelszocsere.png](../../frontend/public/help/images/jelszocsere.png)
- [jogkatalogus.png](../../frontend/public/help/images/jogkatalogus.png)
- [kategoria-parameterek.png](../../frontend/public/help/images/kategoria-parameterek.png)
- [kategoriameterkep.png](../../frontend/public/help/images/kategoriameterkep.png)
- [kategorizalas.png](../../frontend/public/help/images/kategorizalas.png)
- [kezi-parameter.png](../../frontend/public/help/images/kezi-parameter.png)
- [kozos-kategoriafa.png](../../frontend/public/help/images/kozos-kategoriafa.png)
- [manual-asztali.png](../../frontend/public/help/images/manual-asztali.png)
- [manual-mobil.png](../../frontend/public/help/images/manual-mobil.png)
- [megengedett-ertekek.png](../../frontend/public/help/images/megengedett-ertekek.png)
- [meghivo-urlap.png](../../frontend/public/help/images/meghivo-urlap.png)
- [munkamenetek.png](../../frontend/public/help/images/munkamenetek.png)
- [munkatarsak.png](../../frontend/public/help/images/munkatarsak.png)
- [munkaterulet.png](../../frontend/public/help/images/munkaterulet.png)
- [oszlopok.png](../../frontend/public/help/images/oszlopok.png)
- [parameter-futas.png](../../frontend/public/help/images/parameter-futas.png)
- [parameterallapotok.png](../../frontend/public/help/images/parameterallapotok.png)
- [parameterkereso.png](../../frontend/public/help/images/parameterkereso.png)
- [passkey-allapot.png](../../frontend/public/help/images/passkey-allapot.png)
- [rendszerfelhasznalok.png](../../frontend/public/help/images/rendszerfelhasznalok.png)
- [revizio-utkozes.png](../../frontend/public/help/images/revizio-utkozes.png)
- [sajat-fiok.png](../../frontend/public/help/images/sajat-fiok.png)
- [szerepkor-szerkeszto.png](../../frontend/public/help/images/szerepkor-szerkeszto.png)
- [szerepkorok.png](../../frontend/public/help/images/szerepkorok.png)
- [termeklista.png](../../frontend/public/help/images/termeklista.png)
- [tomeges-kijeloles.png](../../frontend/public/help/images/tomeges-kijeloles.png)
- [tomeges-olvasasi-jog.png](../../frontend/public/help/images/tomeges-olvasasi-jog.png)
- [tomeges.png](../../frontend/public/help/images/tomeges.png)
- [totp-allapot.png](../../frontend/public/help/images/totp-allapot.png)
- [ugyfel-letrehozas.png](../../frontend/public/help/images/ugyfel-letrehozas.png)
- [ugyfelek.png](../../frontend/public/help/images/ugyfelek.png)

## Kifejezetten nem elérhető / külön fejlesztés

- #41: kompakt importtörténet, tartós előzménytörlés és a Jóváhagyásra vár állapot megszakító gombja. A meglévő retenciós forrásfájltörlés nem futástörlés.
- #42: új kompakt 5/10/25/50 soros előnézet és a külön importadat-szélhelyzet-javítások. A vizsgált verzió 25-ös lapozást és JSON-t is megjelenít.
- UNAS-termékfájl előállítása és kiküldése: nincs kész. Csak mező-/profil-előkészítés szerepel a kézikönyvben.
- AI-kutatás, kredit és fizetés: nem indul az előkészítési jóváhagyással.
- Univerzális kötöttérték-listaszerkesztő: nincs bekötve a termék kézi szerkesztőjébe. A referenciaértékek olvashatók; ismert forrásjelölt elfogadható.

## Szintetikus demó végigjárása

A `test_follow_written_demo_supplier_import_classification_missing_and_grants` a leírt útvonalat valós UI-írásokkal járja be: beszállító létrehozása → UTF-8/pontosvesszős demó feltöltése → oszlopok és kulcs/feed ellenőrzése → import jóváhagyása → worker tényleges feldolgozása → DEMO-001 kézi besorolása Elöltöltős mosógépek kategóriába → paraméter-előnézet/alkalmazás → kötelező hiány igazolása → olvasó felhasználó tömeges jogosultságainak ellenőrzése. A nyers saját kategória és kézi besorolási védelem megőrzését külön ellenőrzi. A háttérmotor az eldobható SQLite-fixture-ön fut, nem VPS-en.

## Változtatási határ

Nincs backend-, importmotor-, schema-, migráció-, ügyféladat-, pinfo_db-, .env- vagy Compose-változás. Nincs #41/#42 integráció, main merge vagy VPS-telepítés. A CI-ben a HELP-02 ág push-triggerét adtuk hozzá, és csak ennek az ágnak az elavult push-futásait szakítja meg az új push. A main soros ellenőrzése, a jobok és telepítési lépések változatlanok.

## Helyi ellenőrzési jegyzőkönyv

| Parancs / ellenőrzés | Eredmény |
|---|---|
| `PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py` | 437 sikeres; szintetikus adatbázisok |
| `npm --prefix frontend run lint` | sikeres, 0 figyelmeztetés |
| `npm --prefix frontend test` | 13 sikeres; tartalom, linkek, képek, táblázatok, XSS, valódi menüleltár, lintkonfiguráció |
| `npm --prefix frontend run build` | sikeres; TypeScript és Vite |
| `PYTHONPATH=backend .venv/bin/pytest -q scripts/tests/test_help_browser.py scripts/tests/test_help_manual_browser.py` | 12 sikeres; Chromium, 390/1440 px; 134,14 s |
| `npm --prefix frontend audit --audit-level=high` | 0 sérülékenység |
| Teljes böngészős CI-csomag gyűjtése | 163 teszteset; a teljes futtatást a GitHub Actions végzi |

A felhőben Chromium 156, a CI Playwright 1.56 csomagjában Chromium 141 fut.
A helyi eredmény nem helyettesíti a hosted CI-t. A végső futás eredményét a PR
ellenőrzéseinél és az átadási üzenetben kell ellenőrizni. A Docker- és MySQL-
migrációs ellenőrzések is a változatlan teljes CI részei.
