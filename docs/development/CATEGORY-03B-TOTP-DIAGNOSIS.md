# CATEGORY-03B CI – TOTP időablak-diagnózis

Forrás: [tulajdonosi utasítás](https://github.com/bizsis/adatdusito/pull/27#issuecomment-6918070142).
Érintett frontend commit: `ad297a4`; PR #27, base #22 változatlan.
Hibás hosted futás: [43777023547 / backend](https://github.com/bizsis/adatdusito/actions/runs/43777023547/job/133005516776).

## A megfigyelt hiba

A tulajdonos által átadott, titokmentes naplókivonat:

```text
FAILED backend/tests/test_auth09.py::test_totp_and_recovery_single_use_no_full_session_before_second_factor
backend/tests/test_auth09.py:285: AssertionError
assert 200 == 403
1 failed, 388 passed, 2 warnings in 330.85s
```

A backend-, hitelesítési és biztonsági tesztfájlok változatlanok. A 403-as
elvárást nem gyengítettük. A diagnosztika kizárólag helyi, izolált FastAPI/SQLite
fixture-öket használt; nincs valódi fiók, VPS-, referenciaadatbázis- vagy
MySQL-művelet. A használt ideiglenes pytest plugin nem része a CI-nek és a
produkciós kódnak. MFA token, TOTP titok, kód és recovery kód nem része a jelentésnek.

## Mi változik az időablak határán?

Az `enroll()` segéd az aktiváláshoz `pyotp.TOTP(secret).now()` értéket küld.
A 285. sornál a teszt újra `.now()`-t hív, a korábban elküldött kódot nem tárolja.
Ha a két hívás között eltelik a 30 másodperces számláló határa, a második hívás
az új számlálóhoz tartozó **másik** kódot adhatja. Ennek 200-as elfogadása önmagában
nem a korábban elfogyasztott kód újrafelhasználásának bizonyítéka.

A backend `confirm_totp()` menti az elfogadott számlálót. A `verify_factor()` csak
`step > device.last_counter` mellett fogad el TOTP-egyezést. Az alábbi vizsgálat
az időzítés által érintett konkrét esetet ellenőrizte, nem teljes biztonsági audit.

## Célzott eredmények a változatlan ad297a4 állapoton

| Vizsgálat | Eredmény |
|---|---|
| Az eredeti teszt 6 külön pytest-folyamatban, valódi órával | 6/6 sikeres |
| Az eredeti teszt azonos, rögzített TOTP-időablakban | 1 sikeres |
| Az eredeti teszt: első `.now()` az ablak 29. másodpercében, második `.now()` a következő ablak elején | Várt diagnosztikai bukás a 285. soron; a hosted hibapont reprodukálva |
| Az aktiváláskor küldött **azonos, eltárolt kód** újraküldése +0 másodpercnél | HTTP 403; mentett számláló változatlan |
| Ugyanazon kód újraküldése +1 / +30 / +60 másodpercnél | Mindhárom esetben HTTP 403; mentett számláló változatlan |
| A három későbbi időpontban az új, eltérő aktuális kód | HTTP 200; számláló előrelép |

Az utolsó négy eset külön parametrizált, tényleges HTTP-kéréseket és SQLite
állapotellenőrzést tartalmazó ideiglenes teszt volt: **4 passed**. A szándékosan
előidézett eredeti tesztbukás diagnosztikai reprodukció, nem sikeres regressziós
tesztként elszámolt eredmény. A rögzített óra kizárólag a diagnosztikai folyamatban
helyettesítette a TOTP-generálás és a két backendmodul időforrását.

A korábbi teljes helyi ellenőrzések ugyanazon frontend commiton:

- #22 backenddel: **389 passed** (300,25 s).
- #26 / `c05746d` közös tesztágon: **410 backend/eszköz**, **134 böngésző**,
  **14 menüexport** sikeres; frontend lint/TS/build és Docker sikeres.
- A hibás hosted futásban a böngésző-, frontend-, Docker- és menüexportfeladat
  sikeres; a backend és az összesítő CI sikertelen. Ezt nem nevezzük zöld CI-nek.

## A határhelyzet reprodukálása backendfájl módosítása nélkül

A repó gyökerében, a projekt függőségeit tartalmazó virtuális környezettel:

```bash
mkdir -p /tmp/category03b-totp-diagnostic
cat > /tmp/category03b-totp-diagnostic/totp_clock_diagnostic.py <<'PY'
from types import SimpleNamespace
import os
import pytest

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    import pyotp
    from app import auth_api, auth_service
    state = {"time": 1800000029, "calls": 0}
    def now(self):
        state["calls"] += 1
        if os.environ.get("TOTP_DIAGNOSTIC_MODE") == "rollover" and state["calls"] == 2:
            state["time"] += 1
        return self.at(state["time"])
    monkeypatch.setattr(auth_api, "time", SimpleNamespace(time=lambda: state["time"]))
    monkeypatch.setattr(auth_service, "time", SimpleNamespace(time=lambda: state["time"]))
    monkeypatch.setattr(pyotp.TOTP, "now", now)
PY
TOTP_DIAGNOSTIC_MODE=stable PYTHONPATH=backend:/tmp/category03b-totp-diagnostic \
  .venv/bin/python -m pytest -q --tb=line -p totp_clock_diagnostic \
  backend/tests/test_auth09.py::test_totp_and_recovery_single_use_no_full_session_before_second_factor
TOTP_DIAGNOSTIC_MODE=rollover PYTHONPATH=backend:/tmp/category03b-totp-diagnostic \
  .venv/bin/python -m pytest -q --tb=line -p totp_clock_diagnostic \
  backend/tests/test_auth09.py::test_totp_and_recovery_single_use_no_full_session_before_second_factor
```

A `stable` esetnek sikerülnie, a `rollover` esetnek a megadott hibaponton buknia
kell. Ez diagnosztikai parancs, nem a normál CI tesztparancsa. A kódokat és
kérésbodykat tartalmazó részletes hibakimenetet ne másoljuk nyilvános jelentésbe.

## Átadás Claude-nak és CI

Az érintett teszt időfüggő feltevését célzottan reprodukáltuk. Claude külön
AUTH/SECURITY változtatásában indokolt a teszt által valóban elfogyasztott kód
rögzítése, a releváns időforrások determinisztikus kezelése és az időablakon átívelő
azonos-kód replay 403-as regressziója. Nem megoldás a 403-as elvárás 200-ra írása,
a replay-védelem kikapcsolása vagy a teszt kihagyása/retry-jal elfedése.

A helyi négy kontroll nem zár ki minden más biztonsági vagy konkurenciahibát;
MySQL-t és párhuzamos kéréseket ez a vizsgálat nem mért. A jelenlegi bizonyíték
az adott CI-bukást előidéző időablak-feltevést és az azonos kód szekvenciális
elutasítását különíti el.

A célzott hosted újraindítási kísérlet:

```bash
gh run rerun --repo bizsis/adatdusito --job 133005516776
```

HTTP 403-as környezeti hálózati tiltás miatt nem volt elindítható. A jelentés
PR-push-a a meglévő, változatlan workflow alapján új **teljes CI-t** indít;
az eredményét külön kell megfigyelni. A #27 draft marad; nincs main-merge,
VPS-telepítés vagy a #29 dokumentációs PR-jével való összekeverés.
