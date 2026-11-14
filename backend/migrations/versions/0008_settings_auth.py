"""Encrypted settings, usernames and authentication methods; no business data rewrites."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
TABLES = [
    "system_configuration",
    "system_secret_settings",
    "auth_challenges",
    "external_identities",
    "user_passkeys",
    "user_totp_devices",
    "user_recovery_codes",
]


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("username", sa.String(80), nullable=True))
        b.add_column(
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        b.add_column(
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        b.add_column(
            sa.Column(
                "mfa_reset_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        b.alter_column("email", existing_type=sa.String(254), nullable=True)
    c = op.get_bind()
    # Disjoint namespace (@ is forbidden in usernames), stable and collision-free IDs.
    rows = c.execute(sa.text("SELECT id FROM users")).all()
    for (id,) in rows:
        c.execute(
            sa.text("UPDATE users SET username=:u WHERE id=:i"),
            {"u": f"user-{id}", "i": id},
        )
    with op.batch_alter_table("users") as b:
        b.alter_column("username", existing_type=sa.String(80), nullable=False)
        b.create_unique_constraint("uq_users_username", ["username"])
    op.add_column(
        "tenants",
        sa.Column(
            "onboarding_state", sa.String(32), nullable=False, server_default="existing"
        ),
    )
    op.add_column(
        "login_sessions",
        sa.Column(
            "auth_method", sa.String(24), nullable=False, server_default="password"
        ),
    )
    op.add_column(
        "login_sessions",
        sa.Column(
            "mfa_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "login_sessions", sa.Column("reauthenticated_at", sa.DateTime(), nullable=True)
    )
    op.create_table(
        "system_configuration",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    op.create_table(
        "system_secret_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
    )
    op.create_table(
        "auth_challenges",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
    )
    for field in ["purpose", "user_id", "expires_at"]:
        op.create_index("ix_auth_challenges_" + field, "auth_challenges", [field])
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "subject"),
    )
    op.create_index(
        "ix_external_identities_user_id", "external_identities", ["user_id"]
    )
    op.create_table(
        "user_passkeys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rp_id", sa.String(253), nullable=False),
        sa.Column("credential_id", sa.Text(), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime()),
    )
    op.create_index("ix_user_passkeys_user_id", "user_passkeys", ["user_id"])
    op.create_table(
        "user_totp_devices",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_counter", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "user_recovery_codes",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("used_at", sa.DateTime()),
    )


def downgrade():
    c = op.get_bind()
    if c.scalar(
        sa.text(
            "SELECT COUNT(*) FROM audit_events WHERE action LIKE 'auth09.%' OR action LIKE 'settings09.%'"
        )
    ) or c.scalar(sa.text("SELECT COUNT(*) FROM users WHERE email IS NULL")):
        raise RuntimeError(
            "Authentication configuration changed; use the verified backup recovery plan."
        )
    for name in reversed(TABLES):
        op.drop_table(name)
    for col in ["auth_method", "mfa_verified", "reauthenticated_at"]:
        op.drop_column("login_sessions", col)
    op.drop_column("tenants", "onboarding_state")
    with op.batch_alter_table("users") as b:
        b.drop_constraint("uq_users_username", type_="unique")
        for col in [
            "username",
            "email_verified",
            "must_change_password",
            "mfa_reset_required",
        ]:
            b.drop_column(col)
        b.alter_column("email", existing_type=sa.String(254), nullable=False)
