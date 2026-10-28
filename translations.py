"""Lightweight translation-file structure (F16).

A dict per language keyed by short string keys, a `t(key)` helper, and the
active language from the session (default English). Extensible: add keys,
screens or languages here without a build step. Client-facing PDFs stay English.
"""
from flask import session

DEFAULT_LANG = 'en'
SUPPORTED = ('en', 'es')

TRANSLATIONS = {
    'en': {
        # crew login
        'crew_signin': 'Crew Sign In',
        'enter_phone_pin': 'Enter your phone number and PIN.',
        'phone_number': 'Phone number',
        'pin': 'PIN',
        'sign_in': 'Sign in',
        'forgot_pin': 'Forgot your PIN? Ask your foreman to reset it.',
        # crew home
        'crew_portal': 'Crew portal',
        'hi': 'Hi,',
        'sign_out': 'Sign out',
        'clocked_in': 'Clocked in',
        'since': 'Since',
        'hours_so_far': 'h so far',
        'clock_in': 'Clock in',
        'clock_out': 'Clock out',
        'no_jobs': 'No jobs assigned yet — ask your foreman to add you.',
        'your_tasks': 'Your tasks',
        'due': 'due',
        'start': 'Start',
        'mark_done': 'Mark done',
        'reopen': 'Reopen',
        'no_tasks': 'No tasks assigned right now.',
        'foreman_add_tasks': 'Your foreman will add them here.',
        'status_done': 'done',
        'status_in_progress': 'in progress',
        'status_assigned': 'to do',
        'lang_name': 'English',
    },
    'es': {
        'crew_signin': 'Acceso de cuadrilla',
        'enter_phone_pin': 'Ingrese su número de teléfono y PIN.',
        'phone_number': 'Número de teléfono',
        'pin': 'PIN',
        'sign_in': 'Entrar',
        'forgot_pin': '¿Olvidó su PIN? Pida a su capataz que lo reinicie.',
        'crew_portal': 'Portal de la cuadrilla',
        'hi': 'Hola,',
        'sign_out': 'Salir',
        'clocked_in': 'Registrado',
        'since': 'Desde',
        'hours_so_far': 'h hasta ahora',
        'clock_in': 'Registrar entrada',
        'clock_out': 'Registrar salida',
        'no_jobs': 'Aún no tiene trabajos asignados — pida a su capataz que lo agregue.',
        'your_tasks': 'Sus tareas',
        'due': 'para',
        'start': 'Comenzar',
        'mark_done': 'Marcar hecho',
        'reopen': 'Reabrir',
        'no_tasks': 'No hay tareas asignadas en este momento.',
        'foreman_add_tasks': 'Su capataz las agregará aquí.',
        'status_done': 'hecho',
        'status_in_progress': 'en progreso',
        'status_assigned': 'por hacer',
        'lang_name': 'Español',
    },
}


def get_lang():
    try:
        lang = session.get('lang', DEFAULT_LANG)
    except Exception:
        lang = DEFAULT_LANG
    return lang if lang in TRANSLATIONS else DEFAULT_LANG


def t(key):
    """Translate a key for the active language, falling back to English then
    the key itself."""
    lang = get_lang()
    return (TRANSLATIONS.get(lang, {}).get(key)
            or TRANSLATIONS['en'].get(key)
            or key)
