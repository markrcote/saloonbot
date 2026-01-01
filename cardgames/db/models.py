"""Database models for saloonbot."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Column, DateTime, ForeignKey, Integer, 
    Numeric, String, Text, Index
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """User model representing a player."""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    discord_id = Column(Text, unique=True, nullable=False, index=True)
    name = Column(Text, nullable=False)
    wallet = Column(Numeric(precision=10, scale=2), default=0)
    games_played = Column(Integer, default=0)
    games_won = Column(Integer, default=0)
    games_lost = Column(Integer, default=0)
    games_tied = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship to game_players
    game_participations = relationship("GamePlayer", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, discord_id='{self.discord_id}', name='{self.name}')>"


class Game(Base):
    """Game model representing a blackjack game."""
    __tablename__ = 'games'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(UUID(as_uuid=True), unique=True, nullable=False, index=True)
    guild_id = Column(BigInteger, index=True)
    channel_id = Column(BigInteger, index=True)
    state = Column(Text, nullable=False, default='waiting', index=True)  # waiting, active, finished
    game_data = Column(JSONB)  # Stores serialized game state
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationship to game_players
    players = relationship("GamePlayer", back_populates="game", cascade="all, delete-orphan")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_guild_channel', 'guild_id', 'channel_id'),
        Index('idx_state_updated', 'state', 'updated_at'),
    )
    
    def __repr__(self):
        return f"<Game(id={self.id}, game_id='{self.game_id}', state='{self.state}')>"


class GamePlayer(Base):
    """Join table for players in a game."""
    __tablename__ = 'game_players'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    position = Column(Integer, nullable=False)  # Order in the players list
    hand = Column(JSONB)  # Current hand as list of cards
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    game = relationship("Game", back_populates="players")
    user = relationship("User", back_populates="game_participations")
    
    # Ensure unique position per game
    __table_args__ = (
        Index('idx_game_position', 'game_id', 'position', unique=True),
    )
    
    def __repr__(self):
        return f"<GamePlayer(game_id={self.game_id}, user_id={self.user_id}, position={self.position})>"
