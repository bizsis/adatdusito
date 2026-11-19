# TEMPLATE-RESULT-01 – UNAS-kompatibilis termékadat-állomány a mentett sablonból (API-szerződés)

Alapág: `codex/template-preparation-integration`, ág: `claude/template-result-backend`.
Backend: Claude. Frontend: Codex. A szerződés a megvalósítás **előtt** készült.

Cél: egy mentett sablonverzió alapján egy feltöltött beszállítói fájl **minden termékét**
UNAS-kompatibilis sorrá alakítani, majd lapozható előnézetben megmutatni, és CSV- vagy
XLSX-fájlként letölthetővé tenni. eMAG-, AI- és termékimport-folyamat nincs benne; ezek
változatlanok.

## Alapelvek

- **Csak olvas, nem ír.** Az eredmény a sablonverzióból és a forrásfájlból mindig újra
  előáll. Nem hoz létre és nem módosít terméket vagy importfutást, és nem indít feldolgozást.
  A sablonok verziói változatlanok.
- **Csak dokumentált UNAS-oszlop kerül a fájlba.** A fejléc vagy a meglévő UNAS-sémában
  (`backend/app/unas_schema.py`) ismert szabványoszlop, vagy szabályos
  `Paraméter: …` fejléc. Ha egy sablon-hozzárendelés fejléce nem ilyen (pl. a nem igazolt
  `Raktárkészlet #1`), az oszlop **kimarad**, és `undocumented_header_excluded`
  figyelmeztetést kap.
- **Fiktív érték nincs.** Hiányzó kötelező adat jelzést kap, kitalált érték nem kerül a
  helyére. Az egyetlen alapértékek a jóváhagyottak: Státusz = 1 és ÁFA = 27 % (a sablonban
  szerkeszthetők).
- **Devizaváltás nincs.** A fájl a sablon pénznemében, a forrás számaival készül.
- **A forrásadat megmarad**; a forrásfájl és a futás változatlan.
- Ügyfélhez (tenanthoz) kötött, `no-store`; a letöltés auditált (`import.template_result_download`).
- Jogosultság: `imports.read`.

## Az átalakítás szabályai

| Célmező | UNAS-oszlop | Szabály |
|---|---|---|
| Cikkszám | `Cikkszám` | Szöveg, a forrás szerint. Ha üres: **`missing_sku` hiba**, a sor nem kerül a letöltött fájlba. |
| Termék megnevezés | `Termék Név` | Szöveg. Ha üres: `missing_required` (`termek_megnevezes`). |
| Kategória | `Kategória` | A forráskategória **változatlanul**. Ha üres: `missing_required` (`kategoria`). |
| Alternatív kategória n | `Alternatív Kategória n` | Szöveg. |
| Gyártó | `Paraméter: Márka\|\|enum\|…` | Szöveg. |
| Raktárkészlet #0 | `Raktárkészlet` | Szám (tizedesvessző is). Negatív érték változatlanul marad, `negative_stock` figyelmeztetéssel. #1-től: nem dokumentált, kimarad. |
| Nettó ár / Bruttó ár | `Nettó Ár` / `Bruttó Ár` | Szám. A hiányzó oldal ismert ÁFÁ-ból számolódik: nettó = bruttó / (1 + ÁFA), 4 tizedesre; bruttó = nettó × (1 + ÁFA), 2 tizedesre (ROUND_HALF_UP). Ha mindkettő adott és az eltérés 0,01-nél nagyobb: `price_vat_mismatch`, és egyik sem módosul. Ha egyik sincs: `missing_price`. |
| Nettó/Bruttó akciós ár | `Akciós Nettó Ár` / `Akciós Bruttó Ár` | Ugyanaz a számítás. Hiánya nem hiba. |
| Akció kezdete / vége | `Akció Kezdet` / `Akció Lejárat` | `ÉÉÉÉ.HH.NN` alakra igazítva (felismert formátumok: ISO, `ÉÉÉÉ.HH.NN`, `ÉÉÉÉ-HH-NN`, `NN.HH.ÉÉÉÉ`, `NN/HH/ÉÉÉÉ`). Felismerhetetlen dátum: üres, `invalid_date`. Üres forrás: üres. |
| ÁFA | – (az UNAS nem tárol áfakulcsot) | A sor ÁFÁ-ja: a forrásoszlop 0/5/18/27 (`%` jellel is) értéke, vagy a sablon alapértéke. Érvénytelen forrásérték: `invalid_vat`; ilyenkor az adott sorban nincs árszámítás. |
| EAN | `Paraméter: EAN\|\|text\|…` | Lásd *EAN/vonalkód*. |
| Gyártói cikkszám | `Paraméter: Gyártói cikkszám\|\|text\|…` | Szöveg (azonosítószabály, mint az EAN-nál, ellenőrzőszám nélkül). |
| Részletes leírás / Rövid leírás | `Tulajdonságok` / `Rövid Leírás` | Szöveg/HTML, változatlanul. |
| Mennyiségi egység, Másodlagos egység | `Egység`, `Másodlagos egység` | Szöveg. |
| Másodlagos mennyiség, Min. rendelhető, Lépésköz, Tömeg | `Másodlagos egység váltószám`, `Min. Menny.`, `Lépésköz`, `Tömeg` | Szám (tizedesvessző is). Nem szám: üres, `invalid_number`. |
| Státusz | `Státusz` | Forrásérték 0/1, vagy egyértelmű igen/nem jellegű szöveg (1/0). Üres vagy nincs oszlop: a sablon alapértéke (1). Más érték: üres, `invalid_status`. A készletnek nincs köze a Státuszhoz. |
| Termék összevonás alapja | `Alap Típus` | Szöveg. |
| Export tiltás | `Export Tiltás` | Szöveg. |
| Kép | `Kép link` | **Minden** hozzárendelt kép, a kezelő által megadott sorszám szerint, `\|` jellel elválasztva egyetlen cellában; az első a főkép. Ha egy forráscella már `\|`-vel tagolt több linket tartalmaz, azok a helyükön megmaradnak. Üres képoszlop nem hagy rést (az UNAS-ban nincs üres hely), a többi kép relatív sorrendje nem változik, és a hiányt `image_missing_in_sequence` jelzi (`orders`). 10-nél több kép: mind megmarad, `images_over_unas_limit` jelzéssel. |
| További lapfül 1–3 | `További lapfül tartalma 1–3` | Szöveg/HTML. |
| Kiegészítő / Hasonló termékek | `Kiegészítő Termékek` / `Hasonló Termékek` | Szöveg. |
| Paraméter | a sablon `Paraméter: …` fejléce, a dokumentált teljes formátumban (TEMPLATE-FIX-02) | Szöveg, változatlanul. Az előnézetben a `columns[].label` `Paraméter: Név`. |

- **Oszlopsorrend:** a célmezőlista sorrendje. Többszörös célnál példány, illetve sorszám
  szerint; a paraméterek a végén, oszlopsorrendben.
- **Beszerzési ár:** csak akkor lesz ár, ha a kezelő a sablonban kifejezetten eladási árhoz
  rendelte (`purchase_price_as_sale_price` figyelmeztetés a sablonban). A rendszer önmagától
  soha nem használja eladási árként.
- **Pénznem:** ha a forrásban pénznemkód-oszlop van, és egy sor értéke eltér a sablon
  pénznemétől, a sor `currency_mismatch` figyelmeztetést kap. Átváltás nincs.
- **Ismétlődő Cikkszám:** minden ilyen sor `duplicate_sku` figyelmeztetést kap, és mindegyik
  megmarad.

### EAN/vonalkód (CSV, XLS, XLSX)

Az EAN mindig szövegként kerül a fájlba, a vezető nullák megmaradnak.

- **Csupa számjegy** (pl. `0012345678905`): változatlan.
- **Lebegőpontos írásmód egész értékkel** (pl. `5901234123457.0`): a `.0` elhagyható, mert
  nincs veszteség.
- **Tudományos jelölés teljes mantisszával** (pl. `5,901234123457E+12`): visszaállítható, ha a
  mantissza számjegyeinek száma eléri az eredmény jegyeinek számát. Az eredmény csak akkor
  kerül a fájlba, ha érvényes GTIN-8/12/13/14 ellenőrzőszámmal; ilyenkor
  `ean_reconstructed` figyelmeztetést kap.
- **Tudományos jelölés hiányos mantisszával** (pl. `8,71999E+12`): **nem állítható vissza**,
  a számjegyek elvesztek. Az EAN üres marad, a sor `ean_unrecoverable` figyelmeztetést kap,
  és nincs kitalált számjegy.
- **XLS/XLSX számcella**, amely 15 jegynél hosszabb vagy tudományos formátumú
  (`uncertain_identifier`): `ean_unrecoverable`.
- **Érvénytelen ellenőrzőszámú vagy hosszú számsor:** változatlanul kerül a fájlba, és
  `invalid_gtin` figyelmeztetést kap. Ez a forrás adata, nem kitalált érték.

## Végpontok

Előtag: `/api/v1/imports`.

### 1. Előnézet – `GET /import-templates/{id}/result?run_id=&offset=0&limit=50`

- Az `id` egy sablonverzió azonosítója; bármelyik, régebbi verzió is használható.
- A `run_id` alapból a sablon forrásfutása; bármely, a sablon beszállítójához tartozó futás
  megadható. A forrásfájlnak elérhetőnek kell lennie; különben 409.
- A `limit` legfeljebb 200.

```json
{
  "template": {"id": 41, "name": "Alap", "version": 3, "currency": "HUF",
               "engine": "unas"},
  "run_id": 12,
  "columns": [
    {"header": "Cikkszám", "target": {"key": "cikkszam"}, "source_columns": [0]},
    {"header": "Bruttó Ár", "target": {"key": "brutto_ar"}, "source_columns": [],
     "computed": true},
    {"header": "Státusz", "target": {"key": "statusz"}, "source_columns": [],
     "default": "1"}
  ],
  "rows": [
    {"line": 2, "values": ["A-1", "1270", "1"], "status": "ok",
     "errors": [], "warnings": []},
    {"line": 3, "values": ["", "", "1"], "status": "error",
     "errors": [{"code": "missing_sku"}],
     "warnings": [{"code": "missing_price"}]}
  ],
  "offset": 0, "limit": 50, "total": 3,
  "summary": {"rows": 3, "exportable": 2, "excluded": 1,
              "errors": {"missing_sku": 1},
              "warnings": {"missing_price": 1, "ean_unrecoverable": 1}},
  "excluded_columns": [{"header": "Raktárkészlet #1", "source_columns": [9],
                        "code": "undocumented_header_excluded"}],
  "missing_source_columns": []
}
```

- A `values` a `columns` sorrendjét követi.
- A sor `status` mezője `ok`, `warning` vagy `error`; `error`-sor nem kerül a letöltött
  fájlba.
- A `missing_source_columns` azokat a sablonoszlopokat sorolja fel, amelyek ebből a fájlból
  hiányoznak. A hozzárendelés fejléc és előfordulás szerint történik, ahogy a sablon-
  felismerésnél.
- A `summary` a teljes fájlra vonatkozik, nem csak az aktuális oldalra.

### 2. Letöltés – `GET /import-templates/{id}/result.xlsx?run_id=` és `…/result.csv?run_id=`

- **Tartalom:** az előnézet oszlopai és a `status != "error"` sorai, a fejléc a technikai UNAS-
  fejléc.
- **XLSX:** egy munkalap, minden cella szöveg, így az EAN és a vezető nullák biztonságban
  vannak.
- **CSV:** UTF-8 BOM-mal, `;` elválasztóval, minden mező szövegként.
- **Fájlnév:** `UNAS_<sablonnév>_v<verzió>_<run_id>.<xlsx|csv>`.
- **Fejlécek:**
  - `X-Exported-Rows`, `X-Excluded-Rows`;
  - `Content-Disposition: attachment`.
- **Audit:** `import.template_result_download` (sablon, verzió, futás, formátum, sorszámok).

### 3. Újragenerálás sablonmódosítás után

Nincs külön végpont. A sablon módosítása új verziót hoz létre (TEMPLATE-PREP-01), és az új
verzió azonosítójával az 1. és 2. végpont az új szabályokkal állítja elő az eredményt. A
régi verzió azonosítójával a régi eredmény továbbra is előáll. Termékimport és AI nem indul.

## Importálhatóság

- A teszt a letöltött XLSX-et visszaolvassa a meglévő UNAS-exportolvasóval
  (`app.reference_products`). Ellenőrzi, hogy minden fejléc ismert UNAS-oszlop vagy
  paraméter, és hogy a cikkszám, az EAN, a kategória és a paraméterek változatlanul
  visszajönnek.
- A sablonon kívüli, nem dokumentált oszlop nem kerül a fájlba.

## Nyitott kérdések (Tulajdonos/Vezér)

1. **Több kép (rendezve):** a formátum `|` elválasztó egyetlen `Kép link` cellában, a
   főkép elöl. Két, egymástól független forrás igazolja:
   - a valós UNAS-export, ahol egy termék értéke `…/shop_pic/1000842.jpg|…/shop_altpic/1000842_altpic_1.jpg|…/shop_altpic/1000842_altpic_2.jpg`;
   - az UNAS súgójának (Termék adatbázis, Termék képek) keresőkivonata.

   Az `unas.hu` oldalt a fejlesztői környezetből közvetlenül nem lehetett letölteni. Nyitott
   technikai kérdések:
   - a 10 képes korlát csak a kivonatból ismert;
   - a kivonat szerint a `Kép link` csak kép nélküli terméknél tölt fel képet, ütemezve;
   - üres képoszlopnál a rést nem lehet jelölni.

   Mindhármat a valós UAT-import igazolja.
2. **Raktárkészlet #1…:** a többraktáras fejléc nem igazolt, ezért kimarad.
3. **CSV-formátum:** UTF-8 BOM és `;` elválasztó; az UNAS CSV-importjának pontos elvárását a
   valós importteszt igazolja (UAT).
4. **Bruttó ár kerekítése:** 2 tizedes. Ha HUF-nál egészre kell kerekíteni, az üzleti döntés.

## A frontend teendői (Codex)

- **Sablon mentése után:** „Eredmény” nézet a sablonverzióval és a futással, lapozható
  táblázat (oszlopnevek, értékek, soronkénti hibák és figyelmeztetések), és összesítés a
  `summary` alapján.
- **Kimaradó adatok:** a kimaradó oszlopok (`excluded_columns`) és a hiányzó forrásoszlopok
  (`missing_source_columns`) jelzése.
- **Letöltés:** XLSX- és CSV-gomb.
- **Régebbi verzió:** választható, és az eredmény újragenerálható vele.
