# CODEX 05 – Ellenőrzött paraméter-hozzárendelések

## Eredmény és hatókör

Az átadott 2669 soros kategóriaexporton, helyi adminisztrátori felülbírálások nélkül:

| Ellenőrzés | Eredmény |
|---|---:|
| Magyar főcsoport | 13, változatlan sorrendben |
| Rögzített navigációs pont | 583 |
| Szülő–gyermek kapcsolat | 570 |
| Legnagyobb mélység | 4 |
| Strukturális/navigációs pont | 171 |
| Termékkategória paraméterkészlettel | 412 / 412 |
| Külön profilokat használó termékkategória | 18 |
| Paraméterprofil-hozzárendelés | 503 |
| Különböző forráskategória | 467 |
| Bizonytalan vagy hiányzó automatikus hozzárendelés | 0 |

A 133 korábban hiányzó/bizonytalan kapcsolat mellett 7, üres paraméterkészletű gyűjtőpontra mutató kapcsolatot is felülvizsgáltunk. A további 273 korábbi pozitív kapcsolat ellenőrzése 6 téves névegyezést javított: telefon-/fotótartozékok, tablet-töltők és -kábelek, autóakkumulátorok és gyermektrambulinok. Az összes megmaradó 412 termékkategória forrása rögzített, ellenőrzött szabályból származik.

A felhasználó kifejezett kérésére a **TV antennák és kiegészítők** (`web-item-43-3550`) pont megszűnt; törlési jelölése a definícióban megmarad. Ez az egyetlen változás a korábban jóváhagyott fa szerkezetében (584 → 583 pont). A többi név, azonosító, szülőkapcsolat és sorrend változatlan. A forrásadatbázisban nem törlünk kategóriát.

## Paraméterek és külön profilok

| Fix kategória | Forrás | Paraméterszám az exportban |
|---|---|---:|
| Szabadonálló mosogatógépek | Mosogatógépek (411) | 36 |
| Robotgépek | Konyhai robotgépek (34) | 23 |
| Elektromos grillsütők | Kontakt grillek (292) | 17 |
| Monitorok | LCD & LED monitorok (5) | 39 |
| Asztali számítógépek | Asztali számítógép (6) | 70 |
| Televíziók | Televíziók (79) | 46 |

A tágabb fix kategóriáknál a felhasználó kérésére minden releváns profil **külön választható**. Például a Töltőkábelek alatt a töltők (2780) és az adat-/USB-kábelek (2782) külön profilt kapnak. A lámpák és asztalok külön termékkörei sem egyesített paraméterlistát használnak. Profilváltáskor a profil saját kötelező/opcionális jelölései és megengedett értékei jelennek meg; ezek nem öröklődnek és nem mosódnak össze.

A `navigation/{node}/parameters` végpont a `profile_emag_id` lekérdezési paraméterrel választ profilt. Több profil esetén választás nélkül, illetve idegen profil megadásakor 409 választ ad. A felület automatikusan megnyitja az első profilt, és választót ad a többihez. A fix kategóriaazonosság nem változik a profil kiválasztásától.

## Biztonság és felülbírálás

A `backend/reference_data/reviewed_parameter_bindings.json` szabályai a fix teljes útvonalhoz és azonosítóhoz rendelik a valódi Marketplace-forrásazonosítókat, elvárt forrásneveket, eredeti forrásútvonalakat és az archivált menühivatkozást. A menüazonosítók nem válnak Marketplace-azonosítóvá. A futás során a név és forrásazonosító ellenőrzése megmarad; hiányzó/átnevezett forrás figyelmeztetést eredményez, nem egy más termékkörű névrokon automatikus behelyettesítését.

Az `is_allowed` nem változtat a rögzített fán vagy a profilok kiválasztásán. A strukturális gyűjtőpontokhoz nem kell paraméterforrás. Új forráskategória nem kerül automatikusan a fix fába.

A korábbi adminisztrátori hozzárendelés vagy visszavonás elsőbbséget élvez. Emiatt a VPS tényleges számlálói eltérhetnek az offline jelentéstől. Az egységes szerkesztőben az automatikus hozzárendelés visszaállítása visszahozza a felülvizsgált profilokat; kézi egyprofilos választás ezeket felülírja.

**Nincs új migráció, újraimport, új katalógusverzió vagy aktiválás.** A már betöltött katalógus forráskapcsolatait és paraméter-/értéktábláit olvassuk. A 2 847 054 betöltött értékrekordhoz és a `pinfo_db` adatbázishoz nem írunk. A kézi szerkesztő csak a saját felülbírálást és auditbejegyzést menti. A Compose, `.env` és VPS-konfiguráció változatlan.

## Reprodukálható ellenőrzés

A részletes, kategóriánkénti eredmény: [reviewed-parameter-profiles.json](reports/reviewed-parameter-profiles.json). A TSV 29 398 paraméterkapcsolat összesített számát tartalmazza; a teljes értékállomány nincs a helyi exportban. A valódi értékek tartalmát ezért helyben nem állítjuk ellenőrzöttnek.

```bash
.venv/bin/python scripts/report_fixed_categories.py \
  --export backend/tests/fixtures/emag_categories_export.tsv \
  --output /tmp/reviewed-profiles.json
PYTHONPATH=backend .venv/bin/pytest -q backend/tests scripts/tests
npm --prefix frontend run build
```

A tesztek az export alapú lefedettséget, a hiányzó forrás biztonságos kezelését, a külön profilok kötelező jelöléseit és értéktartományait, a kézi felülbírálást/visszaállítást, valamint az adatbázis-rekordok változatlanságát vizsgálják. Asztali és mobil böngészőtesztek ellenőrzik a profilváltást saját katalógus és korábbi referenciaelérés mellett is. A paraméter-/értékadatok tesztmintái szintetikusak; éles import vagy VPS-művelet nem történt.

Ellenőrzési eredmény: **144 sikeres teszt** a teljes backend/scripts csomagban, továbbá a végső profilszámláló-pontosítás után **4 sikeres célzott profilteszt**. A frontend TypeScript/Vite build és a módosított Python-fájlok Ruff-ellenőrzése sikeres. Egy külső Starlette/AnyIO elavulási figyelmeztetés jelent meg; teszthiba nem volt.
