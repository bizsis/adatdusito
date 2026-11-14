# CODEX 09 – Egységes felület, rendszerbeállítások és hitelesítés

## Kiindulási állapot és megőrzött funkciók

Kiindulás: CODEX 08, `0007`, FastAPI + React/TypeScript + MySQL. A felmérés kiterjedt a teljes frontendstruktúrára, CSS-re, függőségekre, valamennyi migrációra, a `system_settings` táblára, a cookie/CSRF/scrypt/Redis folyamatra, meghívásra/SMTP-re, CODEX 08 RBAC-ra és a korábbi tesztekre.

A fejlesztés nem változtatja meg a közös kategóriafát, a `pinfo_db` adatbázist, a CODEX 07 feldolgozási logikát, a meglévő ügyféladatokat vagy a CODEX 08 engedélyszámítás alapelveit. Nincs katalógusimport vagy aktiválás, számlázás, AI-kredit vagy automatikus VPS-telepítés. A fő `compose.yaml` és a `.env` változatlan.

## Cloud & Teal designrendszer

Központi színek: `frontend/src/tokens.css`.

| Token | Szín |
| --- | --- |
| Háttér / felület / határoló | `#F7F9FC` / `#FFFFFF` / `#E7EDF4` |
| Elsődleges / információ | `#0D9488` / `#3B82F6` |
| Szöveg / másodlagos szöveg | `#172B4D` / `#64748B` |
| Siker / figyelmeztetés / veszély | `#16A34A` / `#F59E0B` / `#DC2626` |

A normál méretű fehér gombfeliratokhoz az elsődleges teal sötétebb, kontrasztos `#0F766E` változatát használjuk; az alap akcentus `#0D9488`.

Inter, helyben kiszolgált latin és latin-ext fontfájlokkal, rendszerfont-helyettesítéssel. Egységes 10 px lekerekítés, térközök, fókuszállapot és táblázat/űrlap/gomb stílusok. Világos oldalsáv, fehér panelek, halvány aktív állapotok. Lucide React ikonok a főfunkcióknál és műveleteknél; az ikongombok akadálymentes nevet és kattintható felületet kapnak.

Közös komponensek: `ui.tsx` (`Panel`, `Help`, `FieldTitle`, `IconButton`, `PermissionGrid`, `PermissionMatrix`), `permissions.tsx` (`PermissionOverrides`). A rendszer- és ügyfélszerepkörök és az egyedi kivételek ugyanazt a táblázati alapot használják. Szerepkörszerkesztésnél az oszlopsorrend: név → engedélyező checkbox → pontos magyar leírás. A technikai kód részletekbe csukható. A szerepkörlista táblázatban mutatja a típust, kiosztások számát és védett állapotot; szerkesztés és törlés ikongombbal történik. Az ügyféloldali kiosztásszám kizárólag az adott ügyfélre vonatkozik.

A súgók és permissionmagyarázatok központi helye: `help.ts`. A natív részletező súgó egérrel/érintéssel, Enterrel/Space-szel megnyitható, Escape-pel bezárható. Az import, export, kategóriakezelés, szerepkörök, erőforráskörök, SMTP, titkok, bejelentkezési módok és 2FA tényleges hatását magyarázza.

A dátumok megjelenítését közös `dateTime()` segéd és a beállított időzóna vezérli; a tárolás továbbra is UTC. A jelenlegi alkalmazásnyelv magyar. A környezetcímke csak megjelenítés, nem állít át szervert vagy adatbázist.

## Navigáció és adminisztráció

Főfunkciók a meglévő engedélyek szerint: Áttekintés → Ügyfelek → Termékadatok → Beszállítói import → Export → Rendszerhozzáférések → Rendszerbeállítások → Napló / Audit. A kategóriák és paraméterkeresés a termékadatok alá rendezett, működő navigációs elemek. Az ügyfélmunkatársak kezelése csak ügyfélkontextusban látható. Az Audit önálló főmenüpont.

A Termékadatok ügyfélmunkaterületen olvasási, kurzorral lapozott listát ad a már feldolgozott beszállítói termékekről. A meglévő importadatokat nem írja át. Rendszerkontextusban a közös referenciaböngésző érhető el. A részleges erőforráskörrel hozzáférhetetlen régi importadatok továbbra sem válnak láthatóvá.

A Rendszerbeállítások öt füle: Általános; SMTP / Levelezés; Hitelesítés és bejelentkezés; Kétfaktoros hitelesítés; Biztonsági szabályok. A felső felhasználói menü Biztonság gombja a saját felhasználónév, újraazonosítás, TOTP, recovery kódok, passkeyk, Google-kapcsolat és munkamenetek kezelésére vezet.

A régi `display_name` és `admin_notice` megmarad. A `display_name` a strukturált beállítás és a régi kompatibilitási API közös értéke; az alkalmazás tényleges megjelenését módosítja. A belső `admin_notice` nem kap hangsúlyos új mezőt. Nincsenek üres előfizetési, fizetési vagy AI-menüpontok.

## Adatbázis: `0008_settings_auth`

A `0007` után fut. Kizárólag az alkalmazás-adatbázist érinti.

| Új tábla | Rendeltetés |
| --- | --- |
| `system_configuration` | Validált, kategorizált, nem titkos JSON-beállítások. |
| `system_secret_settings` | SMTP- és OIDC-titkok titkosított értékei. |
| `auth_challenges` | Rövid életű, egyszer használható, hash alapján keresett kihívások. |
| `external_identities` | Kifejezetten összekapcsolt szolgáltató + subject → globális felhasználó. |
| `user_passkeys` | RP, hitelesítőazonosító/hash, nyilvános kulcs, számláló és eszköznév. Privát kulcs nincs. |
| `user_totp_devices` | Titkosított TOTP-kulcs, aktiválás és utolsó elfogadott számláló. |
| `user_recovery_codes` | Egyszer használható kódok egyirányú hash-e és felhasználási ideje. |

Módosított táblák:

- `users`: egyedi `username`, opcionális `email`, `email_verified`, `must_change_password`, `mfa_reset_required`.
- `login_sessions`: hitelesítési mód, ellenőrzött MFA jelző és újraazonosítás ideje.
- `tenants`: `onboarding_state`; a meglévő ügyfeleknél `existing`.

A régi fiókok determinisztikus `user-<id>` felhasználónevet kapnak; a saját Biztonság oldalon megváltoztatható. A felhasználónév ASCII kisbetű, szám, pont, kötőjel és aláhúzás lehet (3–80 karakter), `@` nem lehet benne. Így a felhasználónév és e-mail bejelentkezési névtere nem keveredik. A meglévő e-mailek és jelszóhash-ek változatlanok; történeti e-mail-ellenőrzést nem találunk ki.

A CODEX 08 táblái és kiosztásai megmaradnak. Egy kötelező MFA-ra állított ügyfélszerepkör-sablon helyi másolata automatikusan megőrzi a szabályt; ennek külön auditeseménye van. MFA-szabályban szereplő szerepkör törlése a szabály előzetes rendezéséig tiltott.

## Titokkezelés

Fernet hitelesített titkosítás, a már használt `cryptography` könyvtárral. A kulcs egy üzemeltető által kezelt, alkalmazáskönyvtáron és adatbázison kívüli fájl. Alapértelmezett konténerútvonal: `/run/secrets/adatdusito_key`. Az opcionális `APP_ENCRYPTION_KEY_FILE` csak üzemeltetői környezeti beállítás; a weben nem állítható.

Hiányzó vagy nem illeszkedő kulcsnál nincs plaintext fallback, automatikus új kulcs vagy titoktörlés: 503 válasz érkezik. A beállítási felület a titok létezését kulcs nélkül is jelezheti, az értékét nem. A webes GET és az audit soha nem tartalmaz SMTP-jelszót, Google kliens titkát, TOTP-kulcsot vagy recovery kódot. A kulcsról a titkosított adatbázismentéssel összeillő, külön védett mentést kell tartani. Kulcscseréhez ellenőrzött offline újratitkosítás szükséges; a kulcsfájl egyszerű lecserélése nem rotáció.

A nyers TOTP-kulcs csak az aktiválásnál, a recovery kódok csak létrehozáskor/újrageneráláskor láthatók. Titkosítás nélkül tárolt személyes adat továbbra is az alkalmazás adatmodelljének része; az adatbázis nem teljes egészében titkosított.

## SMTP – webes konfiguráció és prioritás

1. Ha van mentett `smtp` konfiguráció, az teljes egészében elsőbbséget élvez.
2. Ellenkező esetben a meglévő `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, opcionális `SMTP_FROM_NAME` értékek érvényesek.
3. A meghívó lejárata a strukturált biztonsági beállításból származik; ennek hiányában az `INVITE_TTL_HOURS` (alap 48, 1–168 óra) kompatibilitási értéke használatos.

Nincs csendes visszaesés egy hibás mentett konfigurációról a környezetire. A webes módosítás újraindítás nélkül érvényes. Üres jelszómező azonos kiszolgálónál/portnál/titkosításnál/felhasználónál megőrzi a korábbi titkot. Másik célhoz az új jelszót is meg kell adni: a webes admin nem irányíthatja át a vissza nem olvasható régi jelszót egy másik SMTP-kiszolgálóra.

Mentés előtt TLS/STARTTLS kapcsolat és a beállított hitelesítés ellenőrzése történik. Hibánál a korábbi konfiguráció változatlan. Külön kapcsolatpróba és tesztlevél kérhető. A válasz jelzi a titkosított kapcsolatot, a hitelesítés eredményét/hiányát és az SMTP általi elfogadást. Nem állít postaládába érkezést.

A webes célcímeknél minden DNS-választ ellenőrzünk; privát, loopback és tiltott címek alapból kizártak. IPv4-mapped IPv6 és címfordító átjárók sem kerülhetik meg a szabályt. A TCP-kapcsolat már ellenőrzött IP-re épül, a TLS az eredeti szervernevet ellenőrzi; a próbálkozások száma és ideje korlátozott. A DNS nem cserélhető ki a címellenőrzés és kapcsolódás között.

Belső levelezőhöz az üzemeltető előre rögzíthet pontos gépnév-engedélyt az `SMTP_ALLOWED_HOSTS` környezeti listában; ezt a webes admin nem módosíthatja. Link-local/metadata és fordító címek így sem engedélyezhetők. A régi környezeti SMTP-konfiguráció üzemeltető által megbízhatónak megadott címét megőrizzük; a webes tesztekre a szigorú célcím-ellenőrzés vonatkozik. `none` titkosítás weben nem menthető; a régi helyi SMTP-tesztek kompatibilitása megmarad.

## Jelszó, felhasználónév és munkamenet

A `/auth/login` továbbra is elfogadja a régi `email` mezőt; az új `identifier` mező felhasználónév vagy e-mail lehet. A scrypt, HttpOnly/Secure/SameSite=Strict cookie, CSRF és Redis-alapú korlát megmarad. Aktív állapot és CODEX 08 jogosultság minden kérésnél újra ellenőrzött.

Rendszeradmin névvel, egyedi felhasználónévvel, opcionális e-maillel, szerepkörökkel és aktív állapottal hozhat létre rendszerfiókot. Az adminisztrátor által adott ideiglenes jelszó első belépéskor kötelezően cserélendő. Addig nincs üzleti jogosultság. E-mail nélküli fiók helyreállításához superadmin friss újraazonosítással, dokumentált indokkal adhat új ideiglenes jelszót; a többi munkamenet megszűnik, a TOTP-védelem ettől nem kapcsol ki.

Kritikus hitelesítési és titokkezelési műveletekhez öt percen belüli újraazonosítás szükséges: jelszó és beállított második faktor, vagy megfelelően ellenőrzött passkey. Friss, sikeres belépés is ilyen bizonyíték. Jelszavas mód tiltásakor Google-fiókkal új belépés vagy engedélyezett passkey-újraazonosítás használható.

A munkamenetek listája nem ad vissza tokenhash-t vagy nyers tokent; külön, nem hitelesítésre használható azonosító alapján vonhatók vissza. A rövidebb központi élettartam a meglévő munkamenetekre is vonatkozik. A jelszóminimumnak visszafelé nincs hash-átíró hatása; új jelszónál érvényesül. Az elsődleges és második faktor próbái a közös Redis-védelemhez kapcsolódnak; Redis-hibánál a belépés zárt módon hibázik.

## Google OIDC

Google Cloudban webes OAuth/OIDC kliens szükséges, pontos visszahívással:

```text
https://dev.pinfo.hu/api/v1/auth/google/callback
```

A kliensazonosító és titok a webes Hitelesítés oldalon adható meg. Az engedélyezés önmagában nem kapcsol Google-fiókot meglévő fiókhoz. A felhasználó először meglévő módon bejelentkezik, frissen újraazonosít, majd a saját Biztonság oldalán összekapcsolja a Google-fiókot. Azonos e-mail nem elegendő, automatikus fiókegyesítés és automatikus Google-regisztráció nincs.

Authorization Code + S256 PKCE (titkosítva tárolt verifierrel), véletlen state és nonce, rövid életű szerveroldali kihívás, böngészőhöz kötött HttpOnly/Secure/SameSite=Lax átmeneti cookie. A teljes alkalmazáscookie továbbra is Strict. A tokenváltás kizárólag a rögzített Google HTTPS-végponton történik. JWKS-alapú RS256 aláírás, issuer, audience/authorized party, lejárat, kiállítási idő és nonce ellenőrzése kötelező. Az egyszer felhasznált callback nem ismételhető. A subject egyedi, más felhasználó kapcsolatát nem veheti át.

A jelszó letiltása előtt minden aktív superadminnak maradnia kell használható, engedélyezett módszernek. Google-tartalék csak ténylegesen sikeres OIDC-tokenváltással ellenőrzött aktuális klienssel számít. Klienscsere nem zárhat ki Google-only admint. Leválasztás és passkey-törlés ugyanezt a kizárásvédelmet tiszteletben tartja.

Uvicorn és a frontend-konténer Nginx hozzáférési naplója nem naplózza az OIDC callback query paramétereit. **A külső VPS Nginx/proxy naplóformátumát az üzemeltetőnek is ellenőriznie kell a Google éles engedélyezése előtt**: a callbacknél ne szerepeljen `$request` vagy `$request_uri` paraméterekkel; a metódus + `$uri` + protokoll elegendő. A fejlesztés nem módosítja a VPS Nginxét. A sikeres tokenváltás SMTP-től független; a Google szolgáltatói konfigurációt és tényleges külső bejelentkezést az üzemeltetőnek kell kipróbálnia.

## Passkey / WebAuthn

HTTPS, stabil `APP_ORIGIN` és modern böngésző/eszköz szükséges. Az RP a konfigurált alkalmazás hostname-ja. Regisztrációhoz aktív, frissen újraazonosított fiók kell; az eszköznév látható a saját listában. A privát kulcs az eszközön/hitelesítőben marad.

A szerver a `webauthn` könyvtárral ellenőrzi a véletlen, egyszer használható kihívást, origin-t, RP-hash-t, aláírást, jelenlétet, kötelező user verificationt, user handle-t és a rendelkezésre álló számlálót. A cross-origin szertartás tiltott. A regisztrált RP külön tárolódik. A szinkronizált, nulla számlálós hitelesítők könyvtár által szabványosan támogatottak. Az eszközök hozzáadhatók, listázhatók és friss újraazonosítással törölhetők; az utolsó használható adminmód nem törölhető.

A passkey csak a központi szabály engedélyével és igazolt UV mellett teljesíti a többfaktoros követelményt. Kikapcsolt elfogadásnál kötelező MFA esetén TOTP/recovery lépés is kell. Domainváltoztatás előtt gondoskodj másik használható módról és új RP alatti eszközregisztrációról; az origin nem webes beállítás.

## TOTP és helyreállítás

Szabványos, 30 másodperces TOTP, Google/Microsoft Authenticatorral és más kompatibilis alkalmazásokkal. QR + manuális kulcs, ellenőrzőkódos aktiválás, titkosított titok. Az aktiválás is elfogyasztja az elfogadott időlépést; ugyanaz a kód újra nem használható. A következő kódot kell megvárni, vagy egyszer használható recovery kódot használni.

Tíz véletlen, nagy entrópiájú recovery kód készül, csak hash kerül az adatbázisba. Újragenerálás érvényteleníti a régi készletet. TOTP-aktiválás a többi munkamenetet visszavonja. Saját visszavonás friss újraazonosítással lehetséges, kötelező szerepköri szabály mellett nem. Saját TOTP-eszköz azonban ilyenkor is biztonságosan cserélhető: friss régi faktoros vagy recovery kódos újraazonosítás után új QR készül, a régi kulcs az új kód megerősítéséig aktív marad. A csere atomikus, új recovery készletet ad és a többi munkamenetet visszavonja; a kötelező védelmet nem kapcsolja ki. Egy fióknál egy TOTP-profil és több passkey tartható nyilván.

Rendszerfióknál a saját rendszerszerepkör MFA-szabálya érvényesül; régi, kézi ügyféltagság nem változtatja meg ezt. Alapból egyik szerepkörnél sem kötelező a 2FA. Rendszer- és ügyfélszerepkörönként beállítható. Jelszó/Google/passkey első faktor után szükség esetén csak rövid életű MFA-kihívás készül, **teljes munkamenet csak a második faktor teljesítése után**. Még be nem állított kötelező TOTP a korlátozott belépési folyamatban aktiválható. Korábban létező, már nem megfelelő munkamenet csak korlátozott fiókbiztonsági hozzáférést kap; az UI új bejelentkezésre vezet. Inaktív fiók semmilyen módszerrel nem léphet be.

Más felhasználó TOTP-jének helyreállítása nem általános egykattintásos adminletiltás. Dokumentált személyazonosság-ellenőrzés, friss többfaktoros superadmin-kérés és **másik**, szintén frissen több faktorral azonosított superadmin jóváhagyása kell. Az érintett összes munkamenete megszűnik, és a következő belépésnél új TOTP-aktiválás kötelező. Saját/azonos admin nem hagyhatja jóvá a kérést. Egyetlen adminos telepítésnél a recovery kódok biztonságos megőrzése különösen fontos; elvesztett első és második faktor esetére nincs távoli, ellenőrizetlen bypass.

## Nyilvános regisztráció

Alapértelmezetten tiltott. Engedélyezéshez működő, biztonságos SMTP és titkosítási kulcs szükséges. E-mail-ellenőrzés előtt nincs fiók és munkaterület. A link egyszer használható, 60 percig él. Meglévő címre azonos általános válasz érkezik, nincs fiókfelderítés vagy más ügyfélhez automatikus hozzárendelés.

Redis-korlát: az általános próbavédelem mellett napi 100 platformszintű, és hálózati partnerenként napi 10 regisztrációs kérés. A socket peer számít, tetszőleges X-Forwarded-For nem kerül bizalmi forrásba; megosztott reverse proxy mögött a partnerkeret is megosztott. Ezt az alacsony forgalmú kezdeti, opcionális regisztrációhoz dokumentáljuk; nagyobb nyilvános forgalomhoz külön megbízható proxy- és visszaélésvédelmi üzemeltetési terv kell.

Megerősítéskor globális fiók, ügyfélmunkaterület és ügyféladmin-tagság jön létre atomikusan, `pending_subscription` állapottal. **Nem adunk kitalált korlátlan próbaverziót.** Az új munkaterület feldolgozási és felhasználóadminisztrációs jogosultságait szerveroldali kapu korlátozza az előfizetési ütemig; a közös referencia olvasható. A meglévő `existing` ügyfelekre ez nem vonatkozik. Nincs nyilvános végpont az állapot jogosulatlan átállítására.

## Új API-k

Minden útvonal `/api/v1` alatt van. A hitelesített írások meglévő CSRF-védelme változatlan. A publikus bejelentkezési/második faktor/token végpontok saját egyszeri kihívást és sebességkorlátot használnak.

| Útvonal | Funkció |
| --- | --- |
| `GET /auth/methods` | Elérhető módszerek és nyilvános arculat. |
| `GET /system/settings` | Strukturált, titokmentes konfiguráció. |
| `PUT /system/settings/{general,smtp,auth,mfa,security}` | Validált konfigurációmódosítás; auth/MFA/security csak superadminnak. |
| `POST /system/settings/smtp/test` | Kapcsolat- vagy tesztlevél-próba. |
| `GET /auth/security`, `POST /auth/reauth`, `PUT /auth/username` | Saját biztonsági állapot, újraazonosítás és felhasználónév. |
| `POST /auth/totp/{setup,confirm,disable}`, `POST /auth/recovery/rotate` | Saját TOTP és helyreállítási kódok. |
| `POST /auth/mfa/{setup,complete}` | Belépés előtti, korlátozott másodikfaktor-folyamat. |
| `POST /auth/passkeys/register/{options,verify}` | Regisztráció. |
| `POST /auth/passkeys/login/{options,verify}`, `DELETE /auth/passkeys/{id}` | Belépés/újraazonosítás és eszköztörlés. |
| `POST /auth/google/start`, `GET /auth/google/callback`, `DELETE /auth/google/link` | Google OIDC és explicit összekapcsolás. |
| `GET /auth/sessions`, `DELETE /auth/sessions/{id}` | Saját aktív munkamenetek és visszavonás. |
| `POST /auth/system-users`, `POST /auth/system-users/{id}/reset-password` | Rendszerfiók létrehozása és felügyelt ideiglenes jelszó. |
| `POST /auth/admin-recovery/{request,approve}` | Két admin által jóváhagyott TOTP-helyreállítás. |
| `POST /auth/register`, `POST /auth/register/confirm` | Opcionális, ellenőrzött e-mailes munkaterület-létrehozás. |
| `GET /workspace/products?cursor=` | Saját ügyfél feldolgozott termékeinek olvasási listája. |

Az Audit külön marad. Új `settings09.*` és `auth09.*` események rögzítik a konfigurációt titkok nélkül, eszközműveleteket, MFA-hibákat, recovery-használatot, munkamenet-visszavonást, rendszerfiók-létrehozást és összekapcsolást. A szereplő, érintett és indok szerepel, a tokenek/kódok/jelszavak nem.

## Tesztelési eljárás

```bash
cd /workspace/adatdusito
.venv/bin/pip install -r backend/requirements.lock -r scripts/browser-requirements.txt
.venv/bin/python -m playwright install --with-deps chromium
(cd frontend && npm ci && npm run build)
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests
```

A teljes regresszió tartalmazza a korábbi import-, RBAC-, kategória- és katalógusellenőrző teszteket is. A CI ugyanazt a teljes backend + scripts tesztkészletet és mindkét Docker-buildet futtatja.

Új tesztek: e-mail nélküli fiók és kötelező első jelszócsere; régi e-mailes bejelentkezés; SMTP mentés, titokmentes visszaolvasás és hibás módosítás visszautasítása; valódi helyi TLS SMTP hitelesítéssel és tesztlevéllel; DNS/SSRF-védelem; TOTP, egyszeri recovery és lejárt/inaktív belépés; szerepköri MFA és sablonmásolat; passkey/MFA-újraazonosítás megkerülésének tiltása; sessionvisszavonás; adminmódok kizárásvédelme; két adminos helyreállítás; e-mail-ellenőrzött regisztráció feldolgozási jogok kitalálása nélkül.

Az OIDC-tesztek valóban aláírt RSA ID-tokenekkel vizsgálják az issuer/audience/nonce/lejárat/signature/state/PKCE/böngészőkötés szabályait és az e-mail-alapú téves fiókegyesítés tiltását. A WebAuthn-tesztek valódi COSE nyilvános kulccsal és ECDSA aláírásokkal ellenőriznek, hibás origin/UV/számláló/handle és cross-origin kérést is elutasítanak. A böngészőtesztek Chromium virtuális platformhitelesítővel ténylegesen regisztrálnak és bejelentkeznek; külön asztali és mobil megjelenítést, súgót, jogosultsági táblát, SMTP-űrlapot és TOTP/recovery belépést is futtatnak.

Az eldobható MySQL 8 tesztben a `0007 → 0008`, ismételt `upgrade head`, használat előtti downgrade és vissza-upgrade ellenőrzött. Megmaradtak a korábbi hash-ek, két fiók, három tagság, CODEX 08 kiosztás, munkamenet, két ügyfél és CODEX 07 termékadat. A teszt nem a VPS-en futott. A helyi teljes regresszió 242 teszttel sikeres volt; a végső célzott backendfutás 83, az asztali/mobil UI-futás további 8 tesztet ellenőrzött. Az utolsó kiegészítésekkel futó teljes CI tesztszáma, commitja és hivatkozása az átadási üzenetben szerepel. Egy korábbi Starlette/AnyIO elavulási figyelmeztetés maradt, teszthiba nélkül.

## Kézi VPS-telepítés

Ezeket a parancsokat **az üzemeltető** futtatja, nem a fejlesztés. Az aktív importok befejezését előbb várd meg. A karbantartás az alkalmazás frontend/backend/worker szolgáltatásait érinti; nem telepít új MySQL-t, nem indít katalógusimportot, nem nyúl `pinfo_db`-hez, hálózathoz vagy az éles `pinfo.hu` alkalmazáshoz.

A `compose.auth-secrets.example.yaml` opcionális kiegészítés kizárólag a kulcsfájl csatolását tartalmazza. A fő Compose external hálózata és portjai változatlanok. A VPS-en a példát helyi `compose.override.yaml` fájlként telepítjük; így a későbbi szokásos `docker compose` parancsok is megtartják a kulcscsatolást. Meglévő helyi override-ot nem írunk felül: azt előbb át kell nézni és a secret-csatolással kézzel összevezetni. Az alábbi blokkokat ugyanabban a Bash shellben futtasd, vagy állítsd vissza a tényleges `auth_backup_dir`, `auth_stamp` és `auth_compose` változókat.

### 1. Állapot és előző kiadás megőrzése

```bash
cd /opt/adatdusito
set -euo pipefail
umask 077
test -z "$(git status --porcelain --untracked-files=no)"
auth_stamp=$(date -u +%Y%m%d-%H%M%S)
auth_backup_dir="/root/adatdusito-backups/codex09-$auth_stamp"
mkdir -p "$auth_backup_dir"
git rev-parse HEAD > "$auth_backup_dir/previous-commit.txt"
cp -p .env compose.yaml "$auth_backup_dir/"
if [ -f compose.override.yaml ]; then cp -p compose.override.yaml "$auth_backup_dir/"; fi
docker compose config --quiet
docker image tag adatdusito-dev-backend "adatdusito-dev-backend:before-codex09-$auth_stamp"
auth_frontend_image=$(docker compose images -q frontend | head -n 1)
test -n "$auth_frontend_image"
docker image tag "$auth_frontend_image" "adatdusito-dev-frontend:before-codex09-$auth_stamp"
```

Helyi követett módosításnál a blokk megáll: ne írj felül egyeztetés nélkül konfigurációt. A `docker compose config` teljes kimenetét ne publikáld, mert környezeti titkokat is tartalmazhat.

### 2. Külső titkosítási kulcs

A kulcsfájl nem kerül Gitbe és nem webes beállítás. Ha már létezik, a parancs megőrzi. Az alkalmazás konténer-UID-je 10001; a fájl jogosultságát ehhez állítjuk, a könyvtár root számára elérhető. A file-backed Compose secret nem minden környezetben alkalmaz UID/mode átírást, ezért a forrásfájl tényleges jogai is számítanak.

```bash
mkdir -p /opt/adatdusito-secrets
chmod 0700 /opt/adatdusito-secrets
if [ ! -f /opt/adatdusito-secrets/auth-fernet.key ]; then
  docker compose run --rm --no-deps backend python -c 'from cryptography.fernet import Fernet; import sys; sys.stdout.buffer.write(Fernet.generate_key())' > /opt/adatdusito-secrets/auth-fernet.key
fi
test -s /opt/adatdusito-secrets/auth-fernet.key
chown 10001:10001 /opt/adatdusito-secrets/auth-fernet.key
chmod 0400 /opt/adatdusito-secrets/auth-fernet.key
cp /opt/adatdusito-secrets/auth-fernet.key "$auth_backup_dir/auth-fernet.key"
chmod 0600 "$auth_backup_dir/auth-fernet.key"
```

A kulcsot külön védett mentésben is őrizd meg. Ha a `.env`-ben már van egyedi `APP_ENCRYPTION_KEY_FILE`, annak a meglévő kulcsát és csatolását kell megőrizni; ne hozz létre helyette másikat. A példablokk az alapértelmezett, korábban nem konfigurált telepítéshez készült.

### 3. Forrás és image-ek

```bash
git fetch origin main
git merge --ff-only origin/main
if [ -e compose.override.yaml ]; then
  if ! cmp -s compose.auth-secrets.example.yaml compose.override.yaml; then
    printf '%s\n' 'Eltérő helyi override: előbb kézi konfiguráció-ellenőrzés és összevezetés szükséges.' >&2
    exit 1
  fi
else
  cp compose.auth-secrets.example.yaml compose.override.yaml
  touch "$auth_backup_dir/created-auth-override"
fi
auth_compose=(-f compose.yaml -f compose.override.yaml)
docker compose "${auth_compose[@]}" config --quiet
docker compose "${auth_compose[@]}" build backend frontend
docker compose "${auth_compose[@]}" run --rm --no-deps migrate python -c 'from app.system_config import cipher; cipher(); print("Titkosítási kulcs olvasható és érvényes.")'
```

A kulcsteszt nem írja ki a kulcsot. Nem módosítjuk a `.env` fájlt, a meglévő SMTP környezeti értékek támogatottak maradnak.

### 4. Mentés, migráció, indítás

```bash
docker compose "${auth_compose[@]}" stop frontend backend worker
mysqldump -u root -p --single-transaction --no-tablespaces --routines --triggers adatdusito_dev | gzip > "$auth_backup_dir/adatdusito_dev.sql.gz"
gzip -t "$auth_backup_dir/adatdusito_dev.sql.gz"
sha256sum "$auth_backup_dir/adatdusito_dev.sql.gz" > "$auth_backup_dir/adatdusito_dev.sql.gz.sha256"
sha256sum -c "$auth_backup_dir/adatdusito_dev.sql.gz.sha256"
docker compose "${auth_compose[@]}" run --rm --no-deps migrate
docker compose "${auth_compose[@]}" up -d --no-deps backend worker frontend
docker compose "${auth_compose[@]}" exec -T backend alembic current
docker compose "${auth_compose[@]}" ps
docker compose "${auth_compose[@]}" logs --tail=80 backend worker
curl --fail --silent --show-error https://dev.pinfo.hu/api/health/live
```

Elvárt revision: `0008`. A MySQL jelszavát a `mysqldump` interaktívan kéri; ne add át parancsargumentumban. Hiba esetén a `set -euo pipefail` megállítja a további lépéseket. Meglévő ügyfélen ne futtass cloud fixture-t, új bootstrapot vagy termék/katalógusimportot.

### 5. Kézi elfogadási ellenőrzés

1. Régi e-mail+jelszó bejelentkezés, ügyfélváltás és a Molnarvegyi/Nomadsport tagság nélküli superadmin-elérés. Mobil és asztali nézet, világos oldalsáv, főmenüikonok, fókusz és súgó Enter/Escape kezelése.
2. Saját Biztonság oldalon felhasználónév és újraazonosítás. Szerepkörlistában számláló és ikongombok, szerkesztőben név → checkbox → leírás. Egyedi tiltás és másik ügyfél izolációja maradjon érvényes.
3. Általános beállítás neve és időzónája ténylegesen frissüljön. Audit maradjon külön főmenü. A régi belső megjegyzés adatbázisban megmarad.
4. SMTP webes mentés és saját címre tesztlevél. A jelszómező kiürül, a titok csak beállítottnak látszik. Hibás jelszó/host ne írja felül a működő konfigurációt. Ellenőrizd ténylegesen a postaládát; az SMTP-elfogadás önmagában nem bizonyít kézbesítést.
5. E-mail nélküli tesztrendszerfiók saját felhasználónévvel és ideiglenes jelszóval: első belépéskor jelszócsere, majd a kiosztott szerepkörök és ügyfélkör érvényesüljenek.
6. TOTP QR-aktiválás, recovery kódok biztonságos mentése, második faktoros belépés és egy kód egyszeri felhasználása. Csak ellenőrzött tesztszerepkörön próbáld ki a kötelező MFA-t; másik használható adminmód maradjon elérhető.
7. Passkey engedélyezés, saját eszköz regisztrációja és valódi eszközös bejelentkezés. A jelszót csak azután tiltsd le, hogy valamennyi aktív admin alternatívája működik.
8. Google Cloud kliens/consent/tesztfelhasználók, pontos redirect URI és külső proxy naplózása legyen rendben. Ezután saját meglévő fiók explicit összekapcsolása, kijelentkezés és Google-belépés; azonos e-mailből ne legyen automatikus kapcsolat.
9. Munkamenet visszavonás és jogosultság-visszavonás már nyitott másik böngészőben. Az Audit rögzítse az eseményeket titkok nélkül.
10. Szintetikus CSV/XLSX import a régi, teljes körű tesztügyfélnél, meglévő profil/worker/terméklista; referenciafa, paraméterek és exportmezők regressziópróbája. Regisztrációt csak tudatosan kapcsold be; a létrejövő munkaterület legyen előfizetésre váró, importjog nélkül.

## Mentésellenőrzés és visszaállítás

Az alkalmazás teljes mentését **külön, üres ellenőrző sémában** próbáld vissza a karbantartási terv részeként. Ez nem állítja át az alkalmazás adatbázis-URL-jét és nem írja felül az élő sémát. A helyes mentési útvonalat állítsd be:

```bash
set -euo pipefail
auth_restore_schema="adatdusito_restorecheck_$(date -u +%Y%m%d%H%M%S)"
mysql -u root -p -e "CREATE DATABASE \`$auth_restore_schema\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
gzip -dc /root/adatdusito-backups/IDE-A-VALOS-MENTES/adatdusito_dev.sql.gz | mysql -u root -p "$auth_restore_schema"
mysql -u root -p "$auth_restore_schema" -e 'SELECT version_num FROM alembic_version; SELECT COUNT(*) AS users FROM users; SELECT COUNT(*) AS memberships FROM memberships; SELECT COUNT(*) AS sessions FROM login_sessions; SELECT COUNT(*) AS products FROM supplier_products;'
```

A próba külön helyet igényel, a katalógus miatt nem kis mentés. Az ellenőrző sémát csak kézi felülvizsgálat után takarítsd el. A kulcsmentés biztonságát a DB-mentéstől külön is ellenőrizd; titkosított beállításokat tartalmazó mentéshez a hozzá tartozó kulcs kell.

**Korai visszalépés:** ha az új hitelesítést/beállításokat még nem használták, nincs `auth09.*` / `settings09.*` audit és e-mail nélküli új fiók, a migráció visszaléphet. Maga a downgrade is ellenőrzi ezt. A telepítési shell eredeti változóival:

```bash
cd /opt/adatdusito
set -euo pipefail
docker compose "${auth_compose[@]}" stop frontend backend worker
docker compose "${auth_compose[@]}" run --rm --no-deps migrate alembic downgrade 0007
auth_previous_commit=$(cat "$auth_backup_dir/previous-commit.txt")
git switch --detach "$auth_previous_commit"
if [ -f "$auth_backup_dir/compose.override.yaml" ]; then
  cp -p "$auth_backup_dir/compose.override.yaml" compose.override.yaml
elif [ -f "$auth_backup_dir/created-auth-override" ]; then
  mv compose.override.yaml "$auth_backup_dir/codex09-created-override.yaml"
fi
docker image tag "adatdusito-dev-backend:before-codex09-$auth_stamp" adatdusito-dev-backend
docker image tag "adatdusito-dev-frontend:before-codex09-$auth_stamp" adatdusito-dev-frontend
docker compose up -d --no-deps backend worker frontend
```

**Használat utáni rollback:** a régi alkalmazást nem szabad az új hitelesítési adatbázissal indítani, mert figyelmen kívül hagyná az MFA-t és nem ismerné az új fiókokat. Elsődleges a javító frissítés. Teljes visszaállításnál DBA-val: alkalmazás leállítása → aktuális állapot külön mentése → korábbi teljes mentés és összeillő kulcs próba-visszaállítása → későbbi üzleti változások egyeztetése → ellenőrzött teljes alkalmazásséma-helyreállítás → megfelelő korábbi image és konfiguráció → hitelesítési/jogosultsági/üzleti ellenőrzés. A meglévő sémára ráimportált dump nem elég, új táblák/FK-k maradhatnának. Nincs automatikus élő DROP vagy újrainicializálás, és a `pinfo_db` nem része a műveletnek.

## Ismert határok

- A Google valódi szolgáltatói kliensét, consent beállítását, külső proxyját és saját felhasználóval történő belépését az üzemeltető konfigurálja/ellenőrzi. Protokollszintű aláírásos tesztek készültek, éles szolgáltatói hitelesítő adat nincs a repositoryban.
- Passkey használata HTTPS-t és UV-képes eszközt/böngészőt igényel; a teszt valódi Chromium WebAuthn API-t és virtuális hitelesítőt használ. Fizikai eszközök közötti szinkronizálást nem az alkalmazás végzi.
- Külső SMTP kézbesítési reputációt, SPF/DKIM/DMARC és postaládába érkezést nem igazol a kapcsolatpróba. Helyi, tanúsítvánnyal ellenőrzött TLS SMTP és hitelesítés tesztelt.
- Cég-/webáruház-kapcsolat nélküli régi termék/importadat továbbra is csak teljes ügyfélkörrel olvasható. Nem történt automatikus besorolás.
- Próba-előfizetés/kapacitás, fizetés és AI-kreditek nem készültek. Az opcionális új regisztráció ezért szerveroldalon korlátozott, előfizetésre váró munkaterületet hoz létre.
