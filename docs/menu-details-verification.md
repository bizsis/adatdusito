# Részletes menüexport ellenőrzése – 2026-11-13

A Windowsról átadott, 15:19:44 UTC időpontban indított kézi export forrása a `https://www.emag.hu/homepage`. A csatolmány adatait offline dolgoztuk fel; nem utasításként és nem futtatható tartalomként. A két ZIP-tag kizárólag nyilvános navigációs DOM-metaadatot és kategóriaazonosító-bizonyítékot tartalmaz. A 31 834 bájtos eredeti csomag reprodukálható tesztadatként a `backend/tests/fixtures/emag-menu-details.zip` fájlban szerepel.

- ZIP SHA-256: `e21a749de8e9d596cfff5da33c6f70d11f5b1afa7cc1fc4d469d41a693a80938`
- JSON SHA-256: `f8388cef58a799b27f70049521fe6f784efc49b30d4f14dd76c21c61eb04e05f`; egyezik a csomag manifestjével.
- Gyűjtési hiba: 0. Menü-JSON hálózati válasz: 0. Sikeres kategóriaoldal: 1.

## Pontos kapcsolatösszesítés

A 13 magyar főcsoport eredeti sorrendje megmaradt. A 623 menüelem mindegyikét a főcsoporton belüli webshop-menüazonosítóval, névvel és DOM-sorrenddel azonosítottuk. A szülőkapcsolatokat újraszámoltuk az ősök osztályaiból és az ugyanabban a panelben található fejlécazonosítókból; nem csak az export `verified_dom` állítását fogadtuk el.

| Kapcsolat | Darab |
| --- | ---: |
| Igazolt közvetlen főcsoport–menüelem kapcsolat | 129 |
| Igazolt szekció–gyermek kapcsolat | 415 |
| Összes igazolt menüelem-szülőkapcsolat | **544** |
| Továbbra is ellenőrzendő belső szülőkapcsolat | **79** |
| Összes vizsgált menüelem | **623** |
| Megváltozott szülőkapcsolat a korábbi fához képest | **0** |
| Újonnan igazolt Marketplace-megfeleltetés | **0** |

Mind a 623 elem ugyanazt a kapcsolatot/ellenőrzendő állapotot mutatja, mint az eredeti HTML-exportból felépített fa. Az új export ezért megerősítő bizonyíték: nem oldott fel újabb bizonytalan kapcsolatot. A 79 feloldhatatlan csoport elemét továbbra is csak a bizonyított főcsoport alatt, ellenőrzendő jelzéssel tartjuk elérhetően; ez nem állítás arról, hogy a teljes hierarchiában közvetlen gyermekek lennének. A koordinátákból és a nevek hasonlóságából nem következtetünk szülőre.

A 13 gyökérrel együtt **636 navigációs elem** található a forrásadatban. A tárolt navigáció 3 szintű (13 / 208 / 415 elem); ez a megfigyelt menü mélysége, és tartalmazza a bizonytalan elemek főcsoport alatti megjelenítési helyét is. Nem bizonyítja a teljes webshop-kategóriafa mélységét vagy teljességét. A 623 elem között kategóriák mellett márkák, kampányok és szűrők is vannak; nem állítunk 623 termékkategóriát. A kategóriaböngészőben továbbra is a 13 főcsoport, 99 strukturális szekció és 420 kategóriahivatkozás szerepel; a többi elem kapcsolódó hivatkozásként jelenik meg.

| Főcsoport | Elem | Igazolt | Ellenőrzendő |
| --- | ---: | ---: | ---: |
| Háztartási gépek és klíma | 55 | 49 | 6 |
| TV és szórakozás | 49 | 49 | 0 |
| Telefon, Tablet, Laptop | 45 | 42 | 3 |
| Számítástechnika | 48 | 45 | 3 |
| Fotó-Videó, Okos eszközök | 51 | 48 | 3 |
| Szupermarket | 47 | 39 | 8 |
| Otthon, barkács, kert | 56 | 45 | 11 |
| Játékok, Baba, Mama | 49 | 46 | 3 |
| Divat, ékszerek és kiegészítők | 51 | 46 | 5 |
| Szépségápolás | 49 | 41 | 8 |
| Sport és utazás | 45 | 32 | 13 |
| Könyvek, Filmek és Irodaszerek | 45 | 41 | 4 |
| Autó- és motor felszerelések | 33 | 21 | 12 |

## Paramétermegfeleltetés és közös rendszer

A televízió kategóriaoldal HTTP 200 státusszal érkezett, de üres breadcrumb-listával. A `script[1].categoryId` megfigyelt értéke **492**, és további sibling/menuItems azonosítók is szerepelnek. Névterük továbbra is `unverified`; ez nem igazolja a Marketplace **79** kategóriával való azonosságot. A webshop menüjében a Televíziók elem **3730**, a Könyvek főcsoport **79**. Egyik számból sem származtatunk automatikus paraméterkapcsolatot.

Az eredmény a már meglévő egyetlen közös `web_navigation.json` snapshotot egészíti ki elemenkénti bizonyítékkal és `details_verification` forrásösszesítéssel. A `/api/v1/reference/navigation/coverage` ezt az összesítést is visszaadja. Nincs külön forrásböngésző, második termékkategória-tábla vagy paramétermásolat. A későbbi Alza/eMAG forrásmegfigyeléseket ugyanazon közös kategóriaazonosságokhoz, bizonyított megfeleltetéssel kell kapcsolni; a forrásazonosító névtere megőrzendő. Ebben a módosításban Alza-import nem készült.

A navigációs snapshot eredeti `archive_sha256` értéke változatlan, mert az összes navigációs azonosság, URL és kapcsolat változatlan. A kiegészítő csomag saját hash-e külön mezőben szerepel: az új megerősítés önmagában nem érvényteleníti a korábban auditált, ugyanazon snapshothoz kötött operátori jóváhagyásokat. Új, automatikus jóváhagyás nincs.

## Reprodukálás

```bash
python scripts/process_emag_menu_details.py backend/tests/fixtures/emag-menu-details.zip \
  --navigation backend/reference_data/web_navigation.json \
  --output /tmp/verified-web-navigation.json
```

A feldolgozó kizárólag új kimeneti fájlt ír. Hibás hash, hiányzó/dupla elem, eltérő sorrend, nem igazolt DOM-szülő, névtérkeverés vagy a meglévő gráffal ütköző kapcsolat esetén elutasítja a csomagot. Ellentmondó forrást nem ír automatikusan a korábbi igazolt kapcsolat helyére.

A `pinfo_db`, `.env`, séma és migrációk, a Docker Compose external hálózat, VPS- és éles beállítások változatlanok. VPS-telepítés nem történt.
