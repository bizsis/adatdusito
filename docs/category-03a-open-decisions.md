# CATEGORY-03A – Nyitott üzleti kérdések: döntésre előkészített bizonyítéklista

A #20/#25 nyitott kérdései kérdésenként. Mindegyiknél leírjuk a bizonyítékot, a hiányzó bizonyítékot és a 03A jelenlegi, **konzervatív** viselkedését. Programozói jóváhagyás egyik kérdésben sincs. A döntést a Vezér vagy a Tulajdonos hozza meg, külön PR-ban.

Források:
- verziózott kategóriaexport: `backend/tests/fixtures/emag_categories_export.tsv`, SHA-256 `053a18a2…`;
- `backend/reference_data/reviewed_parameter_bindings.json`;
- `backend/reference_data/donor_review.json`.

A paraméternevek összevetéséhez csak olvasó `pinfo_db` SQL kell. Mintája a `docs/category-457-status.md`-ben van.

## 1. A 3 `pending_review` donor

| Menüpont | Donor (param.) | Rokon kategória az exportban | Hiányzó bizonyíték |
|---|---|---|---|
| Mosó-szárítógépek `web-item-114-3492` | 385 Mosógépek (45) | 673 Szárítógépek (31), ugyanazon szülő (3967) alatt | lefedi-e a 385 a szárítási paramétereket (kapacitás, program) |
| Robotporszívók `web-item-114-3820` | 58 Porszívók (27) | nincs külön kategória | robot-specifikus paraméterek (navigáció, üzemidő, dokkoló) |
| IPL `web-item-83-4339` | 63 Epilátorok (26) | nincs külön kategória | fényimpulzusos technológia paraméterei |

**03A viselkedés:** `parameter_profile_state = pending_review`. Csak `src:` helyek keletkeznek (`donor_not_ready`), `emag:` hely, paraméterhely-kiegészítés és alias-alkalmazás nincs. Kézi donorválasztással sem nyílik meg a dúsítási kapu.

**Döntési lehetőségek:**
- (a) jóváhagyás: a bejegyzés törlése a `donor_review.json`-ból;
- (b) más vagy további donor: a `reviewed_parameter_bindings.json` módosítása, pl. a 673 külön profilként;
- (c) donor nélkül marad.

## 2. Főzőedények: lefedetlen termékkörök

- A szabály 4 profilja: 146 Serpenyő (21), 147 Fazekak és lábasok (20), 1606 Hőálló edények (21), 2664 Multifunkciós főzőedények (21).
- Az exportban ugyanazon szülő (1603) alatt van még: 1604 **Főzőedény fedők** (13), 1843 **Kotyogós kávéfőzők** (13), 3619 Főzőedények (**0** paraméter).

**03A viselkedés:** többprofilos, ezért `choice_required`. Kifejezett profilválasztás nélkül nincs `emag:` hely. Fedő vagy kotyogós termék esetén a kezelő a négy profil egyikét sem kénytelen választani: a termék `src:` helyekkel, dúsítás nélkül marad.

**Döntés:** felvegyük-e a 1604-et és a 1843-at külön választható profilként? A 3619-es kategóriának nincs paramétere, ezért donornak nem alkalmas.

## 3. Dekorációk

- Profilok: 1567 Dekorációs kiegészítők (20), 3903 Fali dekorációk (13).

**03A viselkedés:** `choice_required`. A két profilon kívül eső termék kézi döntéssel, dúsítás nélkül kezelhető.

**Döntés:** elfogadható-e ez, vagy kell további profil? Ha igen, melyik eMAG-kategória legyen?

## 4. Kapszulás kávéfőzők és Okos izzók

| Menüpont | Jelenlegi donor | Alternatíva az exportban |
|---|---|---|
| Kapszulás kávéfőzők `web-item-114-3754` | 32 Eszpresszó kávéfőzők (29) | 104 Kávéfőzők (20), ugyanazon szülő (846) alatt |
| Okos izzók `web-item-173-4297` | 365 Izzók (25) | az okos eszközök kategóriái (pl. 3407, 32 paraméter) más termékkörűek |

**03A viselkedés:** a donor `reviewed`, ezért `ready`. Paraméterhely csak biztos egyezésnél töltődik (normalizált név vagy jóváhagyott alias), minden más `review`/`missing`/`src:`. Meglévő értéket nem ír felül.

**Döntés:** maradjon-e a jelenlegi donor, vagy kerüljön `pending_review`-ra (egy sor a `donor_review.json`-ban), amíg a paraméternevek összevetése meg nem történik?

## 5. `is_allowed = 0` (51 donor-hozzárendelés)

- A lista a `docs/reports/category-457-status.json` `donors_not_allowed_in_export` mezőjében van.
- A CODEX 05 döntése szerint ez a fát és a profilválasztást nem befolyásolja.

**03A viselkedés:** a paraméterhely-képzésnél nem számít, mert ez a fázis nem végez piactéri feltöltést.

**Döntés:** a jövőbeli feltöltési fázisban blokkoló vagy figyelmeztető legyen-e?

## 6. 2000-es szinkronhatár (kategóriatérkép)

Technikai alapérték (`product_jobs.SYNC_REAPPLY_LIMIT`). A váratlan futásidőket a háttérfeladat kezeli: bérlet, folytatás, `stalled` jelzés, CLI-folytatás. A paraméterfutás mindig háttérben fut. Termékszintű művelet csak egy terméket érint.
