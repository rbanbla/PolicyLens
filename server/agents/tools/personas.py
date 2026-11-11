import random
import re
from ...models import Persona

SNAPSHOT = ('uuid', 'persona', 'professional_persona', 'family_persona', 'sex', 'age', 'marital_status', 'family_type',
            'housing_type', 'education_level', 'occupation', 'district', 'province')
TEXTS = ('persona', 'professional_persona', 'family_persona')
SEARCHED = ('occupation', 'family_type', 'housing_type', 'marital_status', 'district', 'persona', 'professional_persona', 'family_persona')


def match_persona(hint, taken=(), rng=random):
    # A role gets a person only when someone in the sample fits its age range and at least one keyword; an unrelated person would mislead.
    people = Persona.objects.filter(age__gte=hint['age_min'], age__lte=hint['age_max']).exclude(uuid__in=taken)
    words = [word.strip() for word in hint['keywords'] if word.strip()]
    scored = [(sum(word in ' '.join(getattr(person, field) for field in SEARCHED) for word in words), person) for person in people]
    best = max((score for score, _ in scored), default=0)
    if not best:
        return None
    person = rng.choice([person for score, person in scored if score == best])
    return anonymized({field: getattr(person, field) for field in SNAPSHOT})


def anonymized(snapshot):
    # Every text opens with "<name> 씨는". The name is deleted before the run stores or sends it, so no agent can say it.
    name = re.match(r'(\S+) 씨', snapshot['persona'])
    if name:
        names = '|'.join(map(re.escape, (name.group(1), name.group(1)[1:])))
        pattern = re.compile(rf'(?:{names}) 씨(?:는|가|를|와|의|에게|도)?\s*')
        for field in TEXTS:
            snapshot[field] = pattern.sub('', snapshot[field]).replace(name.group(1), '')
    return snapshot


def match_personas(roles, rng=random):
    personas = []
    for role in roles:
        personas.append(match_persona(role['persona_hint'], [p['uuid'] for p in personas if p], rng))
    return personas
