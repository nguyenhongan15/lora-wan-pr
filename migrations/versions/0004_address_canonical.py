"""address.canonical (geocoding cache, tier 1)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-05

Theo data-architecture.md §3.4 + business-logic.md geocoding cascade.

Đặt trong schema `address` (đã tạo ở 0001). UNIQUE(normalized_query) để cache
hit chính xác. `display_name_unaccent` là generated column dùng cho fuzzy
search (pg_trgm) trong tương lai — chưa expose qua API ở v0.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres `unaccent()` được khai báo STABLE (dictionary có thể reload),
    # nên không xài được trực tiếp trong GENERATED STORED column. Bọc bằng
    # wrapper IMMUTABLE để binding tới dictionary cố định.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.immutable_unaccent(text)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;
        """
    )

    op.execute(
        """
        CREATE TABLE address.canonical (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            normalized_query     text NOT NULL UNIQUE,
            location             geography(Point, 4326) NOT NULL,
            display_name         text NOT NULL,
            display_name_unaccent text GENERATED ALWAYS AS (
                public.immutable_unaccent(lower(display_name))
            ) STORED,
            provider             text NOT NULL,
            confidence           real NOT NULL DEFAULT 1.0,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_provider CHECK (
                provider IN ('postgres','nominatim','vietmap','goong','google')
            ),
            CONSTRAINT chk_confidence CHECK (confidence BETWEEN 0 AND 1)
        );
        """
    )

    # GiST cho proximity search nếu cần sau này.
    op.execute(
        "CREATE INDEX address_canonical_loc_gix ON address.canonical USING gist (location);"
    )
    # pg_trgm cho fuzzy match display_name_unaccent (defer query, index giờ).
    op.execute(
        "CREATE INDEX address_canonical_display_trgm "
        "ON address.canonical USING gin (display_name_unaccent gin_trgm_ops);"
    )

    op.execute(
        "COMMENT ON TABLE address.canonical IS "
        "'Geocoding cache (tier 1) cho cascade lookup. UNIQUE(normalized_query).';"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS address.canonical;")
    op.execute("DROP FUNCTION IF EXISTS public.immutable_unaccent(text);")
