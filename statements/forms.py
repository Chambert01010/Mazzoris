from django.contrib.auth.forms import AuthenticationForm


class MazzorisAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Por favor introduzca nombre de usuario y contraseña correctos.",
    }
