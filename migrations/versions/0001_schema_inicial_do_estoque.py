"""schema inicial do estoque

Revision ID: 0001
Revises: 
Create Date: 2026-10-03 11:00:37.340686
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('outbox_messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('message_id', sa.String(), nullable=False),
    sa.Column('message_type', sa.String(), nullable=False),
    sa.Column('envelope', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('trace_headers', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('message_id')
    )
    op.create_index('idx_outbox_messages_pending', 'outbox_messages', ['id'], unique=False, postgresql_where='published_at IS NULL')
    op.create_table('processed_messages',
    sa.Column('message_id', sa.String(), nullable=False),
    sa.Column('message_type', sa.String(), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('message_id')
    )
    op.create_table('reservations',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('saga_id', sa.String(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('saga_id')
    )
    op.create_index(op.f('ix_reservations_order_id'), 'reservations', ['order_id'], unique=False)
    op.create_table('stock_items',
    sa.Column('part_id', sa.String(), nullable=False),
    sa.Column('sku', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('quantity_on_hand', sa.Integer(), server_default='0', nullable=False),
    sa.Column('quantity_reserved', sa.Integer(), server_default='0', nullable=False),
    sa.Column('min_stock_level', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('quantity_on_hand >= 0', name='ck_stock_items_on_hand_non_negative'),
    sa.CheckConstraint('quantity_reserved <= quantity_on_hand', name='ck_stock_items_reserved_within_on_hand'),
    sa.CheckConstraint('quantity_reserved >= 0', name='ck_stock_items_reserved_non_negative'),
    sa.PrimaryKeyConstraint('part_id')
    )
    op.create_table('reservation_items',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('reservation_id', sa.String(), nullable=False),
    sa.Column('part_id', sa.String(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reservation_items_reservation_id'), 'reservation_items', ['reservation_id'], unique=False)
    op.create_table('stock_movements',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('part_id', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('reservation_id', sa.String(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['part_id'], ['stock_items.part_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_stock_movements_part_id_created_at', 'stock_movements', ['part_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_stock_movements_part_id_created_at', table_name='stock_movements')
    op.drop_table('stock_movements')
    op.drop_index(op.f('ix_reservation_items_reservation_id'), table_name='reservation_items')
    op.drop_table('reservation_items')
    op.drop_table('stock_items')
    op.drop_index(op.f('ix_reservations_order_id'), table_name='reservations')
    op.drop_table('reservations')
    op.drop_table('processed_messages')
    op.drop_index('idx_outbox_messages_pending', table_name='outbox_messages', postgresql_where='published_at IS NULL')
    op.drop_table('outbox_messages')
