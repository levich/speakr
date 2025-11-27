"""
LDAP authentication service.

This module provides LDAP authentication functionality using ldap3.
"""

import os
from ldap3 import Server, Connection, ALL, SUBTREE
from src.database import db
from src.models import User


def is_ldap_enabled():
    """Check if LDAP authentication is enabled."""
    return os.environ.get('LDAP_ENABLED', 'false').lower() == 'true'


def get_ldap_config():
    """Get LDAP configuration from environment variables."""
    if not is_ldap_enabled():
        return None
    
    return {
        'server_url': os.environ.get('LDAP_SERVER_URL'),
        'base_dn': os.environ.get('LDAP_BASE_DN'),
        'bind_dn': os.environ.get('LDAP_BIND_DN'),  # Optional: for authenticated bind
        'bind_password': os.environ.get('LDAP_BIND_PASSWORD'),  # Optional
        'user_search_filter': os.environ.get('LDAP_USER_SEARCH_FILTER', '(uid={username})'),
        'user_dn_template': os.environ.get('LDAP_USER_DN_TEMPLATE'),  # Optional: e.g., uid={username},ou=users,dc=example,dc=com
        'email_attribute': os.environ.get('LDAP_EMAIL_ATTRIBUTE', 'mail'),
        'name_attribute': os.environ.get('LDAP_NAME_ATTRIBUTE', 'cn'),
        'use_tls': os.environ.get('LDAP_USE_TLS', 'false').lower() == 'true',
        'use_ssl': os.environ.get('LDAP_USE_SSL', 'false').lower() == 'true',
    }


def authenticate_ldap_user(username, password):
    """
    Authenticate a user against LDAP server.
    
    Args:
        username: Username to authenticate
        password: Password to verify
        
    Returns:
        Tuple of (user_object, error_message)
        user_object: User model instance if successful, None otherwise
        error_message: Error message if authentication failed, None otherwise
    """
    if not is_ldap_enabled():
        return None, "LDAP authentication is not enabled"
    
    config = get_ldap_config()
    if not config or not config['server_url'] or not config['base_dn']:
        return None, "LDAP configuration is incomplete"
    
    try:
        # Create server connection
        server = Server(
            config['server_url'],
            use_ssl=config['use_ssl'],
            get_info=ALL
        )
        
        # Determine user DN
        user_dn = None
        if config['user_dn_template']:
            # Use template to construct DN
            user_dn = config['user_dn_template'].format(username=username)
        else:
            # Search for user DN
            bind_conn = None
            try:
                # First, bind with service account if provided
                if config['bind_dn'] and config['bind_password']:
                    bind_conn = Connection(
                        server,
                        user=config['bind_dn'],
                        password=config['bind_password'],
                        auto_bind=True
                    )
                else:
                    # Anonymous bind
                    bind_conn = Connection(server, auto_bind=True)
                
                # Search for user
                search_filter = config['user_search_filter'].format(username=username)
                bind_conn.search(
                    search_base=config['base_dn'],
                    search_filter=search_filter,
                    search_scope=SUBTREE,
                    attributes=[config['email_attribute'], config['name_attribute']]
                )
                
                if bind_conn.entries:
                    user_dn = bind_conn.entries[0].entry_dn
                else:
                    return None, "User not found in LDAP directory"
                    
            finally:
                if bind_conn:
                    bind_conn.unbind()
        
        if not user_dn:
            return None, "Could not determine user DN"
        
        # Try to authenticate with user credentials
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=True
        )
        
        # If we get here, authentication was successful
        # Fetch user attributes
        user_conn.search(
            search_base=user_dn,
            search_filter='(objectClass=*)',
            search_scope=SUBTREE,
            attributes=[config['email_attribute'], config['name_attribute']]
        )
        
        email = None
        name = None
        
        if user_conn.entries:
            entry = user_conn.entries[0]
            email_attr = getattr(entry, config['email_attribute'], None)
            name_attr = getattr(entry, config['name_attribute'], None)
            
            if email_attr:
                email = str(email_attr) if hasattr(email_attr, '__str__') else email_attr
            if name_attr:
                name = str(name_attr) if hasattr(name_attr, '__str__') else name_attr
        
        user_conn.unbind()
        
        # Find or create user in database
        if not email:
            email = f"{username}@ldap.local"  # Fallback email
        
        user = User.query.filter_by(
            email=email,
            auth_method='ldap'
        ).first()
        
        if not user:
            # Check if user exists with different auth method
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                return None, f"User with email {email} already exists with different authentication method"
            
            # Create new user
            db_username = username
            # Ensure username is unique
            base_username = db_username
            counter = 1
            while User.query.filter_by(username=db_username).first():
                db_username = f"{base_username}{counter}"
                counter += 1
            
            user = User(
                username=db_username,
                email=email,
                auth_method='ldap',
                ldap_dn=user_dn,
                name=name if name else None,
                password=None  # No password stored for LDAP users
            )
            db.session.add(user)
            db.session.commit()
        else:
            # Update LDAP DN if it changed
            if user.ldap_dn != user_dn:
                user.ldap_dn = user_dn
                if name and not user.name:
                    user.name = name
                db.session.commit()
        
        return user, None
        
    except Exception as e:
        return None, f"LDAP authentication failed: {str(e)}"

