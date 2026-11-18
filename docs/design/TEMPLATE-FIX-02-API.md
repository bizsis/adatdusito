# TEMPLATE-FIX-02 – Egyszerű paraméterek, teljes UNAS-célmezőlista, foglalt célmezők

A `docs/design/TEMPLATE-PREP-01-API.md` és a `docs/design/TEMPLATE-RESULT-01-API.md` frissítése.
Alapág: `codex/template-result-integration` (`2045b3a`), ág: `claude/template-fix-02-backend`.
A szerződés a backend előtt készült, a Codex számára. A meglévő végpontok, mezők és sablonok
változatlanok; minden itt leírt változás kiegészítés.

## 1. Paraméterek: elég a név

- Új paraméterhez a kezelőnek **csak a nevet** kell megadnia:
  `new_parameters: [{"name": "Szín", "approved": true}]`, illetve a célban
  `{"key": "parameter", "parameter": {"name": "Szín"}}`.
  - Típust, mértékegységet, értékkészletet vagy csoportot a felület nem kér.
  - A régi kliensek által küldött `param_type`/`group_name`/`unit` továbbra is elfogadott,
    így a régi sablonok nem sérülnek.
- **A `Paraméter:` előtag soha nem duplázódik.** Ha a kezelő a nevet előtaggal írja be
  (`Paraméter: Szín`), a szerver a `Szín` nevet tárolja.
- **Előtagos forrásoszlop:** a `Paraméter:`-rel kezdődő forrásoszlop automatikusan
  paraméterként rendelődik hozzá (`assignment_source: "auto"`, `method: "source_parameter"`),
  és ehhez nem kell külön jóváhagyás.
  - Ha a fejléc teljes UNAS-paraméterfejléc (`Paraméter: Szín||text|…`), az változatlanul
    megmarad.
  - Ha csak `Paraméter: Szín`, a név `Szín`.
- **A forrásértékek változatlanok.**
- **Megjelenítés:** minden válaszban, ahol paraméter szerepel, új **`label`** mező van, mindig
  `Paraméter: Név` alakban. A frontend ezt jeleníti meg:
  - előkészítés: `suggestion.target.label`, `approved_parameters[].label`,
    `occupied[].label`;
  - validálás: `resolved[].label`;
  - eredmény: `columns[].label`.

### ⚠️ Ellentmondás a dokumentált UNAS-importformátummal (tulajdonosi döntés kell)

- **Ami dokumentált:** az UNAS súgója (Termék adatbázis) szerint a paraméteroszlop fejléce
  **rögzített pozíciójú**: `Paraméter:név|csoport|típus|termék oldalon megjelenhet|…|export feedekben
  látható` (a súgó példája: `Paraméter: Szállítási idő|Szállítás|num|2|0|0|1|0|1|előtte|utána|0|1|1`).
  A valós UNAS-export is ilyen fejlécet használ (`Paraméter: Szélesség||num|1|0|0|0|0|0||cm|0|1|1`).
- **Ami nem igazolt:** hogy a rövid `Paraméter: Név` fejlécet az UNAS-import elfogadja, illetve
  hogy meglévő paraméterhez köti, nem pedig új, duplikált paramétert hoz létre.
- **Mit tesz most a backend:**
  - az **exportált fájl fejléce marad a dokumentált teljes formátum**; új paraméternél ez az
    eddigi alapértelmezett szöveges beállítás (`Paraméter: Név||text|1|0|1|0|0|0|||0|1|1`);
  - a **megjelenített** név mindenhol `Paraméter: Név` (`label`).
- **Javaslat:** egy próbaimporttal kell igazolni az UNAS-ban. Ha a Tulajdonos jóváhagyja a rövid
  fejlécet, a váltás egyetlen helyen történik (`template_result.export_header`).

## 2. Teljes UNAS-célmezőlista

- A `GET /template-targets` a jóváhagyott 33 célmező után (változatlan sorrendben és szabályokkal)
  felsorolja az összes **dokumentált és importálható** UNAS-oszlopot is, amely eddig hiányzott.
- **Forrás:** a meglévő UNAS-séma (`backend/app/unas_schema.py`: a valós UNAS-export oszlopai és
  az UNAS-súgókivonatok). Az `unas.hu` oldal a fejlesztői környezetből közvetlenül nem érhető el.
- **Az új mezők alakja:**
  - `label` = a technikai UNAS-fejléc, mert a kezelői elnevezéseket nem találjuk ki;
  - `group` a séma szerinti csoport;
  - `added_in: "template-fix-02"`;
  - forrásoszlop nélkül is a listában vannak.
- **Nem kerül be:**
  - a rendszer által generált oszlopok (`Létrehozás`, `Utolsó Módosítás`, `Termék link`);
  - az `Azonosító`, mert az importálhatósága nem igazolt;
  - a vevőcsoport-árak, mert áruházspecifikusak.
- **Új egyszerű célmezők (44):** Publikus időszak kezdete, Publikus időszak vége, Ár megjelenés,
  Automatikus kuponsablon, Link, Menny. kezdeti érték, Max. Menny., Vásárolható, ha nincs
  Raktáron, Változatokhoz Raktárkészlet, Alacsony készlet, Pont, Pontért megvehető, Mennyiségi
  kedvezmény, Szállítási mód tiltás, Szállítási mód engedélyezés, Plusz szállítási költség,
  Fizetési mód tiltás, Fizetési mód engedélyezés, Plusz kezelési költség, Plusz szolgáltatások,
  Plusz szolgáltatások működése, Export, Érdeklődjön Státusz, Ne legyen közvetlen kedvezmény,
  Csak ajándékként Státusz, Nincs a listában, Egyedi sorrend, Explicit, Letölthető tartalom,
  Matricák, Kiegészítő Kategóriák, Hasonló Kategóriák, Csomag termék, Kép kapcsolat, Altípus
  listában, Típus sorrend, SEF URL, Kép ALT/TITLE, Kép filenév, OG image, SEO Title,
  SEO Description, SEO Keywords, SEO Robots.
- **Új többszörözhető célmezők** (`multiple: "instances"`, a sorszám csak a valós exportban látott
  tartományban: `min_instance`…`max_instance`):

  | Célmező | Fejléc | Sorszám |
  |---|---|---|
  | `tartalmi_elemek` | `Tartalmi elemek {n}` | 1–3 |
  | `adat` | `Adat {n}` | 1–3 |
  | `statusz_n` | `Státusz {n}` | 1–3 |
  | `crosssale` | `CrossSale{n}` | 1–3 |
  | `upsale` | `UpSale{n}` | 1–2 |
  | `valaszthato_tulajdonsag` | `Választható Tulajdonság {n}` | 1–3 |
  | `tovabbi_lapful_cime` | `További lapfül címe {n}` | 1–3 |

  A `További lapfül tartalma 1–3` továbbra is a már elfogadott `lapful_1…3`.
- Minden célmező kap `min_instance`/`max_instance` mezőt, ha többszörözhető. A meglévőké:
  - Alternatív kategória: 1–99;
  - Raktárkészlet: 0–99.
- **Exportban** az új mezők értéke változtatás nélkül, szövegként kerül a fájlba (nincs
  átalakítás).

## 3. Foglalt célmezők

- Új mező az **előkészítési nézetben** (`GET /runs/{id}/template-preparation`) és a
  **validálás válaszában** (`POST …/template-preparation/validate`):

  ```json
  "occupied": [
    {"slot": "cikkszam", "key": "cikkszam", "columns": [0], "label": "Cikkszám",
     "multiple": null},
    {"slot": "raktarkeszlet#1", "key": "raktarkeszlet", "instance": 1, "columns": [9],
     "label": "Raktárkészlet #1", "multiple": "instances"},
    {"slot": "parameter:Szín", "key": "parameter", "columns": [4],
     "label": "Paraméter: Szín", "multiple": "instances"}
  ]
  ```

- A **nézetben** a betöltött, illetve automatikus hozzárendelések alapján jön létre; a
  **validálásban** a beküldött állapotból.
- Ha egy hozzárendelést törölnek, a következő validálás már nem sorolja fel a célt: az
  újra szabad.
- Egy nem többszörözhető célmező továbbra is csak egy oszlopot fogadhat (`duplicate_target`).
  Ez alól a Kép (`ordered`) és a többszörözhető célmezők kivételek.

## 4. Export

- Változatlanok:
  - a Státusz-, ÁFA-, ár- és képszabályok;
  - a CSV/XLSX-letöltés.
- Új: az eredmény oszlopainál a `label` (paraméternél `Paraméter: Név`).
- Az exportfájl paraméterfejléce a dokumentált teljes formátum marad (lásd az 1. pontot).
- Sem a sablonmentés, sem az export nem indít termékimportot vagy AI-feldolgozást.

## A frontend teendői (Codex)

- **Új paraméter:** a párbeszédablak csak a nevet kéri; a típus- és mértékegység-mezők
  elhagyhatók.
- **Megjelenítés:** paraméternél mindenhol a `label` jelenik meg (`Paraméter: Név`), a
  technikai fejléc nem.
- **Célmezőválasztó:** a teljes `targets` lista, a `min_instance`/`max_instance` szerinti
  sorszámokkal.
- **Foglaltság:** a foglalt, nem többszörözhető célmezők az `occupied` alapján tilthatók vagy
  jelölhetők. Törlés után a validálás frissíti a listát.
