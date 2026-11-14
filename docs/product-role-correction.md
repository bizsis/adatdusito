# Termékkategóriák strukturális besorolásának javítása

A régi szabály a forrásoldali `parameter_filter`, `collection`, `brand` stb. hivatkozástípust automatikusan strukturális szereppé alakította. Emellett néhány konkrét termékkör `section` típusú volt. A jóváhagyott termékfogalmat most explicit `role: product` jelöli, amely elsőbbséget élvez az archivált URL típusával szemben.

A 13 főcsoport, az 583 pont neve és azonosítója, az összes szülőkapcsolat és a sorrend változatlan. 45 korábbi navigációs pont lett termékkategória; összesen 457 termékkategória, 126 navigációs pont, 555 profil-hozzárendelés és 23 többprofilos kategória van az átadott exporton. Nincs hiányzó automatikus profil ezen a mintán; helyi adminisztrátori felülbírálások továbbra is elsőbbséget élveznek.

## Átminősített pontok

| Teljes kategóriaútvonal | Meglévő profilok (eMAG ID) |
|---|---|
| Háztartási gépek és klíma / Mosógépek és szárítógépek / Elöltöltős mosógépek | Mosógépek (385) |
| Háztartási gépek és klíma / Mosógépek és szárítógépek / Felültöltős mosógépek | Mosógépek (385) |
| Háztartási gépek és klíma / Mosógépek és szárítógépek / Mosó-szárítógépek | Mosógépek (385) |
| Háztartási gépek és klíma / Mosogatógépek / Keskeny mosogatógépek | Mosogatógépek (411) |
| Háztartási gépek és klíma / Páraelszívók | Páraelszívók (525) |
| Háztartási gépek és klíma / Beépíthető készülékek / Beépíthető mosogatógépek | Mosogatógépek (411) |
| Háztartási gépek és klíma / Beépíthető készülékek / Beépíthető mikrohullámú sütők | Mikrohullámú sütők (363) |
| Háztartási gépek és klíma / Porszívók és vasalók / Porzsákos porszívók | Porszívók (58) |
| Háztartási gépek és klíma / Porszívók és vasalók / Porzsák nélküli porszívók | Porszívók (58) |
| Háztartási gépek és klíma / Porszívók és vasalók / Álló porszívók | Porszívók (58) |
| Háztartási gépek és klíma / Porszívók és vasalók / Robotporszívók | Porszívók (58) |
| Háztartási gépek és klíma / Kávékészítés / Automata eszpresszó kávéfőzők | Eszpresszó kávéfőzők (32) |
| Háztartási gépek és klíma / Kávékészítés / Kapszulás kávéfőzők | Eszpresszó kávéfőzők (32) |
| TV és szórakozás / eBook olvasók és tartozékok | eBook olvasók (103), eBook olvasó tartozékok (313) |
| TV és szórakozás / Konzolok és játékok / Hordozható játékkonzolok | Hardver konzolok (152) |
| Telefon, Tablet, Laptop / Telefonok / Klasszikus mobiltelefonok | Mobiltelefonok (15) |
| Telefon, Tablet, Laptop / Laptopok / Laptopok Windows-szal | Laptop / Notebook (14) |
| Számítástechnika / Gaming / Gamer PC-k | Asztali számítógép (6) |
| Számítástechnika / Gaming / Gamer laptopok | Laptop / Notebook (14) |
| Számítástechnika / Gaming / Gamer monitorok | LCD & LED monitorok (5) |
| Számítástechnika / Gaming / Gamer billentyűzetek | Billentyűzetek (10) |
| Számítástechnika / Gaming / Gamer egérpad | Egérpad (54) |
| Számítástechnika / Gaming / Gamer egér | Egér (11) |
| Fotó-Videó, Okos eszközök / Okosórák / Android kompatibilis okosórák | Okosórák (2920) |
| Fotó-Videó, Okos eszközök / Okosórák / iOS kompatibilis okosórák | Okosórák (2920) |
| Otthon, barkács, kert / Világítás és elektronika / Okos izzók | Izzók (365) |
| Otthon, barkács, kert / Dekorációk | Dekorációs kiegészítők (1567), Fali dekorációk (3903) |
| Otthon, barkács, kert / Konyha és felszolgálás / Főzőedények | Serpenyő (146), Fazekak és lábasok (147), Hőálló edények (1606), Multifunkciós főzőedények (2664) |
| Otthon, barkács, kert / Konyha és felszolgálás / Vízszűrő kancsók és tartozékok | Vízszűrő kancsók (520), Vízszűrő kancsó tartozékok (3674) |
| Játékok, Baba, Mama / BABA-MAMA / Babakocsik és hordozók | Babakocsik és tartozékok (1359), Babahordozó eszközök (3257) |
| Játékok, Baba, Mama / BABA-MAMA / Babajátékok / Interaktív babajátékok | Interaktív babajátékok (3290) |
| Játékok, Baba, Mama / BABA-MAMA / Babajátékok / Tevékenységi központok és játszószőnyegek | Baba tevékenységi játékközpont (3278) |
| Játékok, Baba, Mama / JÁTÉKOK / Társasjátékok / Gyerek társasjátékok | Társasjátékok (1209) |
| Játékok, Baba, Mama / JÁTÉKOK / Társasjátékok / Családi társasjátékok | Társasjátékok (1209) |
| Játékok, Baba, Mama / JÁTÉKOK / Társasjátékok / Felnőtt társasjátékok | Társasjátékok (1209) |
| Játékok, Baba, Mama / JÁTÉKOK / LEGO felnőtteknek | Építőkészletek (1187) |
| Szépségápolás / Parfümök | Parfüm (1241) |
| Szépségápolás / Szépségápolási készülékek / IPL tartós szőrtelenítők | Epilátorok (63) |
| Sport és utazás / Kerékpározás / Felnőtt kerékpárok | Kerékpárok (1809) |
| Sport és utazás / Kerékpározás / Gyerek kerékpárok | Kerékpárok (1809) |
| Könyvek, Filmek és Irodaszerek / Filmek, zene / Bakelit lemezek | Hanglemezek és zenei CD-k (604) |
| Könyvek, Filmek és Irodaszerek / Írás és rajzolás / Füzetek | Füzetek (2606) |
| Autó- és motor felszerelések / Gumiabroncsok / Nyári gumik | Gumiabroncsok (1412) |
| Autó- és motor felszerelések / Gumiabroncsok / Téli gumik | Gumiabroncsok (1412) |
| Autó- és motor felszerelések / Gumiabroncsok / Négyévszakos | Gumiabroncsok (1412) |

## Mosógépmegkötések

Az Elöltöltős mosógépek, Felültöltős mosógépek és Mosó-szárítógépek a 385-ös Mosógépek profilt használják (45 paraméter az átadott összesítésben). A betöltési típus paraméterének megléte esetén a paraméterválasz `category_constraint` mezője az első két kategóriához `equals / Elöltöltős`, illetve `equals / Felültöltős` feltételt ad. A felület megjeleníti a megkötést. Nem hozunk létre hiányzó paramétert vagy forrásérték-azonosítót; a típusfelismerés ismert, normalizált paraméterneveken történik. Mosó-szárítógéphez nem feltételezünk betöltési módot.

Ez kategóriaspecifikus metaadat: a megengedett forrásértékek teljes listája és a kötelező jelölések megmaradnak. Termékimport nincs ebben a fázisban; a későbbi értékellenőrzésnek a megkötést is figyelembe kell vennie. A valódi paraméterdefiníciók nincsenek a helyi TSV-ben, ezért a konkrét VPS-beli betöltéstípus-paraméter jelenlétét nem állítjuk ellenőrzöttnek. A feltételes API-viselkedést mindkét adatforrás-elérési módban szintetikus mintán ellenőriztük.

## A többi navigációs pont

Minden korábban strukturális pontot felülvizsgáltunk. A főcsoportok, gyűjtőpontok és bolttémák navigációként maradtak: például Mosógépek és szárítógépek, Konyhai kisgépek, Online könyvesbolt, Sportbolt. A teljes megmaradó lista: [retained-navigation-points.json](reports/retained-navigation-points.json). Az átminősített pontok gépi listája: [reclassified-products.json](reports/reclassified-products.json).

Nincs migráció, újraimport, aktiválás vagy VPS-művelet. Az eredeti `pinfo_db` és a betöltött paraméterértékek változatlanok. A meglévő adatverziót használó futásidejű nézet alkalmazza az új szerepeket és profilokat.

## Ellenőrzés

149 teszt sikeres a teljes backend/scripts csomagban; ezek között saját katalóguson és közvetlen referenciaelérésen is ellenőrzött a mosógép-kiválasztás, a feltételes betöltési megkötés és az értékrekordok változatlansága. Asztali és mobil böngészőtesztek, frontend TypeScript/Vite build, Ruff és `git diff --check` sikeresek. Egy külső Starlette/AnyIO elavulási figyelmeztetés maradt. A Gitben tárolt korábbi definícióval külön összevetettük mind az 583 azonosítót, nevet, szülőt és sorrendet: egyeznek.

Részletes új lefedettség: [product-role-coverage.json](reports/product-role-coverage.json).
