"""
OAuth authentication service.

This module provides OAuth authentication functionality using authlib.
Supports multiple OAuth providers (Google, GitHub, etc.).
"""

import os
from authlib.integrations.flask_client import OAuth
from flask import url_for, session, redirect
from src.database import db
from src.models import User


def init_oauth(app):
    """Initialize OAuth client for the Flask app."""
    oauth = OAuth(app)
    
    # Check which OAuth providers are enabled
    google_enabled = os.environ.get('OAUTH_GOOGLE_ENABLED', 'false').lower() == 'true'
    github_enabled = os.environ.get('OAUTH_GITHUB_ENABLED', 'false').lower() == 'true'
    
    # Register Google OAuth
    if google_enabled:
        oauth.register(
            name='google',
            client_id=os.environ.get('OAUTH_GOOGLE_CLIENT_ID'),
            client_secret=os.environ.get('OAUTH_GOOGLE_CLIENT_SECRET'),
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={
                'scope': 'openid email profile'
            }
        )
    
    # Register GitHub OAuth
    if github_enabled:
        oauth.register(
            name='github',
            client_id=os.environ.get('OAUTH_GITHUB_CLIENT_ID'),
            client_secret=os.environ.get('OAUTH_GITHUB_CLIENT_SECRET'),
            authorize_url='https://github.com/login/oauth/authorize',
            authorize_params=None,
            access_token_url='https://github.com/login/oauth/access_token',
            access_token_params=None,
            api_base_url='https://api.github.com/',
            client_kwargs={'scope': 'user:email'}
        )
    
    return oauth


def get_oauth_providers():
    """Get list of enabled OAuth providers."""
    providers = []
    
    if os.environ.get('OAUTH_GOOGLE_ENABLED', 'false').lower() == 'true':
        providers.append({
            'name': 'google',
            'display_name': 'Google',
            'icon': 'fab fa-google'
        })
    
    if os.environ.get('OAUTH_GITHUB_ENABLED', 'false').lower() == 'true':
        providers.append({
            'name': 'github',
            'display_name': 'GitHub',
            'icon': 'fab fa-github'
        })
    
    return providers


def handle_oauth_callback(oauth, provider_name):
    """Handle OAuth callback and create/login user."""
    try:
        provider = oauth.providers[provider_name]
        token = provider.authorize_access_token()
        
        if provider_name == 'google':
            # For Google OpenID Connect, userinfo might be in token or need to be fetched
            user_info = token.get('userinfo')
            if not user_info:
                # Fetch user info using the access token
                resp = provider.get('https://www.googleapis.com/oauth2/v2/userinfo', token=token)
                if resp.status_code == 200:
                    user_info = resp.json()
                else:
                    return None, "Failed to fetch user info from Google"
            
            email = user_info.get('email')
            name = user_info.get('name', '')
            oauth_id = user_info.get('sub')
            picture = user_info.get('picture')
            
        elif provider_name == 'github':
            resp = provider.get('user', token=token)
            if resp.status_code != 200:
                return None, "Failed to fetch user info from GitHub"
            
            user_info = resp.json()
            
            email = user_info.get('email')
            if not email:
                # Try to get email from emails endpoint
                emails_resp = provider.get('user/emails', token=token)
                if emails_resp.status_code == 200:
                    emails = emails_resp.json()
                    if emails:
                        email = next((e['email'] for e in emails if e.get('primary')), emails[0]['email'])
            
            name = user_info.get('name', user_info.get('login', ''))
            oauth_id = str(user_info.get('id'))
            picture = user_info.get('avatar_url')
        else:
            return None, "Unsupported OAuth provider"
        
        if not email:
            return None, "Email not provided by OAuth provider"
        
        # Find or create user
        user = User.query.filter_by(
            email=email,
            auth_method='oauth',
            oauth_provider=provider_name
        ).first()
        
        if not user:
            # Check if user exists with different auth method
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                return None, f"User with email {email} already exists with different authentication method"
            
            # Create new user
            username = email.split('@')[0]
            # Ensure username is unique
            base_username = username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1
            
            user = User(
                username=username,
                email=email,
                auth_method='oauth',
                oauth_provider=provider_name,
                oauth_id=oauth_id,
                name=name if name else None,
                password=None  # No password for OAuth users
            )
            db.session.add(user)
            db.session.commit()
        
        return user, None
        
    except Exception as e:
        return None, str(e)

