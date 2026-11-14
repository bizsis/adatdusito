# Cloud & Teal UI design — CODEX 09 merged implementation

**Status:** CODEX 09 UI merged to `main` at `1d613fe`, deployment to VPS not yet confirmed. This file is design guidance; validate exact component implementation against current source.

## Visual tokens
| Purpose | Hex |
| --- | --- |
| Application background | `#F7F9FC` |
| Cards and content surfaces | `#FFFFFF` |
| Borders | `#E7EDF4` |
| Primary interactive teal | `#0D9488` |
| Informational blue | `#3B82F6` |
| Main text | `#172B4D` |
| Secondary text | `#64748B` |
| Success | `#16A34A` |
| Warning | `#F59E0B` |
| Danger | `#DC2626` |

- Light sidebar, white panels, subtle shadows and visible teal active navigation.
- Inter typography with robust system fallback.
- Unified spacing, focus states, responsive tables/forms and consistent 8–12 px corner radius.
- Lucide React icons, meaningful labels, titles and accessible names; avoid icon-only ambiguous actions.

## Information architecture
Top level: overview, tenants, product data, supplier imports, export, system access, system settings, **Audit as an independent main menu**.
System access: users, roles, grants, invitations.
System settings: general, SMTP, login methods, 2FA, security; add subscription/AI sections only when implemented.

## Permission editor rules
Group permissions by functional domain; three clear columns: **human-readable right → checkbox → plain-language description at the right**. Put underlying technical permission codes in an optional details affordance. Protect irreversible operations with clear confirmation.

## Contextual help
Place clickable, touch/keyboard-accessible help near complex field labels. Explain the actual outcome in Hungarian. Use consistent controls and avoid fake inactive UI or nonfunctional "coming soon" configuration settings.

## Safety and evolution
Do not refactor authorization away from the server. Frontend visibility never replaces backend checks. CODEX 09 introduces shared UI components and workflows; future component refactoring must preserve server-side tenant isolation. Handle non-JSON proxy 413 as a follow-up.
