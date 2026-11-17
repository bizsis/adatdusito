# Segédlet-tartalom szerkesztése

A `HelpPage` csak a Támogatás → Segédlet megnyitásakor töltődik be. A cikkek
strukturált JSON-fájlok, nem futtatható Markdown/MDX vagy HTML. Nincs új backend,
adatbázis vagy tartalomkezelő. A cikkek új builddel kerülnek a felületre.

## Új cikk

1. Készíts egy új `articles/<azonosito>.json` fájlt. A fájlokat a Vite glob
   automatikusan felveszi; komponenskódot vagy kézi importlistát nem kell módosítani.
2. Az `id` legyen egyedi, kisbetűs ASCII slug, például `uj-utmutato`.
   Az URL `#/segedlet/uj-utmutato`; a meglévő id-ket lehetőleg őrizd meg.
3. A `topic` a `topics.json` egyik azonosítója. Az `order` a témakörön belüli
   sorrend; az azonos sorrendű címeket a felület magyarul rendezi.
4. Ellenőrizd a tényleges funkciót és a feliratokat. Jövőbeli AI-kutatást vagy
   UNAS-kiküldést ne írj le működő folyamatként.
5. Futtasd a frontend `npm test`, `npm run lint`, `npm run build` parancsokat.
   A tesztek a tartalom érvényességét, linkjeit és képeit is ellenőrzik.

```json
{
  "id": "uj-utmutato",
  "topic": "elso-lepesek",
  "title": "Új útmutató",
  "summary": "Mikor és mire használható?",
  "order": 20,
  "blocks": [
    { "type": "heading", "text": "A művelet lépései" },
    { "type": "paragraph", "text": "Rövid bevezető." },
    { "type": "steps", "items": ["Első lépés.", "Második lépés."] },
    { "type": "list", "items": ["Ellenőrzési szempont."] },
    { "type": "note", "title": "Fontos", "text": "Megjegyzés." },
    { "type": "warning", "title": "Figyelem", "text": "Mire ügyelj?" },
    {
      "type": "link",
      "article": "belepes-munkaterulet",
      "text": "Belépési útmutató"
    },
    {
      "type": "image",
      "src": "/help/images/munkaterulet.png",
      "alt": "Munkaterület kiválasztása",
      "caption": "Opcionális képaláírás."
    },
    {
      "type": "image",
      "src": "/help/images/feltoltes.png",
      "alt": "Fájlfeltöltés"
    }
  ],
  "related": ["belepes-munkaterulet"]
}
```

A szövegek React-szövegcsomópontként jelennek meg. A HTML nem értelmezett:
a `<script>` is csak szöveg. A belső link `article` azonosítót kap, nem URL-t.
Képként csak `/help/images/<slug>.png|webp|jpg|jpeg` használható; távoli URL,
`javascript:`, adathivatkozás, SVG és könyvtárbejárás nincs engedélyezve.
A cikkben több kép is lehet, mindegyik külön nagyítható. Az `alt` kötelező,
a `caption` elhagyható. A keresés a címben, összefoglalóban, bekezdésekben,
lépésekben, megjegyzésekben és képleírásokban is keres, ékezetfüggetlenül.

## Képernyőképek frissítése

A kilenc kép a `frontend/public/help/images/` könyvtárban van:
`munkaterulet`, `beszallito`, `feltoltes`, `oszlopok`, `import-jovahagyas`,
`kategorizalas`, `kezi-parameter`, `tomeges`, `exportprofil` (`.png`).

Mind valódi produkciós frontend bundle-ből készült, a natív FastAPI/SQLite
böngészőteszt szintetikus adataival, 1440 px-es asztali nézetben. A képek
DOM-elemek kivágásai: nincs rajzolt vagy utólag kitalált vezérlőelem. Nem jelenik
meg jelszó, token, API-kulcs, személyes vagy ügyféladat. A munkaterület neve
`Segédlet demó`, a termékek/fájlok tesztadatok. A kép nem bizonyít VPS-telepítést.

Frissítés kizárólag eldobható felhőtesztben, a repó gyökeréből, a frontend build után:

```bash
HELP_SCREENSHOTS=1 PYTHONPATH=backend .venv/bin/pytest -q \
  scripts/tests/test_help_browser.py::test_record_current_ui_screenshots_and_existing_workflows
```

A kapcsoló nélkül a teszt ellenőriz, de nem írja át a képeket. Nem futtatható
VPS-en vagy meglévő adatbázison. Meglévő felület hiányát ne pótold kitalált képpel;
ilyenkor maradjon pontos szöveges leírás és dokumentált hiányosság.

## HELP-02: részletes kézikönyv

A 36 cikk megtartja a 12 eredeti URL-t. Minden cikk tartalmaz célt,
előfeltételt és jogosultságot, pontos menüutat, mezőmagyarázatot,
demóeljárást, várt eredményt, hibakezelést és adatmegőrzési következményt.
A cikkek hosszúsága és a zöld teszt nem helyettesíti az emberi tartalmi ellenőrzést.

Új blokk a `table`: `caption`, `headers: string[]`, `rows: string[][]`.
A sorok elemszáma egyezzen az oszlopok számával. A cellák szövegek, HTML nem
futtatható. A teljes szöveges keresés a táblázatokat is figyelembe veszi.
A tartalomjegyzék a `heading` blokkokból készül; nem írja át a cikk URL-jét.

A képernyő- és műveletleltár a `coverage.json`; olvasható, képekkel és
forrásokkal összekötött változata:
[HELP-02-COVERAGE.md](../../../../docs/development/HELP-02-COVERAGE.md).
Új menü vagy cikk esetén ezt is frissíteni kell. A teszt a valódi `main.tsx`
menütömbjét TypeScript AST-ből olvassa, így az új, leltár nélküli menü hibát ad.

Az új képek újragyűjtése (a fenti 9 eredeti kép ettől külön marad):

```bash
HELP_SCREENSHOTS=1 PYTHONPATH=backend .venv/bin/pytest -q \
  scripts/tests/test_help_manual_browser.py
```

A képek legfeljebb 1400 px magas, natív DOM-/oldalkivágások; a hosszú űrlapból
csak a feliratozott részlet látható. Nincs rajzolt vezérlő vagy utólag módosított
képtartalom. A 390 px-es kép mobilnézet, a többi 1440 px-es asztali nézet.
A referencia-képek apró, szintetikus SQLite-forrásból készülnek, nem az éles
2,85 millió értékből. A kész katalógus tesztbeli előállítása és aktiválása
kizárólag ezen az eldobható fixture-ön történik. Soha ne futtasd a gyűjtőt VPS-en.

TOTP/QR, eszköztitok, helyreállítási kód, meghívó- vagy jóváhagyási token,
SMTP-/OIDC-jelszó nem rögzíthető. Külső Google- és natív passkey-ablakból nem
készítünk kitalált képet. A forrásszintű leírás mellett ez külön emberi/eszközös
ellenőrzési pont marad.

Az önálló HELP-02 átadásban a #41/#42 még nem szerepelt. A RELEASE-CANDIDATE-02
integrálja ezeket (#43), ezért a törlésről, kompakt előnézetről és figyelmeztetésekről
szóló importcikkeket és képeket frissítettük. UNAS-fájlgenerálás, AI-kutatás és
kredit/fizetés továbbra sem kész funkció. A történeti átadási leltár és a jelenlegi
felhasználói útmutató verzióját külön kezeld.

## RELEASE-CANDIDATE-02 importképek

A #43 és #46 egyesítése után öt új, szintetikus képernyőkép mutatja a tényleges
kompakt importfelületet: `rc02-oszlopok`, `rc02-elozet`, `rc02-jovahagyas`,
`rc02-importtortenet`, `rc02-importtorles`. A korábbi képek a történeti leltárhoz
megmaradnak; a normál importcikkek az új vezérlőket mutatják.

```bash
RC02_SCREENSHOTS=1 PYTHONPATH=backend .venv/bin/pytest -q \
  scripts/tests/test_release_candidate02_browser.py
```

Csak az eldobható FastAPI/SQLite-fixture-ön futtatható. A 390 és 1440 px-es
folyamatot is ellenőrzi; képet csak 1440 px-en ír. A CSV a hibajegy tényeit
rekonstruáló `rc02_sample.synthetic_feed()`, nem az eredeti beszállítói fájl.
A következő import-UI változtatásnál ezeket a képeket és a mezőneveket újra kell
ellenőrizni. A teljes HELP-02 kézikönyv emberi tartalmi jóváhagyása ettől még
nem tekinthető késznek.
