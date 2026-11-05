from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe
from ..models import StudyCase

ROLES = {"student": "학생", "faculty": "교수", "administration": "학사행정"}


def published():
    return StudyCase.objects.filter(published=True).prefetch_related("clauses").order_by("-created_at")


@require_safe
def home(request):
    return render(request, "home.html")


@require_safe
def catalogue(request):
    return render(request, "catalogue.html", {"policies": published()})


@require_safe
def detail(request, pk):
    case = get_object_or_404(published(), pk=pk)
    clauses = case.clauses.prefetch_related("mock_turns__revision").order_by("pk")
    for clause in clauses:
        for turn in clause.mock_turns.all():
            turn.role_label = ROLES.get(turn.role, turn.role)
    return render(request, "policy.html", {"case": case, "clauses": clauses})
