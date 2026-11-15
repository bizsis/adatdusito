# CATEGORY-02D – PR #18 és #19 integrációs ellenőrzés

Feladat: [#21](https://github.com/bizsis/adatdusito/issues/21).
Integrációs ág: `codex/category-02d-integration`. Ez tesztág, nem main-merge és
nem telepítési jóváhagyás. A két kiinduló PR ága változatlan marad.

## Reprodukálható kiindulópont

| Összetevő | Pontos commit |
| --- | --- |
| Main kiindulópont | `80b0dce5b5270eb5de1ccecbfef5427ce35aa2c3` |
| PR #18 backend | `8c5db11c091668188ea4ddcd6e1195ea8cc29af2` |
| PR #19 frontend | `0625e4b2489a9f4d3f7c2387fda86bb638dc0b77` |
| Integrációs merge, ütközés nélkül | `74f4c64` |

A tesztek az együttes kódot használják: a produkciós Vite buildet Chromium
jeleníti meg, a `/api/v1/...` kérések a valódi FastAPI alkalmazásba jutnak,
valódi session/CSRF/jogosultsági middleware-rel és izolált SQLite fixture-rel.
A nem hibainjektált API-válaszokat nem írjuk át. A bridge a meglévő backend
browser-tesztekhez hasonlóan TestClientet használ, nem egy telepített MySQL/Nginx
szervert. VPS, eredeti `pinfo_db`, `.env` és ügyféladat nem érintett.

## Végpont- és DTO-összehasonlítás

| Művelet | Frontend és backend szerződése / ellenőrzés |
| --- | --- |
| `GET /workspace/products` | `q` név/SKU/GTIN, 120 karakter; `status`, `origin`, `navigation_node_id`; 25-ös kurzoros lapozás. Az ékezet-/wildcard-szabály a backendé, nincs helyi termékszűrés. |
| `status_counts` | A keresés és többi szűrő érvényesül; a státuszszűrő nem szűkíti a két számlálót. Üres találat és 50 003 tárolt rekord is ellenőrzött. |
| `GET /workspace/products/{id}` | Saját kategória változatlan, belső kategória külön; `capabilities.classify`, forrásmezők, eredet, zár és audit. 404 nem üríti sikeresnek látszó termékké a részletet. |
| `PATCH .../classification` | `set/reset`, `expected_revision`, opcionális donor; valódi 403/404/409/422 és sikeres set/reset. Revízióütközéskor friss olvasás, nincs automatikus újramentés. |
| `GET /workspace/category-maps` | 50-es oldalak; 53 saját kategóriánál két lap. `map: null`, nullable indok és jóváhagyott/elutasított térkép támogatott. |
| `PUT /workspace/category-maps/{id}` | `expected_revision: null` vagy aktuális revízió, jóváhagyás/elutasítás. Minden nem zárolt sajátkategória-termékre hat; nincs opcionálisnak tűnő örökítés. |
| `DELETE .../category-maps/{id}` | Revízió queryben, body nélkül; térkép ténylegesen eltűnik, termékek újrabesorolódnak. Külön „törölve” sikerfelirat. |
| Helyi előnézet | Csak az ismert kategória/donor-változás és becslés. Nem hív nem létező dry-run API-t; lock/konfliktus előre ismeretlen. Mentés előtti kilépés nem ír adatot. |
| `products_changed/locked_skipped` | Kizárólag a sikeres, érvényes mentési válaszból lesz pontos visszajelzés. Hibás válasz után explicit visszaolvasás kell akkor is, ha a szerver már mentett. |
| `GET /workspace/internal-categories` | Valós API: 457 kategória, 100+100+100+100+57-es oldalak. Minden ID elérhető, teljes útvonallal. Nincs hardcoded 412-es UI-korlát. |
| Több donor | `Töltőkábelek` két profilja külön opció; a kiválasztott külső eMAG-ID megy a szervernek. A besorolás nem állítja a donor/dúsítás automatikus jóváhagyását. |
| Küszöb | Olvasás `GET /system/settings`, `classification.auto_threshold = 0.98`; mentés `PUT /system/settings/classification`, 0,5–1 skála. A külön `GET /system/settings/classification` nincs implementálva, ezért nem használjuk. |
| Tenant/RBAC | Valódi csak-olvasási capability, írási jog visszavonása, másik ügyfél üres listája és idegen termék 404. Tenantváltás a meglévő áttekintésre lép vissza, nem tart meg nyitott terméket/keresést. |

## Javított eltérések és hibák

1. **Hibás JSON-alakok:** a TypeScript típus önmagában nem futásidejű védelem.
   A fogyasztott DTO-mezőket ellenőrizzük listázás, részlet, választó, térkép és
   mentési válasz előtt. Hibás választ nem alakítunk üres sikerlistává, nem
   jelenik meg React-hiba vagy hamis mentési siker. Az additív mezők engedélyezettek.
2. **Még nem besorolt termék:** a valódi backend `method: null` és
   `rule_version: null` értéket is ad. A frontend DTO nullable, a felirat
   „Még nincs”, nem technikai `null`. A 50 003-as teszt ilyen termékeket is lefed.
3. **Kategóriatérkép indoka:** `reason` a valós API-ban nullable; a frontend
   típus ezt követi. Nem változtatunk backendmezőt vagy sémaelőírást.
4. **Helyreállítás:** induló listaolvasási hiba után újrapróbálás, további
   olvasási hibák után újratöltés, bizonytalan/elutasított mentés után friss
   adatbetöltés. A kliens nem írja újra vakon az esetleg már mentett adatot.
5. **Műveleti visszajelzés:** törlés/elutasítás után nem „mentve/jóváhagyva”
   üzenet jelenik meg; a pontos változott/kihagyott darabszám továbbra is a szerveré.
6. **Donor és besorolás:** külön figyelmeztetés tisztázza, hogy a donorprofil
   kiválasztása nem a későbbi automatikus dúsítás vagy egy kétes donor jóváhagyása.
   Nem épült új AI-, kredit-, általános bulk- vagy bizonyítékkezelő folyamat.

A 13 főcsoport sorrendje a valós `/reference/navigation?scope=tree` válaszból
az eredeti specifikációval összehasonlított; a 457 kategória minden teljes
útvonala és path-ID sora a teszt előtti/utáni pillanatképben változatlan.
A meglévő 412-es mock-összesítések 457-re frissültek; ezek továbbra is csak mockok.

## Claude számára egyeztetendő dokumentációs pontok

Backend/migrációs kódot nem javítottam párhuzamosan. A PR #18 szerződésében
érdemes egyértelművé tenni a még nem besorolt termékek nullable `method` és
`rule_version`, valamint a térkép nullable `reason` mezőjét. A beállításrész
GET/PUT címe ne sugalljon létező külön GET classification-végpontot.
A donorlistában csak azonosító/név szerepel; donoronkénti későbbi dúsítási
jóváhagyást vagy minősítést ebből nem lehet megállapítani. A frontend ezért
semleges tájékoztatást ad, és nem állít ilyen szerveroldali jóváhagyást.

Ezekhez most nem szükséges séma- vagy backendimplementáció-módosítás. A 457-es
választék valós, ezért a korábbi 412-es leírások elavultak. A felhasználó által
jóváhagyott fa megmarad.

## Új és meglévő tesztek

`scripts/tests/test_category02d_browser.py`: valódi név/SKU/EAN és státusz,
valós számlálók; minden 457 kategória és a 13 gyökér; több donor;
térképlapozás/jóváhagyás/törlés/elutasítás/409; előnézet és mentés nélküli kilépés;
50 003 tényleges SQLite-termék, legfeljebb 25 DOM-sor és kis válasz;
401/403/404/409/422; csak-olvasás/tenantváltás; hibás JSON-alakok; már megtörtént
mentés hibás válasza; 503 utáni helyreállítás; gyors keresés és késői régi válasz.

**Hibainjektálás külön kezelve:** a hibás JSON és a hálózati 503 a tesztbridge
szándékos hibája; a valódi szerver válasza és a transport-fault külön naplózott.
A késleltetés a valódi API-választ tartja vissza. Ezek nem backend DTO-/üzleti
folyamat-bizonyítékok. A többi esetben a szerver valódi válasza jut a böngészőbe,
beleértve a tesztelt 401/403/404/409/422-t. A korábbi két valódi integrációs teszt
külön ellenőrzi a kézi set/reset-et, reimport-zárat/auditot, mapöröklődést és a
0,98-as küszöb olvasását/mentését is.

```bash
cd frontend
npm ci
npm run lint
npm run test:lint
npm run build
npm audit --audit-level=high
cd ..
python backend/scripts/check_requirements.py --resolve
PYTHONPATH=backend python -m pytest -q backend/tests scripts/tests \
  --ignore-glob='*_browser.py' --ignore=scripts/tests/test_emag_menu_export.py
PYTHONPATH=backend python -m pytest -q backend/tests/*_browser.py scripts/tests/*_browser.py
# A CI külön menu-export jobjának önálló tesztje:
python -m pytest -q scripts/tests/test_emag_menu_export.py
# A meglévő Dockerfile-okkal mindkét image buildelendő.
```

A 50 003-as adatsor izolált tesztfixture, nem egyszeri 50 003-as import. Nincs
állományszintű 50 000-es korlátozás vagy memóriaigényes teljes termékletöltés.
MySQL-terhelésmérés, VPS/Nginx/HTTPS telepítési teszt nem történt; ezekre nincs
engedély ebből a feladatból. A helyi futás nem azonos a GitHub Actions futásával.
