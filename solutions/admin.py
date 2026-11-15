from django.contrib import admin
from .models import SolutionRequest, SolutionQuota


@admin.register(SolutionRequest)
class SolutionRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'problem', 'language', 'status', 'created_at')
    list_filter = ('status', 'language')
    readonly_fields = ('user', 'problem', 'code', 'language', 'status', 'fingerprint', 'explanation', 'solution_code', 'time_complexity', 'space_complexity', 'error_message', 'created_at', 'started_at', 'finished_at')

    def has_add_permission(self, request):
        return False


admin.site.register(SolutionQuota)
