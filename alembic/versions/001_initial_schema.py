"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-01-01 05:53:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('discord_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('wallet', sa.Numeric(precision=10, scale=2), server_default='0', nullable=True),
        sa.Column('games_played', sa.Integer(), server_default='0', nullable=True),
        sa.Column('games_won', sa.Integer(), server_default='0', nullable=True),
        sa.Column('games_lost', sa.Integer(), server_default='0', nullable=True),
        sa.Column('games_tied', sa.Integer(), server_default='0', nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_discord_id', 'users', ['discord_id'], unique=True)
    
    # Create games table
    op.create_table(
        'games',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game_id', UUID(as_uuid=True), nullable=False),
        sa.Column('guild_id', sa.BigInteger(), nullable=True),
        sa.Column('channel_id', sa.BigInteger(), nullable=True),
        sa.Column('state', sa.Text(), server_default='waiting', nullable=False),
        sa.Column('game_data', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_games_game_id', 'games', ['game_id'], unique=True)
    op.create_index('ix_games_guild_id', 'games', ['guild_id'], unique=False)
    op.create_index('ix_games_channel_id', 'games', ['channel_id'], unique=False)
    op.create_index('ix_games_state', 'games', ['state'], unique=False)
    op.create_index('idx_guild_channel', 'games', ['guild_id', 'channel_id'], unique=False)
    op.create_index('idx_state_updated', 'games', ['state', 'updated_at'], unique=False)
    
    # Create game_players table
    op.create_table(
        'game_players',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('game_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('hand', JSONB(), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_game_position', 'game_players', ['game_id', 'position'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_game_position', table_name='game_players')
    op.drop_table('game_players')
    
    op.drop_index('idx_state_updated', table_name='games')
    op.drop_index('idx_guild_channel', table_name='games')
    op.drop_index('ix_games_state', table_name='games')
    op.drop_index('ix_games_channel_id', table_name='games')
    op.drop_index('ix_games_guild_id', table_name='games')
    op.drop_index('ix_games_game_id', table_name='games')
    op.drop_table('games')
    
    op.drop_index('ix_users_discord_id', table_name='users')
    op.drop_table('users')
