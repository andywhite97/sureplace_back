from django.contrib import admin


class GrantAdmin(admin.ModelAdmin):
    readonly_fields = ("granted_by", "granted_at")

    def get_form(self, request, obj=None, **kwargs):
        base = super().get_form(request, obj, **kwargs)

        class ActorForm(base):
            def clean(self):
                data = super().clean()
                if not self.instance._state.adding:
                    return data
                self.instance.granted_by = request.user
                package = data.get("source_package")
                if package:
                    self.instance.amount = package.price
                    self.instance.duration_days = package.duration_days
                if data.get("plan") and hasattr(self.instance, "amount"):
                    self.instance.amount = data["plan"].price
                return data

        return ActorForm

    def has_delete_permission(self, request, obj=None):
        return False
