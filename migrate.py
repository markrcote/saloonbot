#!/usr/bin/env python3
"""
Database migration script for saloonbot.

This script helps with database initialization and migration management.
"""

import argparse
import logging
import os
import sys

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def init_db():
    """Initialize the database by creating all tables."""
    try:
        from cardgames.db import init_db as db_init
        logging.info("Initializing database...")
        db_init()
        logging.info("Database initialized successfully!")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        sys.exit(1)


def upgrade_db():
    """Run Alembic migrations to upgrade the database."""
    try:
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config("alembic.ini")
        logging.info("Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        logging.info("Database upgraded successfully!")
    except Exception as e:
        logging.error(f"Failed to upgrade database: {e}")
        sys.exit(1)


def downgrade_db(revision="-1"):
    """Rollback database migrations."""
    try:
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config("alembic.ini")
        logging.info(f"Rolling back to revision {revision}...")
        command.downgrade(alembic_cfg, revision)
        logging.info("Database downgraded successfully!")
    except Exception as e:
        logging.error(f"Failed to downgrade database: {e}")
        sys.exit(1)


def create_migration(message):
    """Create a new migration."""
    try:
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config("alembic.ini")
        logging.info(f"Creating new migration: {message}")
        command.revision(alembic_cfg, message=message, autogenerate=True)
        logging.info("Migration created successfully!")
    except Exception as e:
        logging.error(f"Failed to create migration: {e}")
        sys.exit(1)


def show_history():
    """Show migration history."""
    try:
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config("alembic.ini")
        command.history(alembic_cfg)
    except Exception as e:
        logging.error(f"Failed to show history: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Database migration management for saloonbot'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Init command
    subparsers.add_parser('init', help='Initialize the database (create tables)')
    
    # Upgrade command
    subparsers.add_parser('upgrade', help='Upgrade database to latest migration')
    
    # Downgrade command
    downgrade_parser = subparsers.add_parser('downgrade', help='Rollback database migrations')
    downgrade_parser.add_argument(
        '--revision', '-r',
        default='-1',
        help='Revision to downgrade to (default: -1 for previous)'
    )
    
    # Create migration command
    create_parser = subparsers.add_parser('create', help='Create a new migration')
    create_parser.add_argument(
        'message',
        help='Migration message/description'
    )
    
    # History command
    subparsers.add_parser('history', help='Show migration history')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'init':
        init_db()
    elif args.command == 'upgrade':
        upgrade_db()
    elif args.command == 'downgrade':
        downgrade_db(args.revision)
    elif args.command == 'create':
        create_migration(args.message)
    elif args.command == 'history':
        show_history()


if __name__ == '__main__':
    main()
