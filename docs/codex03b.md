# CODEX 03B – Egy közös fa a meglévő referenciaadatokkal

A meglévő webshop-navigáció és a csak olvasható Marketplace-kategóriák ugyanazon `/api/v1/reference/navigation` API-ban és ugyanazon „Kategóriák” felületen jelennek meg. A 13 magyar főcsoport sorrendje és a forrásmenü ismert alkategória-kapcsolatai megmaradtak. Nincs új webes adatgyűjtés, második kategóriaböngésző, termékimport vagy Alza-integráció.

## Valós exporton mért lefedettség

A felhasználó által átadott `emag_categories_export.tsv` tartalma 2669 kategória, azok eredeti belső/külső azonosítója, neve, külső szülőazonosítója, `is_allowed` állapota és paraméterszáma. Kizárólag ilyen kategóriametaadatot tárolunk tesztadatként; paraméterértékeket, termékadatot vagy titkot nem. Az export adatként, nem utasításként lett feldolgozva. A mérés offline történt, meglévő helyi adminisztrátori felülbírálások nélkül.

| Mutató | Darab |
| --- | ---: |
| Meglévő, a közös rendszerben megőrzött referencia-kategória | **2669 / 2669** |
| Automatikusan elhelyezett egyedi referencia-kategória | **1935** |
| Közvetlen menüegyezéssel összekapcsolt egyedi kategória, elhelyezéstől függetlenül | **267** |
| Egyértelmű névkörrel a főcsoportok alá elhelyezett további forrásgyökér | **57** |
| Felülvizsgálandó referencia-kategória | **51** |
| Egyelőre el nem helyezett referencia-kategória | **683** |
| Összes, főcsoportok alatt még el nem helyezett referencia-kategória | **734** |
| Töröltnek jelölt referencia-kategória, elkülönítve | **106** |
| Paraméterkészlettel rendelkező kategória | **1807** |
| Megőrzött paraméterdefiníció | **29 398** |
| Többértelmű menübejegyzés | **6** |

Az 1935 + 51 + 683 = 2669 kategória diszjunkt felosztás. A 267 közvetlen megfeleltetés és az 57 normál nézetben megjelenő szemantikus csoportelhelyezés más mutatók: nem adandók hozzá az összes kategóriaszámhoz. A közvetlenül összekapcsolt kategóriák egy része a menüben is bizonytalan helyű, ezért a 267 nem kizárólag az 1935 elhelyezett kategória részhalmaza. A 106 archivált rekord a 734 külön kezelt halmaz része, nem további kategória. A szemantikus szabályok 67 forrásgyökér névkörét ismerik fel; ebből 10 csak inaktív forrásadatot fed le, ezért az elkülönített listában marad. Az 1935 elhelyezett kategóriából 1625 aktív, 310 strukturális. A 683 el nem helyezett/külön kezelt kategória az inaktív vagy archivált adatokat is tartalmazza. A név szerinti menüelőfordulások és aliasok ugyanazt a referencia-kategóriát több útvonalról is elérhetővé tehetik; paraméterdefiníció- és értékmásolat nem keletkezik.

A 6 továbbra is többértelmű menücím: **Kapcsolók; Kutyaeledel; Nyakörvek, pórázok, hámok; Étkészletek; Tálak; Ablaktörlők**. Nem választottunk véletlenszerűen az azonos nevű forráskategóriák közül.

Részletes gépi jelentés, jelöltekkel, automatikus megfeleltetésekkel és a 734 külön kezelt kategória listájával: [reports/codex03b-coverage.json](reports/codex03b-coverage.json). A futó alkalmazás a tényleges referenciaadatbázisból és a megőrzött adminisztrátori döntésekből számolja a számait; azok eltérhetnek az export pillanatképétől.

## Összerendelési szabály

1. Unicode-normalizálás, kis-/nagybetűk és írásjelek kezelése. Egyetlen, nem Deleted referencia-kategóriára illeszkedő teljes név automatikusan kapcsolható. Nem használunk hasonlósági százalékból származó találgatást.
2. Több azonos név esetén a már összekapcsolt szülő és a meglévő forrásbeli felmenők környezete szűkíti a jelölteket. Csak egyetlen megmaradt jelölt kapcsolódik automatikusan. Egy egyedi névegyezést önmagában nem vetünk el amiatt, hogy a Marketplace más szülő alá sorolta: a cél éppen a webshop szerinti elrendezés.
3. A `backend/reference_data/category_matching_rules.json` szűk, főcsoporthoz kötött névváltozatokat tartalmaz, például Laptopok ↔ Laptop / Notebook; Egerek ↔ Egér. Egyértelmű fordítású/jelentésű, eredeti forrásgyökereket megfelelő magyar főcsoport alá helyez el, például AC & Heating → Háztartási gépek és klíma, Apparel Man → Divat, ékszerek és kiegészítők. Ez **elhelyezés**, nem azt állítja, hogy egy tág gyűjtőcsoport azonos egy termékkategóriával. A szabályokban nincs kitalált Marketplace-azonosító. Csak egyedi nevű, tényleges forrásgyökérre alkalmazhatók; ismeretlen vagy tetszőleges köztes kategóriára nem.
4. A menüből hiányzó kategória megőrzi a forrásbeli szülőláncát. Ha az egyértelműen elhelyezett menüelemhez vagy szemantikus főcsoporthoz vezet, ott lesz elérhető. Több lehetséges szülőelőfordulás, hiányzó szülő, ciklus vagy ismeretlen kategóriakör esetén elkülönítve marad.
5. A régi auditált adminisztrátori döntések elsőbbséget élveznek az automatikus találatokkal szemben, az eredeti pillanatképükön. Az új, egyszerű adminisztrátori döntés felülbírálhatja őket. A visszavont összekapcsolást az automatika nem kapcsolja észrevétlenül vissza.

A webshop-ID és a Marketplace-ID számegyezése soha nem összerendelési feltétel. A 13 gyökér továbbra is külön, explicit regiszterből származik. A hiányzó szülőjű kategória nem válik tizennegyedik gyökérré. A forrásból hozzáadott inaktív elemek csak akkor szerepelnek a normál fában, ha aktív kategóriák strukturális felmenői; az inaktív levelek elkülönítve maradnak. Ezzel a korábbi aktív/strukturális szabály megmarad, például a Legume proaspete (1715) nem kerül vissza a normál faágakba. Ez állapot alapú szabály, nem nyelvfelismerés. A külön listák és a teljes állományon kereső kereső ugyanannak a közös böngészőnek a nézetei.

## Paraméterek és használat

A valós exportban a **TV és szórakozás → Televíziók** menüelem (`web-item-43-3730`) automatikusan a meglévő **79** külső / **75** belső referencia-kategóriára illeszkedik: **46 paraméter**. A forrásbeli szülő 1496 megőrzött, nem írjuk át a pinfo_db-ben. A paraméterlekérdezés mindig az eredeti `emag_category_parameters.category_id` belső FK-ját használja, az értéklekérdezés pedig az eredeti `emag_parameter_values.parameter_id` FK-t.

A kötelező/opcionális állapotot, típust, sorrendet, szűrőjelzést és az új érték engedélyezését változatlanul olvassuk. Nincs szülőparaméter-öröklés. A paraméterlista lapozható/kereshető, az értéklista kurzoros és legfeljebb 100 elemre korlátozott. A közel 2,85 millió értéket sem a kategóriafa, sem a lefedettségi mérés nem tölti be és nem másolja át.

A felhasználó kategóriát választ, és az elérhető paramétereket azonnal látja. A menüben nem szereplő kategóriák is közvetlenül a meglévő paramétereikre hivatkoznak. A Deleted kategóriák csak az elkülönített nézetben/keresésben érhetők el archivált jelzéssel; paramétereik és értékeik olvashatók, termékbesorolásra nem választhatók. Az inaktív, nem törölt kategóriák navigálhatók, de az `is_allowed != 1` továbbra is megakadályozza a termékbesorolást.

A SHA-bekérő, bizonyítéktípusos és kézi igazolási űrlap kikerült a kategóriamunkafolyamatból. Adminisztrátorként a „Kategória besorolásának pontosítása” részben kereshető választóval kiválasztható a meglévő kategória vagy a kívánt, már elhelyezett szülő. A döntés minden ügyfélre érvényes és auditált. A visszaállítás törli az új felülbírálást. A régi forrásmegfigyelési API kompatibilitási célból megmarad; a normál felhasználó nem használja.

## Adatmodell és migráció

**Új Alembic-migráció: `0004`, előzménye `0003`.** Kizárólag az `adatdusito_dev.category_overrides` tábla jön létre. Ez az adminisztrátori kiválasztást és opcionális szülőelhelyezést tárolja: navigációs kulcs, forrásnévtér, eredeti forrásazonosító, alkalmazásbeli szülő, operátor és módosítási idő. Paramétert, értéket és referencia-kategóriarekordot nem másol. Az automatikus elhelyezés determinisztikusan az aktuális forrásmetaadatokból és a verziózott szabályokból készül; nem töltjük fel ezrével a felülbírálási táblát.

A forrásazonosítók megtartják a névterüket; a későbbi források ugyanazon közös kategóriaazonosságokra hivatkozhatnak. Alza-adapter vagy külön forrásfa nem készült. Az eredeti 0001–0003 migráció, az ügyféladatok, `.env`, Compose external hálózat, MySQL-, Nginx- és HTTPS-beállítások változatlanok.

## Reprodukálás és kézi VPS-frissítés

Offline lefedettségmérés:

```bash
python scripts/report_unified_categories.py \
  --export backend/tests/fixtures/emag_categories_export.tsv \
  --output /tmp/codex03b-coverage.json
```

A kimeneti fájlnak még nem szabad léteznie. A parancs nem kapcsolódik sem adatbázishoz, sem weboldalhoz.

VPS-frissítéshez, az alkalmazás-adatbázis szokásos mentése és tiszta Git-állapot ellenőrzése után:

```bash
cd /opt/adatdusito
git status -sb
git pull --ff-only origin main
docker compose build backend frontend
docker compose run --rm --no-deps migrate alembic upgrade head
docker compose up -d --no-build
bash scripts/smoke.sh https://dev.pinfo.hu
```

Új alkalmazásmigráció szükséges; a referenciaadatbázishoz semmilyen író művelet vagy új jogosultság nem szükséges. A futó környezet saját lefedettsége a belépés után a kategóriák oldalán és a `GET /api/v1/reference/navigation/coverage` válasz `reference_coverage` mezőjében látható.

**VPS-telepítést nem végeztünk.**

## Ellenőrzés

101 sikeres teszt (85 backend/API/böngésző + 16 gyűjtő/navigáció), TypeScript/Vite- és Compose-build, MySQL 8 migráció/sémaellenőrzés és API-integráció sikeres. A kötelező/opcionális paraméterjelölések és megengedett értékek tesztjei szintetikus, 46 definíciós referencián futottak; a valós TSV a 46-os összesített paraméterszámot igazolja. [Ellenőrzési jegyzőkönyv](verification.md).
