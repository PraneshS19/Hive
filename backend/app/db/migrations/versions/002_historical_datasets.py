"""002_historical_datasets

Revision ID: 002_historical_datasets
Revises: 001_initial_schema
Create Date: 2026-10-21 12:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_historical_datasets'
down_revision: str | None = '001_initial_schema'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create datasets registry table
    op.create_table(
        'datasets',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('asset_name', sa.String(length=100), nullable=True),
        sa.Column('exchange', sa.String(length=20), nullable=False, server_default='NSE'),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('provenance', sa.Text(), nullable=False),
        sa.Column('timeframe', sa.String(length=20), nullable=False, server_default='1d'),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('candle_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_adjusted', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('adjustment_status', sa.String(length=30), nullable=False, server_default='UNADJUSTED'),
        sa.Column('quality_status', sa.String(length=30), nullable=False, server_default='VALIDATED'),
        sa.Column('validation_report_json', sa.Text(), nullable=True),
        sa.Column('license_info', sa.String(length=200), nullable=False, server_default='Public educational / research usage'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_datasets_symbol', 'datasets', ['symbol'])

    # 2. Add dataset_id to candles if not exists
    # Using batch_alter_table for SQLite compatibility
    with op.batch_alter_table('candles') as batch_op:
        batch_op.add_column(sa.Column('dataset_id', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_candles_dataset_id', ['dataset_id'])


def downgrade() -> None:
    with op.batch_alter_table('candles') as batch_op:
        batch_op.drop_index('ix_candles_dataset_id')
        batch_op.drop_column('dataset_id')

    op.drop_index('ix_datasets_symbol', table_name='datasets')
    op.drop_table('datasets')
