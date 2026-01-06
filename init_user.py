#!/usr/bin/env python
"""
Initialize admin user for the app.
Run this once after deployment.
"""

from app import create_user, get_user_by_username

username = 'admin'
password = 'admin123'  # CHANGE THIS!

# Check if user already exists
existing_user = get_user_by_username(username)
if existing_user:
    print(f"User '{username}' already exists!")
else:
    try:
        create_user(username, password, 'admin')
        print(f"✅ Admin user '{username}' created successfully!")
        print(f"   Username: {username}")
        print(f"   Password: {password}")
        print("   ⚠️  CHANGE THE PASSWORD AFTER FIRST LOGIN!")
    except Exception as e:
        print(f"❌ Error creating user: {e}")
