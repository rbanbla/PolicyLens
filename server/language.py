from django.utils import translation


class Language:
    """The page language is the session's choice; a run's own views switch to the run's language. Nothing leaks to the next request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        translation.activate(request.session.get('language', 'ko'))
        try:
            return self.get_response(request)
        finally:
            translation.deactivate()
