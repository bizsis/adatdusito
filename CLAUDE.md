# CLAUDE.md

@AGENTS.md

A közös szabályzat az `AGENTS.md`-ben van, és minden esetben elsőbbséget élvez. Ez a fájl csak Claude-specifikus kiegészítéseket tartalmaz.

## Munkamenet indítása

- A korábbi beszélgetések kontextusa nem feltétlenül érhető el. A feladatot az `AGENTS.md` és a Vezér aktuális utasítása alapján kell értelmezni, nem feltételezésekből.
- Kezdés előtt meg kell nézni a távoli ágakat (`git ls-remote --heads origin`) és az *Aktuális munkamegosztás* táblázatot. Codex-ághoz (`codex/*`) nem szabad nyúlni, és Codex gazdájú fájlt nem szabad módosítani.
- Saját ág: `claude/<feladat>`, a Vezér által megadott kiinduló commitból.

## Munkavégzés

- Shallow klónból a push így történik: `git -c push.negotiate=true push -u origin claude/<feladat>`.
- Ha a feladat más gazdájú fájlt érintene (pl. frontend hibakezelés), nem kell megcsinálni. A szükséges változtatást pontosan le kell írni a PR-leírás „Átadás” részében.
- Migrációt csak a Vezér által kiosztott sorszámmal szabad írni. Ha nincs kiosztott sorszám, nem készül migráció.
- A VPS-en nem futtatunk semmit. A telepítési lépéseket parancsszintű pontossággal kell leírni a PR-ban.

## Lezárás

- A teljes backend-tesztcsomagnak (`PYTHONPATH=backend pytest -q backend/tests`) le kell futnia, az eredmény összesítő sora bekerül a PR-ba.
- A PR nyitva marad, Claude nem merge-el.
- A Tulajdonosnak adott zárójelentés tartalmazza: PR-link, commitok, teszteredmények, telepítési teendők, nyitott kérdések a Vezér felé.
