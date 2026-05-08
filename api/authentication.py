"""Custom authentication for the API."""
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from django.conf import settings
from .models import WorkerAPIKey


class WorkerAPIKeyAuthentication(BaseAuthentication):
    """Authenticate using a WorkerAPIKey from the X-Api-Key header."""
    
    def authenticate(self, request):
        """Authenticate the request using the API key."""
        # Get the API key from the header
        custom_header = getattr(settings, 'API_KEY_CUSTOM_HEADER', 'HTTP_X_API_KEY')
        key_string = request.META.get(custom_header)
        
        if not key_string:
            return None  # Let other authentication methods handle it
        
        # Try to find and validate the key
        try:
            # The rest_framework_api_key package provides an is_valid method
            # that checks if the key string matches a stored hashed key
            is_valid = WorkerAPIKey.objects.is_valid(key_string)
            
            if not is_valid:
                raise AuthenticationFailed('Invalid API key.')
            
            # Get the key object by the prefix (first 8 chars)
            prefix = key_string.split('.')[0] if '.' in key_string else key_string[:8]
            key_obj = WorkerAPIKey.objects.get(prefix=prefix)
            
            if key_obj.revoked:
                raise AuthenticationFailed('API key has been revoked.')
            
            # Return the key object as the authentication
            # request.auth will be set to key_obj by DRF
            return (None, key_obj)
        except WorkerAPIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid API key.')
        except Exception as e:
            raise AuthenticationFailed(f'Authentication failed: {str(e)}')


class HasWorkerAPIKey(BasePermission):
    """Permission class that checks if the request has been authenticated with an API key."""
    
    def has_permission(self, request, view):
        """Check if request.auth is a WorkerAPIKey object."""
        # After authentication, request.auth should be the WorkerAPIKey object
        return isinstance(request.auth, WorkerAPIKey)


