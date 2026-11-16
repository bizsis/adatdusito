# HELP-01 – Támogatás / Segédlet

Alap: `codex/release-candidate-01`, pontos SHA:
`09dc09b374bf6a9d52a60c329e47dcd14b85e1aa`.
Fejlesztési ág: `codex/help-01`. Külön draft PR, base: `codex/release-candidate-01`,
így csak a HELP-01 változások kerülnek a diffbe. Nincs main-merge vagy VPS-telepítés.
A RELEASE-CANDIDATE-01 eredeti ága és adatfeldolgozási kódja változatlan.

## Funkció és tartalom

- Támogatás lenyíló főmenü, egyetlen Segédlet almenüvel, Lucide ikonokkal.
- Minden bejelentkezett felhasználónál megjelenik, külön üzleti jogosultság nélkül.
  A bejelentkezési, MFA- és jelszócsere-korlátokat nem kerüli meg.
- Külön, lazy-loaded oldal. A cikkfájlok/CSS csak megnyitáskor töltődnek; a képek
  reszponzívak és lazy-loadedek. Nincs új függőség vagy backend API.
- Ékezetfüggetlen keresés címben és teljes tartalomban; témakörszűrés és sorrend.
- Egyedi, megosztható fragment URL-ek; reload, böngésző-vissza, kapcsolódó cikkek,
  témakörökhöz visszalépés, hiányzó cikk és üres találat kezelése.
- Strukturált tartalom: alcím, bekezdés, lista, számozott lépések, megjegyzés,
  figyelmeztetés, belső link, több kép és képaláírás. HTML/script nem futtatható;
  képként csak szűkített helyi raszteres útvonal fogadható el.
- Natív dialogos képnagyítás, Bezárás/Escape és fókusz-visszaadás; billentyűzetes menü.

A 8 témakörben 12 útmutató szerepel:

1. Bejelentkezés és munkaterület kiválasztása
2. Beszállító létrehozása
3. CSV/XLSX feltöltése
4. Oszlopok megfeleltetése
5. Import ellenőrzése és jóváhagyása
6. Termékek kategorizálása
7. eMAG-paraméterek és donorprofilok
8. Paraméterek kézi javítása és zárolása
9. Tömeges feldolgozás és előkészítési jóváhagyás
10. Exportprofilok beállítása
11. Felhasználók és jogosultságok
12. Gyakori kérdések és hibák

A cikkek az aktuális ImportWorkspace, ClassificationWorkspace, LiveParameters,
LiveBulkPreparation, ApprovalReview és ExportAdmin működésére épülnek. A kötött
paraméterértékek szabad kézi szerkesztését nem ígérik. A tényleges AI-kutatást és
UNAS-exportot kifejezetten még nem kész végfelhasználói folyamatként jelölik.
A jelenlegi ügyfél-exportprofilban nincs külön profilnév-szerkesztő; ezt a cikk
pontosítja, a termékfunkciót ebben a feladatban nem módosítjuk.

## Képek és szerkesztés

**9 verziózott PNG**, `frontend/public/help/images/`. A képek a produkciós
frontend aktuális, valódi vezérlőit mutatják tesztadatokkal; nincs ügyféladat,
személyes adat, jelszó vagy token. A képrögzítés az izolált natív böngészőteszt
része, külön kapcsolóval; normál CI nem írja át az állományokat.

Szerkesztési útmutató, séma, lista és biztonsági szabályok:
[frontend/src/support/README.md](../../frontend/src/support/README.md).
Új cikkhez csak új JSON-tartalomfájl és szükség esetén kép kell, komponenskód nem.

## Ellenőrzések

```bash
(cd frontend && npm test && npm run lint && npm run build)
PYTHONPATH=backend .venv/bin/pytest -q scripts/tests/test_help_browser.py
PYTHONPATH=backend .venv/bin/pytest -q -ra backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
```

A frontend `npm test` megtartja a korábbi három lintkonfigurációs tesztet, és
hozzáadja a keresés/útvonal/tartalom/kép/XSS megjelenítés vizsgálatait. A CI frontend
jobja ezt is futtatja. A HELP ág saját push-triggert kap a PR API esetleges korlátja
melletti hosted ellenőrzéshez; a MySQL gate és a többi job logikája változatlan.

A natív böngészős teszt 390 és 1440 px-en ellenőrzi a teljes navigációt, keresést
(szerverhívás nélkül), témaköröket, cikkeket, reload/back/kapcsolódó linkeket,
képnagyítást, Escape-et, fókusz-visszaadást, vízszintes túlcsordulást és 404-et.
Üzleti jogok nélküli hitelesített felhasználóval is megnyitja, és kijelentkezés
után a bejelentkezési határt vizsgálja. A képrögzítő smoke a meglévő import-,
besorolási, paraméter-, tömeges és exportnézetet is végigjárja. Csak szintetikus
SQLite-adatok érintettek; a referencia-kapcsolat írásmentessége is ellenőrzött.

A helyi végső ellenőrzés: **10 frontendteszt** (7 segédlet/tartalom/biztonság,
3 meglévő lintkonfiguráció), **5 natív böngészőteszt**, **437 backend/eszközteszt**,
lint és TypeScript/Vite build: mind sikeres. A képrögzítő smoke külön is sikeres.
A cikkek renderelője és tartalma külön HelpPage chunkba került (kb. 27,4 kB,
gzip 9,4 kB), a 9 PNG összesen kb. 472 kB, és nem töltődik be a Segédlet
nyitóoldalán. Nincs új runtime vagy fejlesztői függőség.
A végső átadás a hosted futás eredményét és a pontos commit SHA-t külön rögzíti.

## Mobil témakörváltási regresszió

Az első hosted futásban a 390 px-es témakörválasztó a keresés törlése után a
négy importcikk helyett nullát mutathatott. A natív hivatkozás már módosította az
URL-t, de a sorba állított `hashchange` előtt a React-állapot még a régi keresést
őrizte. A gyors select/change ebből visszaírhatta a törölt keresőszöveget.

A vezérlők most az aktuális URL-t olvassák, és a témakörváltáskor is közvetlenül
frissítik a React-állapotot. A böngésző vissza/előre eseménykezelése megmarad.
Az új, késleltetett hashchange-et szimuláló natív regresszió a javítás előtt
0 cikkel elbukik, a javítás után változatlanul 4 importcikket vár és kap. Az
ellenkező irányt is vizsgálja: témakörtörlés utáni gyors keresés nem állíthatja
vissza a régi témakört. Az eredeti mobil/asztali teszt elvárásai nem gyengültek.
A teljes HELP-csomag: **5 passed**, a frontendcsomag: **10 passed**, lint/build zöld.
A végső átadás a javított commit új teljes hosted CI-futását adja meg.

## Határok

Nincs backend-, migráció-, `.env`-, Compose-, referenciaadat- vagy VPS-konfiguráció-
változtatás. Nincs új import-, kategorizálási, paraméter-, AI- vagy exportlogika.
A Segédlet nem jogosultságbővítés. A 3 vitatott donor és az RC biztonsági korlátai
változatlanok. A bejelentkező oldalról nem készül jelszót vagy biztonsági kódot
mutató kép; a belépési útmutató a munkaterület-választót ábrázolja.
