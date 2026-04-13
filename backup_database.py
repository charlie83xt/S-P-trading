#!/usr/bin/env python3
"""
Automatic Database Backup System
Run this daily (or add to bot startup)
"""


import os
import shutil
from datetime import datetime, timedelta
import glob


# Configuration
DB_PATH = 'data/db/market_data.db'
BACKUP_DIR = 'data/backups'
DAILY_DIR = os.path.join(BACKUP_DIR, 'daily')
WEEKLY_DIR = os.path.join(BACKUP_DIR, 'weekly')
KEEP_DAILY = 7  # Keep last 7 days
KEEP_WEEKLY = 4  # Keep last 4 weeks


def ensure_directories():
    """Create backup directories"""
    os.makedirs(DAILY_DIR, exist_ok=True)
    os.makedirs(WEEKLY_DIR, exist_ok=True)


def backup_database():
    """Create timestamped backup"""
    if not os.path.exists(DB_PATH):
        print(f"⚠️  Database not found: {DB_PATH}")
        return None
    
    # Create timestamp
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    date_only = now.strftime("%Y%m%d")
    
    # Daily backup
    daily_backup = os.path.join(DAILY_DIR, f"market_data_{timestamp}.db")
    shutil.copy2(DB_PATH, daily_backup)
    
    # Get file size
    size_mb = os.path.getsize(daily_backup) / (1024 * 1024)
    
    print(f"✅ Daily backup created:")
    print(f"   {daily_backup}")
    print(f"   Size: {size_mb:.2f} MB")
    
    # Weekly backup (on Fridays or if it's been 7 days)
    if now.weekday() == 4 or should_create_weekly():
        week_num = now.strftime("%Y-W%U")
        weekly_backup = os.path.join(WEEKLY_DIR, f"market_data_{week_num}.db")
        shutil.copy2(DB_PATH, weekly_backup)
        print(f"✅ Weekly backup created: {weekly_backup}")
    
    return daily_backup


def should_create_weekly():
    """Check if we need a weekly backup"""
    weekly_backups = glob.glob(os.path.join(WEEKLY_DIR, "*.db"))
    if not weekly_backups:
        return True
    
    # Get most recent weekly backup
    latest = max(weekly_backups, key=os.path.getmtime)
    latest_time = datetime.fromtimestamp(os.path.getmtime(latest))
    
    # Create weekly if last one is >7 days old
    return (datetime.now() - latest_time).days >= 7


def cleanup_old_backups():
    """Remove old backups to save space"""
    now = datetime.now()
    
    # Clean daily backups (keep last KEEP_DAILY)
    daily_backups = sorted(
        glob.glob(os.path.join(DAILY_DIR, "*.db")),
        key=os.path.getmtime,
        reverse=True
    )
    
    for old_backup in daily_backups[KEEP_DAILY:]:
        os.remove(old_backup)
        print(f"🗑️  Deleted old daily backup: {os.path.basename(old_backup)}")
    
    # Clean weekly backups (keep last KEEP_WEEKLY)
    weekly_backups = sorted(
        glob.glob(os.path.join(WEEKLY_DIR, "*.db")),
        key=os.path.getmtime,
        reverse=True
    )
    
    for old_backup in weekly_backups[KEEP_WEEKLY:]:
        os.remove(old_backup)
        print(f"🗑️  Deleted old weekly backup: {os.path.basename(old_backup)}")


def list_backups():
    """Show all available backups"""
    print("\n" + "="*60)
    print("📦 AVAILABLE BACKUPS")
    print("="*60)
    
    # Daily backups
    daily_backups = sorted(glob.glob(os.path.join(DAILY_DIR, "*.db")), reverse=True)
    print(f"\n📅 Daily Backups ({len(daily_backups)}):")
    for backup in daily_backups[:5]:  # Show last 5
        size_mb = os.path.getsize(backup) / (1024 * 1024)
        mtime = datetime.fromtimestamp(os.path.getmtime(backup))
        print(f"  {os.path.basename(backup)} - {size_mb:.2f} MB - {mtime.strftime('%Y-%m-%d %H:%M')}")
    
    # Weekly backups
    weekly_backups = sorted(glob.glob(os.path.join(WEEKLY_DIR, "*.db")), reverse=True)
    print(f"\n📆 Weekly Backups ({len(weekly_backups)}):")
    for backup in weekly_backups:
        size_mb = os.path.getsize(backup) / (1024 * 1024)
        mtime = datetime.fromtimestamp(os.path.getmtime(backup))
        print(f"  {os.path.basename(backup)} - {size_mb:.2f} MB - {mtime.strftime('%Y-%m-%d %H:%M')}")


def restore_from_backup(backup_path):
    """Restore database from backup"""
    if not os.path.exists(backup_path):
        print(f"❌ Backup not found: {backup_path}")
        return False
    
    # Backup current database first
    if os.path.exists(DB_PATH):
        emergency_backup = DB_PATH + ".before_restore"
        shutil.copy2(DB_PATH, emergency_backup)
        print(f"⚠️  Current database backed up to: {emergency_backup}")
    
    # Restore
    shutil.copy2(backup_path, DB_PATH)
    print(f"✅ Database restored from: {backup_path}")
    return True


if __name__ == '__main__':
    import sys
    
    ensure_directories()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'list':
            list_backups()
        elif sys.argv[1] == 'restore' and len(sys.argv) > 2:
            restore_from_backup(sys.argv[2])
        else:
            print("Usage:")
            print("  python backup_database.py          # Create backup")
            print("  python backup_database.py list     # List backups")
            print("  python backup_database.py restore <path>  # Restore from backup")
    else:
        # Default: create backup
        backup_database()
        cleanup_old_backups()
        list_backups()



