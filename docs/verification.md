# Telepítési összefoglaló és ellenőrzési jegyzőkönyv

Dátum: 2026-11-13 (Europe/Budapest).
Helyszín: izolált Codex felhőkörnyezet, nem a VPS.

| Ellenőrzés | Eredmény |
| --- | --- |
| Backend pytest | 4 sikeres teszt; 1 függőségi deprecation warning |
| TypeScript + Vite build | Sikeres |
| Frontend production npm audit | 0 ismert sérülékenység a vizsgált függőségekben |
| Backend és frontend Docker build, TLS-ellenőrzéssel | Sikeres |
| Compose-konfiguráció | Érvényes |
| MySQL 8.0 izolált próba | Sikeres, kizárólag üres, mesterséges referenciatáblákkal |
| Alembic baseline | Sikeres, verzió: 0001 |
| Referenciafelhasználó SHOW GRANTS ellenőrzése | Csak SELECT és USAGE a helyi próbakörnyezetben |
| Frontend HTTP, liveness, readiness | HTTP 200; mind a négy readiness-ellenőrzés sikeres |
| Celery feladat Redis-en át | infra.ping eredménye pong |
| Ismételt felhőbeli indítás | Sikeres |
| VPS SSH | A 167.86.70.129:22 kapcsolat elutasítva |
| VPS szolgáltatás-/MySQL-/Nginx-felmérés | Hozzáférés hiányában nem történt meg |
| dev.pinfo.hu HTTPS és Let's Encrypt | Előkészített konfiguráció; nincs telepítve vagy ellenőrizve |
| Valódi pinfo_db olvasás | Hozzáférés hiányában nem ellenőrizhető |

Az integráció során javítva: Alembic Python-útvonal, a nem root frontend fájljogai,
a közös backend-image neve és a tesztadatbázis TCP-alapú indulási ellenőrzése.
A tesztadatbázis folyamatának átmeneti újraindítása alatt egy korai diagnosztikai kérés
kapcsolati hibát adott; az új indítás befejezése után a jogosultság-ellenőrzés sikeres.

A VPS-en nem történt változtatás. A meglévő MySQL, pinfo_db és pinfo.hu érintetlen.
Az éles környezet nincs telepítve. A váz nem tartalmaz üzleti funkciókat vagy hitelesítést.
A backendtesztekben a readiness hibás és sikeres útvonala mockolt; a külön Compose smoke
ellenőrzés valódi MySQL-, Redis- és Celery-kapcsolatot használt.

Következő lépés: működő, hostkulccsal ellenőrzött SSH-kapcsolat és biztonságosan
beállított hitelesítés; utána a docs/deployment.md szerinti felmérés és fejlesztői telepítés.
Meglévő szolgáltatás konfigurációjának átírása vagy reload előtt konkrét jóváhagyás szükséges.
