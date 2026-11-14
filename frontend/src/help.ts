export const helpText = {
  roles:
    "A kijelölt szerepkörök engedélyei összeadódnak. Az egyedi tiltás minden szerepkörengedélyt felülír. Rendszerszintű jog ügyfélszerepkörhöz nem rendelhető.",
  scope:
    "A teljes kör a később létrehozott erőforrásokra is vonatkozik. Kijelölt kör esetén új cég vagy webáruház nem adódik hozzá automatikusan. A még céghez nem rendelt importadatokhoz teljes ügyfélkör szükséges.",
  smtp: "A mentett webes konfiguráció elsőbbséget kap az SMTP környezeti beállításaival szemben, és újraindítás nélkül érvényes. Mentés előtt a szerver ellenőrzi a titkosított kapcsolatot és a hitelesítést. Sikertelen ellenőrzéskor a korábbi konfiguráció megmarad.",
  secret:
    "A mező üresen hagyása megőrzi a korábbi titkot. Mentés után a jelszó nem kérhető vissza. A titkosításhoz üzemeltető által kezelt, külön fájlban tárolt kulcs szükséges.",
  smtpTest:
    "A teszt az SMTP-kiszolgáló válaszát mutatja. Az elfogadott levél postaládába érkezését nem tudjuk igazolni. Belső célcímhez csak az üzemeltető adhat külön engedélyt; a tesztküldések száma korlátozott.",
  auth: "A beállítás az új bejelentkezéseket szabályozza. Aktív superadmin nem maradhat használható bejelentkezési mód nélkül. A Google-fiók azonos e-mail esetén sem kapcsolódik automatikusan: először meglévő fiókkal kell bejelentkezni és összekapcsolni.",
  mfa: "A kötelező szerepkörök felhasználói második faktor nélkül nem kapnak teljes hozzáférést. Már aktív munkamenetnél is érvényesül. Az első belépéskor beállítható a TOTP. Alapértelmezésben egyik szerepkörnél sem kötelező.",
  passkey:
    "A passkey az eszközöd biztonságos hitelesítőjét használja. A szerver ellenőrzi a webhelyet, a kihívást és a felhasználó-ellenőrzést. A privát kulcs nem kerül az alkalmazáshoz. Többfaktorosnak csak a központi szabályzat szerint számít.",
  recovery:
    "A helyreállítási kódok csak egyszer láthatók és egyenként egyszer használhatók. Tárold őket biztonságos, külön helyen. Új kódkészlet létrehozása érvényteleníti a régit.",
  recoveryAdmin:
    "Más felhasználó TOTP-helyreállítását két külön, frissen több faktorral azonosított superadmin hagyja jóvá, dokumentált személyazonosság-ellenőrzés után. A fiók ezután új TOTP-beállításra kötelezett; minden munkamenete megszűnik.",
  security:
    "A rövidebb munkamenet-élettartam a már aktív munkameneteket is korlátozza. Az új jelszókövetelmény jelszó létrehozásakor vagy cseréjekor érvényesül, a meglévő hash-ek változatlanok. A belépési korlát közös Redis-alapú védelem.",
  registration:
    "Bekapcsolva e-mail-ellenőrzés és regisztrációs sebességkorlát véd. Az új munkaterület előfizetésre váró állapotú: nem kap kitalált próbakapacitást, és az import nem aktív. Alapértelmezetten kikapcsolt.",
  importMapping:
    "A fájl oszlopait belső mezőkhöz rendelheted. Az azonosítómező és pénzügyi jelentés jóváhagyása határozza meg a későbbi feldolgozást; ugyanazt az oszlopot ne rendeld ellentmondó mezőkhöz.",
  category:
    "A jóváhagyott kategóriafa közös minden ügyfél számára. A navigációs pontok és termékkategóriák különböznek; a forrásparaméterek kiválasztása nem módosítja a kategóriahierarchiát.",
  export:
    "A webáruházmotor mezősémája központi beállítás. Az ügyfél exportprofilja saját megfeleltetéseket tárol. A meglévő importadatok és forrásértékek változatlanok maradnak.",
} as const;
export type HelpKey = keyof typeof helpText;
export const groupLabels: Record<string, string> = {
  system: "Rendszeradminisztráció",
  tenants: "Ügyfelek",
  members: "Munkatársak",
  imports: "Import",
  exports: "Export",
  reference: "Referenciák",
  products: "Termékadatok",
  companies: "Cégek",
  webshops: "Webáruházak",
  audit: "Audit",
};
export const permissionDescriptions: Record<string, string> = {
  "system.settings.read":
    "Általános, levelezési és biztonsági konfiguráció megtekintése titkok nélkül.",
  "system.settings.manage":
    "Rendszerbeállítások módosítása és SMTP tesztelése. A hitelesítési szabályokhoz superadmin és friss újraazonosítás kell.",
  "system.roles.read":
    "Rendszerszerepkörök és jogosultsági katalógus megtekintése.",
  "system.roles.manage":
    "Rendszerszerepkörök létrehozása, módosítása és törlése a delegálási korlátokon belül.",
  "system.users.read": "Rendszerfiókok keresése és hozzáféréseik megtekintése.",
  "system.users.manage":
    "Rendszerfiókok, meghívók és hozzáférések kezelése; védett adminműveletekhez superadmin kell.",
  "system.audit.read":
    "Rendszerszintű és engedélyezett ügyfélkörhöz tartozó audit megtekintése.",
  "tenants.read":
    "Az engedélyezett ügyfelek nevének és állapotának megtekintése.",
  "tenants.create": "Új ügyfélmunkaterület létrehozása rendszerszinten.",
  "tenants.edit": "Engedélyezett ügyfél nevének módosítása.",
  "tenants.suspend": "Engedélyezett ügyfél felfüggesztése vagy újraaktiválása.",
  "tenants.access.manage":
    "Rendszerfelhasználó összes, kijelölt vagy ügyfél nélküli hozzáférési körének beállítása.",
  "members.read":
    "Saját munkaterület munkatársainak és szerepköreinek megtekintése.",
  "members.invite":
    "E-mailes meghívó küldése, visszavonása és újraküldése a saját ügyfélnél.",
  "members.manage":
    "Saját ügyféltagságok és erőforráskörök kezelése a globális fiók törlése nélkül.",
  "members.roles.manage":
    "Ügyfélszerepkörök, több szerepkör és egyedi engedélyek/tiltások kezelése.",
  "products.read":
    "Az aktív ügyfél beszállítói termékeinek és változásaiknak megtekintése.",
  "imports.read":
    "Beszállítók, importprofilok, fájlelőnézetek és feldolgozási előzmények olvasása.",
  "imports.create": "CSV/XLSX fájl feltöltése elemzésre és új import indítása.",
  "imports.manage":
    "Beszállítók, feldolgozási profilok és importbeállítások kezelése.",
  "imports.approve":
    "Oszlopmegfeleltetés és pénzügyi értelmezés jóváhagyása, feldolgozás engedélyezése.",
  "imports.cancel": "Saját ügyfél importfolyamatának megszakítása.",
  "exports.read": "Webáruházmotorok és saját exportprofilok megtekintése.",
  "exports.profile": "Ügyfélspecifikus exportmező-megfeleltetés mentése.",
  "exports.fields.manage":
    "Központi webáruházmotorok és exportmező-sémák módosítása.",
  "reference.read":
    "Közös kategóriafa, paraméterek és megengedett értékek keresése és olvasása.",
  "reference.manage":
    "Központi referenciaforrások és paraméter-hozzárendelések kezelése. A rögzített fa nem változik.",
  "audit.read":
    "Az aktív ügyfélhez tartozó műveleti és jogosultsági napló megtekintése.",
  "companies.read": "A hozzáférési körbe tartozó cégek megtekintése.",
  "companies.manage": "Cégnyilvántartás kezelése a saját ügyfélen belül.",
  "webshops.read": "A hozzáférési körbe tartozó webáruházak megtekintése.",
  "webshops.manage":
    "Webáruház-nyilvántartás kezelése a saját ügyfélen belül. Nem indít külső integrációt.",
};
export function auditLabel(code: string): string {
  return (
    (
      {
        "auth.login": "Bejelentkezés",
        "auth.logout": "Kijelentkezés",
        "auth.login_failed": "Sikertelen bejelentkezés",
        "auth.tenant_switch": "Munkaterület-váltás",
        "user.create": "Felhasználó létrehozása",
        "user.update": "Fiók módosítása",
        "user.password_change": "Saját jelszó cseréje",
        "tenant.create": "Ügyfél létrehozása",
        "tenant.update": "Ügyfél módosítása",
        "member.assign": "Tagság hozzárendelése",
        "member.update": "Tagság módosítása",
        "member.profile_update": "Munkatársi fiók módosítása",
        "member.create_user": "Munkatárs létrehozása",
        "setting.update": "Kompatibilitási beállítás módosítása",
        "access.role_create": "Szerepkör létrehozása",
        "access.role_update": "Szerepkör módosítása",
        "access.role_delete": "Szerepkör törlése",
        "access.user_update": "Szerepkörök és egyedi jogosultságok módosítása",
        "access.system_resources": "Erőforrás-hozzáférési kör módosítása",
        "access.invite_create": "Meghívó létrehozása",
        "access.invite_accept": "Meghívó elfogadása",
        "access.invite_resend": "Meghívó újraküldése",
        "access.invite_revoke": "Meghívó visszavonása",
        "access.invite_superseded": "Korábbi meghívó érvénytelenítése",
        "settings09.general": "Általános rendszerbeállítások módosítása",
        "settings09.smtp": "SMTP-konfiguráció módosítása",
        "settings09.smtp_test": "SMTP-teszt",
        "settings09.auth": "Bejelentkezési módok módosítása",
        "settings09.mfa": "Kétfaktoros szabályok módosítása",
        "settings09.security": "Biztonsági szabályok módosítása",
        "settings09.mfa_inherit":
          "Kötelező MFA megőrzése helyi szerepkörmásolatnál",
        "auth09.totp_setup": "TOTP-beállítás indítása",
        "auth09.totp_enabled": "TOTP aktiválása",
        "auth09.totp_disabled": "TOTP visszavonása",
        "auth09.totp_replaced": "TOTP-eszköz biztonságos cseréje",
        "auth09.mfa_failed": "Sikertelen második faktor",
        "auth09.recovery_used": "Helyreállítási kód felhasználása",
        "auth09.recovery_rotated": "Helyreállítási kódok újragenerálása",
        "auth09.reauth": "Újraazonosítás",
        "auth09.reauth_passkey": "Újraazonosítás passkeyjel",
        "auth09.session_revoked": "Munkamenet visszavonása",
        "auth09.passkey_registered": "Passkey regisztrálása",
        "auth09.passkey_deleted": "Passkey törlése",
        "auth09.passkey_failed": "Sikertelen passkey-ellenőrzés",
        "auth09.username_changed": "Felhasználónév módosítása",
        "auth09.system_user_create": "Rendszerfiók létrehozása",
        "auth09.admin_password_reset": "Adminisztrátori ideiglenes jelszó",
        "auth09.recovery_requested": "TOTP-helyreállítás kezdeményezése",
        "auth09.recovery_approved": "TOTP-helyreállítás jóváhagyása",
        "auth09.google_linked": "Google-fiók összekapcsolása",
        "auth09.google_unlinked": "Google-kapcsolat megszüntetése",
        "auth09.registration_verified": "E-mailes regisztráció megerősítése",
        "import.supplier": "Beszállító létrehozása",
        "import.upload": "Beszállítói fájl feltöltése",
        "import.approve": "Import jóváhagyása",
        "import.cancel": "Import megszakítása",
        "import.expire_source": "Importforrás eltávolítása",
        "export.engine_version": "Exportmező-séma verziójának mentése",
        "export.profile": "Saját exportprofil mentése",
      } as Record<string, string>
    )[code] || "Naplózott rendszerművelet"
  );
}
